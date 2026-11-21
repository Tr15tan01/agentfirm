"""Orchestrator: plans a task as a graph of agent subtasks, runs them, passes results between
agents, follows agent handoffs and writes one combined result (ADR 0005).

* **No tools, no shortcuts.** The orchestrator never calls a tool. Every action happens inside an
  agent subtask, under that agent's grants, the requester's permissions and the subtask's own
  approval gates. Approvals belong to one execution, so approving one subtask never authorises
  another, and nothing an upstream agent writes can approve anything.
* **Durable.** The plan is persisted (`plan.created`) before subtasks are created; subtask keys are
  unique per orchestrator, so a crashed run resumes without duplicating work.
* **No lost wake-ups.** A finishing subtask re-queues the orchestrator under a lock on the
  orchestrator row (engine `_set_terminal`); the orchestrator goes idle only after re-checking its
  subtasks under that same lock.
* **Upstream results are data.** They reach the next agent wrapped as untrusted content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select, update

from agentfirm.agents.contracts import (
    AgentError,
    AgentManifest,
    AgentResult,
    ArtifactRef,
    Claim,
    ErrorCode,
    HandoffRequest,
    UsageSummary,
)
from agentfirm.agents.registry import registry
from agentfirm.core.config import get_settings
from agentfirm.core.permissions import ROLE_PERMISSIONS, Role
from agentfirm.modules.agents.models import Agent, AgentVersion
from agentfirm.modules.identity.models import Membership
from agentfirm.modules.tasks.models import TERMINAL_STATUSES, ExecutionEvent, Task, TaskExecution

from .context import ExecutionContext, untrusted
from .errors import ExecutionHalted, StepError
from .events import EventSink, wake_workers
from .gateway.gateway import ModelGateway

#: Subtasks the planner may create, and the hard cap including agent handoffs.
MAX_PLANNED = 6
MAX_SUBTASKS = 10
#: Credits kept for the orchestrator itself (planning + synthesis).
RESERVE_CREDITS = 60
MIN_SUBTASK_CREDITS = 20
DEFAULT_TASK_CREDITS = 1500
MAX_TASK_CREDITS = 5000
MAX_DEPTH = 2
KEY = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


# ── Model I/O ────────────────────────────────────────────────────────────────


class PlannedSubtask(BaseModel):
    key: str = Field(description="short snake_case id, unique in the plan, e.g. 'research'")
    agent: str = Field(description="agent key from the list")
    intent: str | None = Field(default=None, description="one of that agent's intents, if clear")
    objective: str = Field(min_length=3, max_length=2000, description="self-contained instruction for that agent")
    depends_on: list[str] = Field(default_factory=list, description="keys of subtasks whose results this one needs")
    reason: str = ""


class OrchestrationPlan(BaseModel):
    subtasks: list[PlannedSubtask] = Field(min_length=1, max_length=MAX_PLANNED)
    rationale: str = ""


class Synthesis(BaseModel):
    overview: str = Field(description="markdown, at most ~200 words, built only from the subtask results")
    next_steps: list[str] = Field(default_factory=list, max_length=5)


PLAN_SYSTEM = (
    "You are AgentFirm's orchestrator. Split the user's objective into the FEWEST subtasks, each done by "
    "exactly one agent from the list. Use a single subtask when one agent can do everything. Give every "
    "subtask a self-contained objective that restates the details it needs (names, numbers, audience, "
    "constraints) from the user's objective. Route work straight to the specialist; don't use an intent whose job is "
    "routing to other agents. Later subtasks automatically receive the results of the "
    "subtasks they depend on, so say how to use them (e.g. 'using the research findings'). List in "
    "depends_on only subtasks whose results are needed; independent subtasks run in parallel. Never add "
    "an action the user did not ask for (publishing, sending, paying, deploying, buying). Pick an intent "
    "only when it clearly fits."
)
SYNTH_SYSTEM = (
    "You combine the results of several AgentFirm agents into one answer for the user. Use ONLY facts "
    "stated in the subtask results; attribute them to the agent. Never say an action happened (published, "
    "sent, deployed, paid) unless a result says so. Mention subtasks that failed, were skipped or need input."
)


# ── Planning (pure, unit-tested) ─────────────────────────────────────────────


@dataclass(frozen=True)
class Candidate:
    key: str
    name: str
    version_id: UUID
    version: str
    manifest: AgentManifest


def topo_order(subtasks: list[PlannedSubtask]) -> list[str] | None:
    """Kahn's algorithm; None if the dependencies contain a cycle."""
    deps = {s.key: set(s.depends_on) for s in subtasks}
    order: list[str] = []
    ready = [k for k, d in deps.items() if not d]
    while ready:
        k = ready.pop(0)
        order.append(k)
        for other, d in deps.items():
            if k in d:
                d.discard(k)
                if not d and other not in order and other not in ready:
                    ready.append(other)
    return order if len(order) == len(deps) else None


def validate_plan(plan: OrchestrationPlan, candidates: dict[str, Candidate], required: set[str]) -> list[str]:
    errors: list[str] = []
    keys = [s.key for s in plan.subtasks]
    if len(set(keys)) != len(keys):
        errors.append("subtask keys must be unique")
    for s in plan.subtasks:
        if not KEY.match(s.key):
            errors.append(f"'{s.key}': keys are 2-32 lowercase letters, digits or underscores")
        c = candidates.get(s.agent)
        if c is None:
            errors.append(f"{s.key}: agent '{s.agent}' is not available for this task (choose from {sorted(candidates)})")
            continue
        if s.intent and s.intent not in {i.key for i in c.manifest.intents}:
            errors.append(f"{s.key}: '{s.intent}' is not an intent of {s.agent}")
        for d in s.depends_on:
            if d == s.key:
                errors.append(f"{s.key}: a subtask can't depend on itself")
            elif d not in keys:
                errors.append(f"{s.key}: unknown dependency '{d}'")
    if missing := required - {s.agent for s in plan.subtasks}:
        errors.append(f"the plan must use every agent the user selected; missing: {', '.join(sorted(missing))}")
    if not errors and topo_order(plan.subtasks) is None:
        errors.append("dependencies contain a cycle")
    return errors


def allot(plan: OrchestrationPlan, candidates: dict[str, Candidate], total: int) -> dict[str, int] | None:
    """Split the task budget across subtasks (capped by each agent's own limit)."""
    available = total - RESERVE_CREDITS
    per = available // len(plan.subtasks) if plan.subtasks else 0
    out = {s.key: min(candidates[s.agent].manifest.limits.max_credits, per) for s in plan.subtasks}
    return out if all(v >= MIN_SUBTASK_CREDITS for v in out.values()) else None


def outcome(ex: TaskExecution) -> str:
    """completed | partial | needs_input | failed | cancelled | skipped (for a finished subtask)."""
    if ex.status == "completed":
        return str((ex.result or {}).get("status", "completed"))
    return ex.status


# ── Orchestrator profile (lets the orchestrator use the shared ExecutionContext) ──


@dataclass(frozen=True)
class _Models:
    capabilities: tuple[str, ...] = ("reasoning", "summarize")
    temperature: dict[str, float] = field(default_factory=lambda: {"reasoning": 0.1, "summarize": 0.2})
    max_output_tokens: int = 4000


@dataclass(frozen=True)
class OrchestratorProfile:
    """Duck-typed stand-in for an AgentManifest: the context only reads key, name and models."""

    key: str = "orchestrator"
    name: str = "Orchestrator"
    models: _Models = field(default_factory=_Models)


PROFILE = OrchestratorProfile()


class OrchestratorRun:
    """One worker's turn at an orchestrator execution. Re-entrant: each turn advances the graph
    as far as it can, then goes idle until a subtask finishes."""

    def __init__(self, *, execution_id: UUID, org_id: UUID, worker_id: str, gateway: ModelGateway) -> None:
        from .engine import _OrgSession

        self.execution_id, self.org_id, self.worker_id, self.gateway = execution_id, org_id, worker_id, gateway
        self._session = lambda: _OrgSession(org_id)
        self.ctx: ExecutionContext | None = None
        self.candidates: dict[str, Candidate] = {}
        self.total_budget = DEFAULT_TASK_CREDITS
        self._keys: dict[UUID, str] = {}  # subtask execution id → agent key

    # ── db helpers ───────────────────────────────────────────────────────────
    async def _set(self, **values: Any) -> None:
        async with self._session() as s:
            await s.execute(update(TaskExecution).where(TaskExecution.id == self.execution_id).values(**values))

    async def _check_control(self) -> None:
        lease = get_settings().worker_lease_seconds
        async with self._session() as s:
            row = (await s.execute(select(TaskExecution.status, TaskExecution.lease_owner).where(TaskExecution.id == self.execution_id))).one()
            if row.status in ("paused", "cancelled"):
                raise ExecutionHalted(row.status)
            if row.lease_owner != self.worker_id:
                raise ExecutionHalted("lease_lost")
            await s.execute(update(TaskExecution).where(TaskExecution.id == self.execution_id).values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease)))

    async def _children(self) -> list[TaskExecution]:
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(TaskExecution, Agent.key)
                    .join(AgentVersion, AgentVersion.id == TaskExecution.agent_version_id)
                    .join(Agent, Agent.id == AgentVersion.agent_id)
                    .where(TaskExecution.parent_execution_id == self.execution_id)
                    .order_by(TaskExecution.queued_at, TaskExecution.id)
                )
            ).all()
            out = []
            for r, key in rows:
                s.expunge(r)
                self._keys[r.id] = key
                out.append(r)
            return out

    async def _events(self, type_: str) -> list[dict[str, Any]]:
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(ExecutionEvent.payload).where(ExecutionEvent.execution_id == self.execution_id, ExecutionEvent.type == type_).order_by(ExecutionEvent.seq)
                )
            ).scalars()
            return [dict(r) for r in rows]

    async def _acked(self) -> set[str]:
        return {e["subtask_execution_id"] for e in await self._events("subtask.completed")}

    async def _load(self) -> tuple[TaskExecution, Task, frozenset[str]]:
        async with self._session() as s:
            ex = (await s.execute(select(TaskExecution).where(TaskExecution.id == self.execution_id))).scalar_one()
            task = (await s.execute(select(Task).where(Task.id == ex.task_id))).scalar_one()
            role = await s.scalar(select(Membership.role).where(Membership.org_id == self.org_id, Membership.user_id == task.created_by, Membership.status == "active"))
            s.expunge(ex)
            s.expunge(task)
        perms = frozenset(p.value for p in ROLE_PERMISSIONS[Role(role)]) if role else frozenset()
        if "tasks:create" not in perms:
            raise StepError(ErrorCode.PERMISSION_DENIED, "The requesting user can no longer run tasks in this workspace.")
        return ex, task, perms

    async def _load_candidates(self, perms: frozenset[str], selected: list[str]) -> None:
        """Agents this requester may run that accept orchestrated work (limited to the user's
        selection and to the agents the workspace's plan includes)."""
        from agentfirm.modules.billing import accounts

        async with self._session() as s:
            plan_agents = (await accounts.load(s, self.org_id)).plan.agents
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(Agent.key, Agent.name, AgentVersion.id, AgentVersion.version, AgentVersion.manifest)
                    .join(AgentVersion, (AgentVersion.agent_id == Agent.id) & AgentVersion.is_current.is_(True))
                    .where(Agent.is_enabled.is_(True))
                    .order_by(Agent.key)
                )
            ).all()
        for key, name, vid, ver, manifest in rows:
            if (selected and key not in selected) or (plan_agents is not None and key not in plan_agents):
                continue
            try:
                m = AgentManifest.model_validate(manifest)
            except ValidationError:
                continue  # pre-spec versions can't run (engine reports this for direct runs)
            if set(m.permissions) <= perms and "orchestrator" in m.collaboration.accepts_from:
                self.candidates[key] = Candidate(key=key, name=name, version_id=vid, version=ver, manifest=m)

    # ── main ─────────────────────────────────────────────────────────────────
    async def execute(self) -> str:
        sink: EventSink | None = None
        try:
            ex, task, perms = await self._load()
            sink = EventSink(org_id=self.org_id, task_id=task.id, execution_id=self.execution_id)
            params = dict(ex.parameters or {})
            selected = [str(a) for a in params.get("agents", [])]
            self.total_budget = int(ex.budget_credits or DEFAULT_TASK_CREDITS)
            self.ctx = ExecutionContext(
                org_id=self.org_id,
                task_id=task.id,
                execution_id=self.execution_id,
                requested_by=task.created_by,
                agent_version_id=None,  # type: ignore[arg-type]  # org / platform model routes
                manifest=PROFILE,  # type: ignore[arg-type]
                registry=registry(),
                permissions=perms,
                budget_credits=RESERVE_CREDITS,
                credits_used=ex.credits_used,
                gateway=self.gateway,
                sink=sink,
                objective=ex.objective or task.objective,
            )
            await self._check_control()
            await self._load_candidates(perms, selected)
            plans = [p for p in await self._events("plan.created") if p.get("kind") == "orchestration"]
            objective = ex.objective or task.objective
            if not plans and params.get("resume_from"):
                await self.ctx.emit("execution.status", {"status": "running", "reply": True})
                await self._set(status="running", stage="Continuing with your answer")
                resumed = await self._resume(UUID(str(params["resume_from"])), str(params.get("clarification", "")))
                planned = resumed if resumed is not None else await self._make_plan(objective, set(selected))
                if isinstance(planned, str):
                    return await self._finish_needs_input(planned)
            elif not plans:
                await self.ctx.emit("execution.status", {"status": "running"})
                await self._set(status="running", stage="Planning subtasks")
                planned = await self._make_plan(objective, set(selected))
                if isinstance(planned, str):
                    return await self._finish_needs_input(planned)
            else:
                planned = plans[-1]["subtasks"]
                await self.ctx.emit("execution.status", {"status": "running", "resumed": True})
                await self._set(status="running", stage="Coordinating subtasks")
            await self._ensure_spawned(planned)
            while True:
                await self._check_control()
                if await self._advance():
                    continue
                children = await self._children()
                if children and all(c.status in TERMINAL_STATUSES for c in children):
                    return await self._finish(await self._synthesise(objective, planned, children))
                if await self._idle():
                    return "waiting_subtasks"
        except ExecutionHalted as halt:
            await self._set(lease_owner=None, lease_expires_at=None)
            return halt.reason
        except StepError as exc:
            return await self._fail(exc, sink)

    # ── plan ─────────────────────────────────────────────────────────────────
    async def _make_plan(self, objective: str, required: set[str]) -> list[dict[str, Any]] | str:
        assert self.ctx
        if not self.candidates:
            raise StepError(ErrorCode.PERMISSION_DENIED, "None of the agents you can use accepts orchestrated work.")
        if unknown := required - set(self.candidates):
            raise StepError(ErrorCode.PERMISSION_DENIED, f"You can't run these agents: {', '.join(sorted(unknown))}.")
        agents = [
            {
                "key": c.key,
                "name": c.name,
                "description": c.manifest.description,
                "intents": [
                    {"key": i.key, "description": i.description, "workflow": i.workflow, "examples": i.examples, "counter_examples": i.counter_examples}
                    for i in c.manifest.intents
                ],
            }
            for c in self.candidates.values()
        ]
        catalogue = "\n".join(
            f"- {a['key']} ({a['name']}): {a['description']} Intents: " + "; ".join(f"{i['key']} — {i['description']}" for i in a["intents"]) for a in agents
        )
        feedback = ""
        plan: OrchestrationPlan | None = None
        errors: list[str] = []
        for _attempt in range(2):
            user = f"Agents:\n{catalogue}\n\n" + (f"The user selected these agents (use each): {', '.join(sorted(required))}\n\n" if required else "")
            user += f"User objective:\n{objective}" + (f"\n\nYour previous plan was invalid: {feedback}. Fix it." if feedback else "")
            try:
                plan = await self.ctx.structured(
                    "plan", "reasoning", OrchestrationPlan, system=PLAN_SYSTEM, user=user, sim={"objective": objective, "agents": agents, "required": sorted(required)}
                )
            except StepError as exc:
                if exc.code != ErrorCode.MODEL_ERROR:
                    raise
                errors = [exc.message]
                feedback = exc.message
                continue
            errors = validate_plan(plan, self.candidates, required)
            if not errors:
                break
            feedback = "; ".join(errors)
        if plan is None or errors:
            await self.ctx.log("warn", f"Planning failed: {'; '.join(errors)[:500]}")
            return "I couldn't turn this into a plan the agents can run. Could you say which agents should help, or split the request into steps?"
        budgets = allot(plan, self.candidates, self.total_budget)
        if budgets is None:
            return (
                f"A budget of {self.total_budget} credits is too small for {len(plan.subtasks)} subtasks "
                f"(each needs at least {MIN_SUBTASK_CREDITS}). Raise max_credits or narrow the request."
            )
        order = topo_order(plan.subtasks) or [s.key for s in plan.subtasks]
        by_key = {s.key: s for s in plan.subtasks}
        subtasks = []
        for k in order:
            s = by_key[k]
            c = self.candidates[s.agent]
            subtasks.append(
                {
                    "key": s.key,
                    "agent": s.agent,
                    "agent_version_id": str(c.version_id),
                    "agent_version": c.version,
                    "intent": s.intent,
                    "objective": s.objective,
                    "depends_on": s.depends_on,
                    "reason": s.reason,
                    "budget": budgets[s.key],
                }
            )
        await self.ctx.emit(
            "plan.created",
            {
                "kind": "orchestration",
                "rationale": plan.rationale,
                "workflow": "orchestration",
                "steps": [{"key": s["key"], "title": f"{self.candidates[s['agent']].name}: {s['objective'][:120]}", "weight": 1, "agent": s["agent"]} for s in subtasks],
                "subtasks": subtasks,
            },
        )
        return subtasks

    async def _resume(self, previous_id: UUID, clarification: str) -> list[dict[str, Any]] | None:
        """Continue after the user answered (ADR 0006): keep the previous plan, reuse every subtask
        that already finished (its result, never its actions) and re-run the rest; stuck subtasks get
        the answer added to their objective."""
        assert self.ctx
        async with self._session() as s:
            plan = (
                await s.execute(
                    select(ExecutionEvent.payload)
                    .where(ExecutionEvent.execution_id == previous_id, ExecutionEvent.type == "plan.created")
                    .order_by(ExecutionEvent.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            old = (await s.execute(select(TaskExecution).where(TaskExecution.parent_execution_id == previous_id))).scalars().all()
            if not plan or plan.get("kind") != "orchestration":
                return None  # it stopped before planning (e.g. asked which agents to use): plan afresh
            ex = (await s.execute(select(TaskExecution).where(TaskExecution.id == self.execution_id))).scalar_one()
            stuck = {o.subtask_key for o in old if outcome(o) == "needs_input"}
            reused = 0
            for o in old:
                if outcome(o) not in ("completed", "partial"):
                    continue
                s.add(
                    TaskExecution(
                        org_id=self.org_id,
                        task_id=ex.task_id,
                        parent_execution_id=self.execution_id,
                        agent_version_id=o.agent_version_id,
                        kind="agent",
                        subtask_key=o.subtask_key,
                        objective=o.objective,
                        parameters=o.parameters,
                        context=o.context,
                        depends_on=list(o.depends_on or []),
                        delegation_depth=o.delegation_depth,
                        origin=o.origin,
                        budget_credits=o.budget_credits,
                        status="completed",
                        progress=o.progress,
                        result=o.result,
                        stage="Reused from the previous attempt",
                        started_at=o.started_at,
                        finished_at=datetime.now(UTC),
                    )
                )
                reused += 1
        subtasks = []
        for p in plan["subtasks"]:
            if p["key"] in stuck and clarification:
                p = {**p, "objective": f"{p['objective']}\n\nThe user answered your question: {clarification}"}
            subtasks.append(p)
        await self.ctx.emit("plan.created", {**plan, "subtasks": subtasks, "resumed_from": str(previous_id), "reused": reused})
        await self.ctx.log("info", f"Continuing with the user's answer: {reused} finished subtask(s) reused, the rest run again.")
        return subtasks

    async def _ensure_spawned(self, planned: list[dict[str, Any]]) -> None:
        """Create the planned subtasks that don't exist yet (idempotent after a crash)."""
        assert self.ctx
        created: list[tuple[TaskExecution, dict[str, Any]]] = []
        async with self._session() as s:
            ex = (await s.execute(select(TaskExecution).where(TaskExecution.id == self.execution_id))).scalar_one()
            existing = set((await s.execute(select(TaskExecution.subtask_key).where(TaskExecution.parent_execution_id == self.execution_id))).scalars())
            for p in planned:
                if p["key"] in existing:
                    continue
                child = TaskExecution(
                    org_id=self.org_id,
                    task_id=ex.task_id,
                    parent_execution_id=self.execution_id,
                    agent_version_id=UUID(p["agent_version_id"]),
                    kind="agent",
                    subtask_key=p["key"],
                    objective=p["objective"],
                    parameters={"intent": p["intent"]} if p.get("intent") else {},
                    depends_on=list(p["depends_on"]),
                    delegation_depth=0,
                    origin="orchestrator",
                    budget_credits=p["budget"],
                    status="blocked" if p["depends_on"] else "queued",
                    stage=f"Waiting for {', '.join(p['depends_on'])}" if p["depends_on"] else "Queued",
                )
                s.add(child)
                created.append((child, p))
            await s.flush()
            ids = [(c.id, p) for c, p in created]
            total = len(existing) + len(created)
            await s.execute(update(TaskExecution).where(TaskExecution.id == self.execution_id).values(steps_total=total))
        for cid, p in ids:
            await self.ctx.emit(
                "subtask.spawned",
                {"subtask_execution_id": str(cid), "key": p["key"], "agent": p["agent"], "objective": p["objective"], "depends_on": p["depends_on"], "origin": "orchestrator", "depth": 0},
            )
        if ids:
            await wake_workers("subtasks queued")

    # ── coordination ─────────────────────────────────────────────────────────
    async def _advance(self) -> bool:
        """One pass: acknowledge finished subtasks (following their handoffs), then release or skip
        blocked ones. Returns True if anything changed."""
        assert self.ctx
        children = await self._children()
        acked = await self._acked()
        changed = False
        for c in children:
            if c.status in TERMINAL_STATUSES and str(c.id) not in acked:
                await self._follow_handoffs(c, children)
                await self.ctx.emit(
                    "subtask.completed",
                    {"subtask_execution_id": str(c.id), "key": c.subtask_key, "agent": self._agent_of(c), "status": c.status, "result_status": outcome(c)},
                )
                changed = True
        if changed:
            children = await self._children()
        by_key = {c.subtask_key: c for c in children}
        for c in children:
            if c.status != "blocked":
                continue
            deps = [by_key[d] for d in c.depends_on if d in by_key]
            if any(d.status not in TERMINAL_STATUSES for d in deps):
                continue
            bad = [d for d in deps if outcome(d) not in ("completed", "partial")]
            if bad:
                reason = "; ".join(f"{d.subtask_key} ({self._agent_of(d)}) {outcome(d).replace('_', ' ')}" for d in bad)
                await self._skip(c, f"Skipped because {reason}.")
            else:
                await self._release(c, deps)
            changed = True
        if changed:
            await self._record_progress()
        return changed

    def _agent_of(self, c: TaskExecution) -> str:
        return self._keys.get(c.id) or next((k for k, v in self.candidates.items() if v.version_id == c.agent_version_id), "agent")

    @staticmethod
    def _upstream(d: TaskExecution, agent: str) -> dict[str, Any]:
        r = d.result or {}
        return {
            "agent": agent,
            "subtask": d.subtask_key,
            "status": outcome(d),
            "summary": str(r.get("summary", ""))[:6000],
            "claims": [{"text": c.get("text"), "status": c.get("status")} for c in (r.get("claims") or [])[:20]],
            "artifacts": [{"id": a.get("id"), "name": a.get("name"), "kind": a.get("kind")} for a in (r.get("artifacts") or [])[:10]],
        }

    async def _release(self, c: TaskExecution, deps: list[TaskExecution]) -> None:
        assert self.ctx
        upstream = [self._upstream(d, self._agent_of(d)) for d in deps]
        async with self._session() as s:
            await s.execute(
                update(TaskExecution)
                .where(TaskExecution.id == c.id, TaskExecution.status == "blocked")
                .values(status="queued", stage="Queued", context={"upstream": upstream}, queued_at=func.now())
            )
        for d in deps:
            await self.ctx.emit(
                "handoff",
                {"kind": "result", "accepted": True, "from_agent": self._agent_of(d), "from_subtask": d.subtask_key, "to_agent": self._agent_of(c), "to_subtask": c.subtask_key},
            )
        await wake_workers("subtask released")

    async def _skip(self, c: TaskExecution, reason: str) -> None:
        result = AgentResult(execution_id=c.id, status="cancelled", summary=reason)
        async with self._session() as s:
            await s.execute(
                update(TaskExecution)
                .where(TaskExecution.id == c.id, TaskExecution.status == "blocked")
                .values(status="skipped", stage=reason[:240], finished_at=datetime.now(UTC), result=result.model_dump(mode="json"))
            )
        await EventSink(org_id=self.org_id, task_id=c.task_id, execution_id=c.id).emit("execution.status", {"status": "skipped", "reason": reason})

    async def _follow_handoffs(self, c: TaskExecution, children: list[TaskExecution]) -> None:
        """Turn a finished subtask's handoff requests into new subtasks when policy allows;
        otherwise record why not (they're then offered to the user as suggestions)."""
        assert self.ctx
        handoffs = (c.result or {}).get("handoffs") or []
        if not handoffs:
            return
        src_key = self._agent_of(c)
        src = self.candidates.get(src_key)
        for i, h in enumerate(handoffs):
            to = str(h.get("to_agent", ""))
            target = self.candidates.get(to)
            spent = sum(x.budget_credits or 0 for x in children)
            remaining = self.total_budget - RESERVE_CREDITS - spent
            depth = c.delegation_depth + 1
            reason = None
            if outcome(c) not in ("completed", "partial"):
                reason = f"{src_key} did not complete"
            elif src is None or to not in src.manifest.collaboration.can_delegate_to:
                reason = f"{src_key} may not delegate to {to}"
            elif target is None:
                reason = f"{to} isn't available for this task"
            elif src_key not in target.manifest.collaboration.accepts_from:
                reason = f"{to} doesn't accept work from {src_key}"
            elif to in (src_key, c.origin):
                reason = "it would create a delegation cycle"
            elif depth > min(MAX_DEPTH, src.manifest.limits.max_delegation_depth):
                reason = "delegation depth limit reached"
            elif len(children) >= MAX_SUBTASKS:
                reason = f"subtask limit ({MAX_SUBTASKS}) reached"
            elif remaining < MIN_SUBTASK_CREDITS:
                reason = "task budget exhausted"
            elif any(self._agent_of(x) == to and (x.objective or "").strip() == str(h.get("objective", "")).strip() for x in children):
                reason = "an identical subtask already exists"
            event = {"kind": "delegation", "from_agent": src_key, "from_subtask": c.subtask_key, "to_agent": to, "objective": str(h.get("objective", ""))[:500], "reason": h.get("reason", "")}
            if reason:
                await self.ctx.emit("handoff", {**event, "accepted": False, "declined_because": reason, "handoff": h})
                continue
            assert target is not None
            key = f"{c.subtask_key}_{to}_{i}"[:48]
            params = await self._handoff_params(target, h.get("parameters") or {})
            budget = min(target.manifest.limits.max_credits, remaining)
            async with self._session() as s:
                exists = await s.scalar(select(TaskExecution.id).where(TaskExecution.parent_execution_id == self.execution_id, TaskExecution.subtask_key == key))
                if exists is None:
                    child = TaskExecution(
                        org_id=self.org_id,
                        task_id=c.task_id,
                        parent_execution_id=self.execution_id,
                        agent_version_id=target.version_id,
                        kind="agent",
                        subtask_key=key,
                        objective=str(h.get("objective", ""))[:2000] or "Continue from the previous agent's result.",
                        parameters=params,
                        context={"upstream": [self._upstream(c, src_key)]},
                        depends_on=[c.subtask_key],
                        delegation_depth=depth,
                        origin=src_key,
                        budget_credits=budget,
                        status="queued",
                        stage=f"Handed off by {src.name if src else src_key}",
                    )
                    s.add(child)
                    await s.flush()
                    exists = child.id
                    await s.execute(update(TaskExecution).where(TaskExecution.id == self.execution_id).values(steps_total=len(children) + 1))
            self._keys[exists] = to
            children.append(TaskExecution(id=exists, agent_version_id=target.version_id, objective=str(h.get("objective", "")), budget_credits=budget, subtask_key=key))
            await self.ctx.emit("handoff", {**event, "accepted": True, "to_subtask": key})
            await self.ctx.emit(
                "subtask.spawned",
                {"subtask_execution_id": str(exists), "key": key, "agent": to, "objective": event["objective"], "depends_on": [c.subtask_key], "origin": src_key, "depth": depth},
            )
            await wake_workers("handoff")

    async def _handoff_params(self, target: Candidate, params: dict[str, Any]) -> dict[str, Any]:
        """Handoff parameters are checked against the target manifest; invalid ones are dropped."""
        from agentfirm.core.errors import Unprocessable
        from agentfirm.modules.tasks.service import _validate_parameters

        try:
            clean, _ = _validate_parameters(target.manifest.model_dump(mode="json"), {k: v for k, v in params.items() if k != "max_credits"})
            return clean
        except Unprocessable as exc:
            assert self.ctx
            await self.ctx.log("warn", f"Handoff parameters for {target.key} dropped: {exc}")
            return {}

    async def _record_progress(self) -> None:
        assert self.ctx
        children = await self._children()
        done = sum(1 for c in children if c.status in TERMINAL_STATUSES)
        total = len(children) or 1
        await self.ctx.emit("progress", {"completed_weight": done, "total_weight": total})
        await self._set(progress=Decimal(str(round(done / total, 4))), steps_completed=done, steps_total=len(children))

    async def _idle(self) -> bool:
        """Go idle unless something changed meanwhile. Children wake us under the same row lock."""
        assert self.ctx
        async with self._session() as s:
            status = await s.scalar(select(TaskExecution.status).where(TaskExecution.id == self.execution_id).with_for_update())
            if status in ("paused", "cancelled"):
                raise ExecutionHalted(str(status))
            rows = (await s.execute(select(TaskExecution).where(TaskExecution.parent_execution_id == self.execution_id))).scalars().all()
            acked = {
                e["subtask_execution_id"]
                for e in (await s.execute(select(ExecutionEvent.payload).where(ExecutionEvent.execution_id == self.execution_id, ExecutionEvent.type == "subtask.completed"))).scalars()
            }
            by_key = {r.subtask_key: r for r in rows}
            unacked = any(r.status in TERMINAL_STATUSES and str(r.id) not in acked for r in rows)
            releasable = any(r.status == "blocked" and all(by_key[d].status in TERMINAL_STATUSES for d in r.depends_on if d in by_key) for r in rows)
            if unacked or releasable:
                return False
            waiting = [r for r in rows if r.status not in TERMINAL_STATUSES]
            names = ", ".join(sorted({self._agent_of(r).capitalize() for r in waiting}))
            await s.execute(
                update(TaskExecution)
                .where(TaskExecution.id == self.execution_id)
                .values(status="waiting_subtasks", lease_owner=None, lease_expires_at=None, stage=f"Waiting for {names}"[:240])
            )
        await self.ctx.emit("execution.status", {"status": "waiting_subtasks"})
        return True

    # ── result ───────────────────────────────────────────────────────────────
    async def _synthesise(self, objective: str, planned: list[dict[str, Any]], children: list[TaskExecution]) -> AgentResult:
        assert self.ctx
        order = {p["key"]: n for n, p in enumerate(planned)}
        children = sorted(children, key=lambda c: (order.get(c.subtask_key or "", 100), c.queued_at or datetime.now(UTC)))
        results = [(c, self._agent_of(c), c.result or {}) for c in children]
        outcomes = [outcome(c) for c in children]

        claims: list[Claim] = []
        seen: set[str] = set()
        artifacts: list[ArtifactRef] = []
        questions: list[str] = []
        for c, agent, r in results:
            for cl in r.get("claims") or []:
                try:
                    claim = Claim.model_validate(cl)
                except ValidationError:
                    continue
                if claim.text not in seen:
                    seen.add(claim.text)
                    claims.append(claim)
            for a in r.get("artifacts") or []:
                try:
                    artifacts.append(ArtifactRef.model_validate(a))
                except ValidationError:
                    continue
            if outcome(c) == "needs_input":
                questions += [f"{agent.capitalize()}: {q}" for q in (r.get("questions") or [r.get("summary", "")])]

        declined = [e for e in await self._events("handoff") if e.get("kind") == "delegation" and not e.get("accepted")]
        suggestions: list[HandoffRequest] = []
        for e in declined:
            try:
                suggestions.append(HandoffRequest.model_validate({k: v for k, v in (e.get("handoff") or {}).items() if k in HandoffRequest.model_fields}))
            except ValidationError:
                continue

        async with self._session() as s:
            credits = int(
                await s.scalar(
                    select(func.coalesce(func.sum(TaskExecution.credits_used), 0)).where(
                        (TaskExecution.parent_execution_id == self.execution_id) | (TaskExecution.id == self.execution_id)
                    )
                )
                or 0
            )
        tool_calls = sum(int((r.get("usage") or {}).get("tool_calls", 0)) for _, _, r in results)
        usage = UsageSummary(credits=credits, tool_calls=tool_calls)
        quality = {"subtasks_completed": round(sum(o == "completed" for o in outcomes) / len(outcomes), 3)}

        if all(o == "completed" for o in outcomes):
            status = "completed"
        elif questions:
            status = "needs_input"
        elif all(o in ("failed", "cancelled", "skipped") for o in outcomes):
            status = "failed"
        else:
            status = "partial"

        if len(results) == 1:
            c, agent, r = results[0]
            summary = str(r.get("summary") or "")
            body = summary
        else:
            sections = []
            for n, (c, agent, r) in enumerate(results, 1):
                label = self.candidates[agent].name if agent in self.candidates else agent
                via = f" · handed off by {c.origin}" if c.origin and c.origin != "orchestrator" else ""
                sections.append(f"### {n}. {label} — {outcome(c).replace('_', ' ')}{via}\n\n{str(r.get('summary') or '').strip()}")
            overview = await self._overview(objective, results)
            body = f"{overview}\n\n## What each agent did\n\n" + "\n\n".join(sections)
        error = None
        if status == "failed":
            first = next((r.get("error") for _, _, r in results if r.get("error")), None) or {}
            error = AgentError(code=ErrorCode(first.get("code", "internal")), message=str(first.get("message", "All subtasks failed.")), retriable=bool(first.get("retriable", False)))
        return AgentResult(
            execution_id=self.execution_id,
            status=status,  # type: ignore[arg-type]
            summary=body,
            claims=claims,
            artifacts=artifacts,
            handoffs=suggestions,
            questions=questions if status == "needs_input" else [],
            usage=usage,
            quality=quality,
            error=error,
        )

    async def _overview(self, objective: str, results: list[tuple[TaskExecution, str, dict[str, Any]]]) -> str:
        assert self.ctx
        block = "\n\n".join(
            untrusted(f"agent:{agent}:{c.subtask_key}", f"Status: {outcome(c)}\n\n{str(r.get('summary') or '')[:5000]}", limit=6000) for c, agent, r in results
        )
        try:
            syn = await self.ctx.structured(
                "synthesize",
                "summarize",
                Synthesis,
                system=SYNTH_SYSTEM,
                user=f"User objective:\n{objective}\n\nSubtask results:\n{block}",
                sim={"objective": objective, "results": [{"agent": a, "key": c.subtask_key, "status": outcome(c), "summary": str(r.get("summary") or "")} for c, a, r in results]},
            )
        except StepError as exc:  # the combined result is still complete without an overview
            await self.ctx.log("warn", f"Overview unavailable ({exc.code.value}); showing each agent's result.")
            return "Here is what each agent produced."
        steps = "".join(f"\n- {s}" for s in syn.next_steps)
        return syn.overview.strip() + (f"\n\n**Suggested next steps**{steps}" if steps else "")

    async def _finish(self, result: AgentResult) -> str:
        assert self.ctx
        values: dict[str, Any] = {"progress": Decimal(1)} if result.status == "completed" else {}  # otherwise keep real progress
        await self._set(
            status="completed",
            finished_at=datetime.now(UTC),
            result=result.model_dump(mode="json"),
            lease_owner=None,
            lease_expires_at=None,
            **values,
            stage="Completed" if result.status == "completed" else f"Completed ({result.status.replace('_', ' ')})",
        )
        await self.ctx.emit("execution.status", {"status": "completed", "result_status": result.status})
        return "completed"

    async def _finish_needs_input(self, question: str) -> str:
        return await self._finish(AgentResult(execution_id=self.execution_id, status="needs_input", summary=question, questions=[question]))

    async def _fail(self, exc: StepError, sink: EventSink | None) -> str:
        err = {"code": exc.code.value, "message": exc.message[:1000], "retriable": exc.retriable}
        await self._set(
            status="failed",
            error=exc.message[:2000],
            finished_at=datetime.now(UTC),
            lease_owner=None,
            lease_expires_at=None,
            stage=f"Failed: {exc.message[:200]}",
            result={"status": "failed", "error": err},
        )
        if sink is not None:
            await sink.emit("execution.status", {"status": "failed", "error": err})
        return "failed"


# ── Simulator builders (AGENTFIRM_GATEWAY_MODE=simulated only) ───────────────
# A crude, deterministic stand-in for a planning model so the whole collaboration path can be
# exercised in CI and evals: split the objective into clauses, route each clause to the agent
# whose intent examples it resembles most, chain "then" clauses and run "also" clauses in parallel.

_CLAUSE = re.compile(r"(?:[.;]\s+|,?\s+(?=(?:then|also|after that|afterwards)\b))", re.IGNORECASE)
_AND = re.compile(r",?\s+and\s+(?=(?:then|also)\b)", re.IGNORECASE)
_PARALLEL = re.compile(r"^(?:and\s+)?(?:also|separately|in parallel|meanwhile)\b[,:]?\s*", re.IGNORECASE)
_SEQUENTIAL = re.compile(r"^(?:and\s+)?(?:then|after that|afterwards|next|finally)\b[,:]?\s*", re.IGNORECASE)


def _sim_stems(text: str) -> set[str]:
    from .gateway.simulated import STOP, tokens

    return {w[:5] for w in tokens(text) if w not in STOP}


#: Leading-verb hints (simulator only), like the Assistant's routing simulator.
_SIM_HINTS = [
    ("research", re.compile(r"^(research|find out|investigate|look into|compare|fact[- ]check|summari[sz]e)\b")),
    ("creative", re.compile(r"^(brainstorm|come up with|ideate|invent|name)\b")),
    ("marketing", re.compile(r"^(write|draft|publish|post|plan a campaign|create a campaign)\b.*\b(post|campaign|linkedin|instagram|newsletter|ad|ads)\b")),
    ("bi", re.compile(r"^(analy[sz]e|forecast|report on|build a (kpi|dashboard))\b")),
    ("engineer", re.compile(r"^(fix|deploy|refactor|review the code|implement|upgrade)\b")),
    ("assistant", re.compile(r"^(email|send|schedule|book|remind|draft an email|reply)\b")),
]


def _sim_route(clause: str, agents: list[dict[str, Any]]) -> tuple[str, str, float]:
    q = _sim_stems(clause)
    hinted = next((agent for agent, rx in _SIM_HINTS if rx.search(clause.lower())), None)

    def sim(e: str) -> float:  # cosine overlap of stem sets
        es = _sim_stems(e)
        return len(q & es) / (len(q) * len(es)) ** 0.5 if q and es else 0.0

    best = ("", "", 0.0)
    for a in agents:
        for i in a["intents"]:
            if i.get("workflow") == "delegate":
                continue  # the orchestrator is the router; specialists get the work directly
            pos = max((sim(e) for e in i["examples"]), default=0.0)
            neg = max((sim(e) for e in i.get("counter_examples", [])), default=0.0)
            score = pos - 0.5 * neg + (0.5 if a["key"] == hinted else 0.0)
            if score > best[2]:
                best = (a["key"], i["key"], score)
    return best


def _register_simulator() -> None:
    from .gateway.simulated import register

    @register("orchestrator.plan")
    def _plan(req: Any) -> dict[str, Any]:
        ctx = req.sim_context
        agents = ctx["agents"]
        required = set(ctx.get("required") or [])
        pool = [a for a in agents if not required or a["key"] in required]
        parts = [p.strip(" ,.") for p in _CLAUSE.split(_AND.sub(" ", ctx["objective"])) if p and p.strip(" ,.")]
        subtasks: list[dict[str, Any]] = []
        for part in parts:
            parallel = bool(_PARALLEL.match(part))
            text = _SEQUENTIAL.sub("", _PARALLEL.sub("", part)).strip()
            if not text:
                continue
            agent, _intent, score = _sim_route(text, pool)
            if not agent or score <= 0:
                if subtasks:  # no signal: it belongs to the previous clause
                    subtasks[-1]["objective"] += f". {text}"
                    continue
                agent = pool[0]["key"]
            if subtasks and subtasks[-1]["agent"] == agent and not parallel:
                subtasks[-1]["objective"] += f", then {text}"
                continue
            key = agent if all(s["key"] != agent for s in subtasks) else f"{agent}_{len(subtasks) + 1}"
            prev = [subtasks[-1]["key"]] if subtasks and not parallel else []
            subtasks.append({"key": key, "agent": agent, "intent": None, "objective": text[0].upper() + text[1:], "depends_on": prev, "reason": "simulated clause routing"})
        for a in sorted(required - {s["agent"] for s in subtasks}):
            subtasks.append({"key": a, "agent": a, "intent": None, "objective": ctx["objective"], "depends_on": [s["key"] for s in subtasks][-1:], "reason": "selected by the user"})
        return {"subtasks": subtasks[:MAX_PLANNED], "rationale": "simulated plan: one subtask per clause, chained unless marked 'also'"}

    @register("orchestrator.synthesize")
    def _synth(req: Any) -> dict[str, Any]:
        results = req.sim_context["results"]
        parts = [f"{r['agent'].capitalize()} {r['status'].replace('_', ' ')}" for r in results]
        return {"overview": f"(Simulated overview) {len(results)} agents worked on this: " + ", then ".join(parts) + ".", "next_steps": []}


_register_simulator()
