"""Agent Engine: runs one execution of a pinned agent version as a LangGraph graph.

* The graph is built from the manifest workflow (one node per step, parallel groups
  fan out/in) and checkpointed in Postgres (thread_id = execution id), so a crashed
  worker's run resumes from the last completed step.
* Approval steps call LangGraph `interrupt()`; the decision is read back from the
  approval_requests table when the execution is resumed.
* Progress = Σ weights of completed steps ÷ Σ weights, computed from persisted
  `step.completed` events — never estimated.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import operator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update

from agentfirm.agents.contracts import AgentManifest, AgentResult, ApprovalPolicy, ErrorCode, Workflow, WorkflowStep
from agentfirm.agents.registry import registry
from agentfirm.core.config import get_settings
from agentfirm.core.db import DbContext, apply_context, sessionmaker
from agentfirm.core.permissions import ROLE_PERMISSIONS, Role
from agentfirm.modules.agents.models import Agent, AgentVersion
from agentfirm.modules.identity.models import Membership
from agentfirm.modules.tasks.models import ApprovalRequest, ExecutionEvent, StepResult, Task, TaskExecution

from .context import ExecutionContext
from .errors import ExecutionHalted, StepError
from .events import EventSink, wake_workers
from .gateway.gateway import ModelGateway
from .programs import PROGRAMS
from .programs.base import AgentProgram


def merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {**a, **b}


class GraphState(TypedDict, total=False):
    data: Annotated[dict[str, Any], merge]
    completed: Annotated[list[str], operator.add]


class IntentChoice(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""


class _NeedsInput(Exception):
    def __init__(self, questions: list[str]) -> None:
        super().__init__(questions[0] if questions else "needs input")
        self.questions = questions


class _Partial(Exception):
    pass


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    """Step outputs are JSON (they already round-trip through the checkpointer)."""
    return json.loads(json.dumps(data, default=str))


def layers(workflow: Workflow) -> list[list[WorkflowStep]]:
    out: list[list[WorkflowStep]] = []
    for s in workflow.steps:
        if out and s.parallel_group and out[-1][0].parallel_group == s.parallel_group:
            out[-1].append(s)
        else:
            out.append([s])
    return out


class Run:
    """One worker's attempt at one execution."""

    def __init__(self, *, execution_id: UUID, org_id: UUID, worker_id: str, gateway: ModelGateway, checkpointer: AsyncPostgresSaver) -> None:
        self.execution_id, self.org_id, self.worker_id = execution_id, org_id, worker_id
        self.gateway, self.checkpointer = gateway, checkpointer
        self.ctx: ExecutionContext | None = None
        self.program: AgentProgram | None = None
        self.workflow: Workflow | None = None

    # ── database helpers ─────────────────────────────────────────────────────
    def _session(self):  # type: ignore[no-untyped-def]
        return _OrgSession(self.org_id)

    async def _set(self, **values: Any) -> None:
        async with self._session() as s:
            await s.execute(update(TaskExecution).where(TaskExecution.id == self.execution_id).values(**values))

    async def _set_terminal(self, **values: Any) -> None:
        """Final status update. For a subtask, the orchestrator is woken in the SAME transaction,
        under a lock on the orchestrator row: it either sees this result when it re-checks its
        subtasks, or it has already gone idle and is re-queued here. No lost wake-ups."""
        parent_id = None
        async with self._session() as s:
            parent_id = await s.scalar(select(TaskExecution.parent_execution_id).where(TaskExecution.id == self.execution_id))
            if parent_id is not None:
                await s.execute(select(TaskExecution.id).where(TaskExecution.id == parent_id).with_for_update())
            await s.execute(update(TaskExecution).where(TaskExecution.id == self.execution_id).values(**values))
            if parent_id is not None:
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == parent_id, TaskExecution.status == "waiting_subtasks")
                    .values(status="queued", stage="Coordinating subtasks")
                )
        if parent_id is not None:
            await wake_workers("subtask finished")

    async def check_control(self) -> None:
        """Cooperative pause/cancel + lease ownership + lease extension (heartbeat)."""
        lease = get_settings().worker_lease_seconds
        async with self._session() as s:
            row = (await s.execute(select(TaskExecution.status, TaskExecution.lease_owner).where(TaskExecution.id == self.execution_id))).one()
            if row.status in ("paused", "cancelled"):
                raise ExecutionHalted(row.status)
            if row.lease_owner != self.worker_id:
                raise ExecutionHalted("lease_lost")
            await s.execute(
                update(TaskExecution).where(TaskExecution.id == self.execution_id).values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease))
            )

    async def _completed_steps(self) -> set[str]:
        async with self._session() as s:
            rows = (
                await s.execute(select(ExecutionEvent.payload).where(ExecutionEvent.execution_id == self.execution_id, ExecutionEvent.type == "step.completed"))
            ).scalars()
            return {r["step"] for r in rows}

    async def _recorded_output(self, step: str) -> dict[str, Any] | None:
        async with self._session() as s:
            return await s.scalar(select(StepResult.output).where(StepResult.execution_id == self.execution_id, StepResult.step == step))

    async def _record_progress(self, step: WorkflowStep) -> None:
        assert self.ctx and self.workflow
        done = await self._completed_steps()
        total = sum(s.weight for s in self.workflow.steps)
        completed_weight = sum(s.weight for s in self.workflow.steps if s.key in done)
        await self.ctx.emit("progress", {"completed_weight": completed_weight, "total_weight": total})
        await self._set(progress=Decimal(str(round(completed_weight / total, 4))), steps_completed=len(done), stage=step.title[:240])

    # ── setup ────────────────────────────────────────────────────────────────
    async def _load(self) -> tuple[TaskExecution, Task, AgentManifest, frozenset[str]]:
        async with self._session() as s:
            ex = (await s.execute(select(TaskExecution).where(TaskExecution.id == self.execution_id))).scalar_one()
            task = (await s.execute(select(Task).where(Task.id == ex.task_id))).scalar_one()
            version = await s.get(AgentVersion, ex.agent_version_id)
            enabled = await s.scalar(select(Agent.is_enabled).where(Agent.id == version.agent_id)) if version else None
            m = (
                await s.execute(
                    select(Membership).where(Membership.org_id == self.org_id, Membership.user_id == task.created_by, Membership.status == "active")
                )
            ).scalar_one_or_none()
        try:
            manifest = AgentManifest.model_validate(version.manifest) if version else None
        except ValidationError as exc:
            raise StepError(
                ErrorCode.INTERNAL,
                f"Agent version {version.version if version else '?'} predates the executable manifest format — publish the specification manifest (python -m agentfirm.agents.publishing).",
            ) from exc
        if manifest is None:
            raise StepError(ErrorCode.INTERNAL, "Agent version not found")
        if enabled is False:
            raise StepError(ErrorCode.POLICY_VIOLATION, f"The {manifest.name} agent is turned off by the platform administrator.")
        perms = frozenset(p.value for p in ROLE_PERMISSIONS[Role(m.role)]) if m else frozenset()
        if not set(manifest.permissions) <= perms:
            raise StepError(ErrorCode.PERMISSION_DENIED, "The requesting user no longer has permission to run this agent.")
        return ex, task, manifest, perms

    async def _permissions_of(self, user_id: UUID | None) -> frozenset[str]:
        """Current permissions of a member of this organisation (empty if no longer a member)."""
        if user_id is None:
            return frozenset()
        async with self._session() as s:
            role = await s.scalar(select(Membership.role).where(Membership.org_id == self.org_id, Membership.user_id == user_id, Membership.status == "active"))
        return frozenset(p.value for p in ROLE_PERMISSIONS[Role(role)]) if role else frozenset()

    async def _approvals(self) -> tuple[set[str], dict[str, frozenset[str]]]:
        """Approved gated tools of this execution and, per tool, the approver's permissions:
        for an approval-gated action the approver's authority applies (ADR 0004)."""
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(ApprovalRequest.tool_key, ApprovalRequest.decided_by).where(
                        ApprovalRequest.execution_id == self.execution_id, ApprovalRequest.status == "approved"
                    )
                )
            ).all()
        approved: set[str] = set()
        authority: dict[str, frozenset[str]] = {}
        for key, decided_by in rows:
            tools = key.split(",")
            approved.update(tools)
            perms = await self._permissions_of(decided_by)
            authority.update(dict.fromkeys(tools, perms))
        return approved, authority

    async def _plan(self) -> str | None:
        async with self._session() as s:
            ev = (
                await s.execute(
                    select(ExecutionEvent.payload)
                    .where(ExecutionEvent.execution_id == self.execution_id, ExecutionEvent.type == "plan.created")
                    .order_by(ExecutionEvent.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return ev["workflow"] if ev else None

    async def _classify(self, manifest: AgentManifest) -> tuple[str, str, float]:
        assert self.ctx
        if (forced := self.ctx.parameters.get("intent")) and any(i.key == forced for i in manifest.intents):
            intent = next(i for i in manifest.intents if i.key == forced)
            return intent.key, intent.workflow, 1.0
        intents = [{"key": i.key, "description": i.description, "examples": i.examples, "counter_examples": i.counter_examples} for i in manifest.intents]
        self.ctx.enter_step("classify", frozenset())
        choice = await self.ctx.structured(
            "classify_intent",
            "classify",
            IntentChoice,
            system="Classify the user's request into exactly one of the agent's intents. Use the examples; counter-examples belong to other agents.",
            user=f"Intents: {intents}\n\nRequest: {self.ctx.objective}",
            sim={"objective": self.ctx.objective, "intents": intents},
        )
        intent = next((i for i in manifest.intents if i.key == choice.intent), manifest.intents[0])
        return intent.key, intent.workflow, choice.confidence

    # ── graph ────────────────────────────────────────────────────────────────
    def _node(self, step: WorkflowStep):  # type: ignore[no-untyped-def]
        async def node(state: GraphState) -> dict[str, Any]:
            assert self.ctx and self.program and self.workflow
            await self.check_control()
            self.ctx.enter_step(step.key, frozenset(step.tools))
            if (recorded := await self._recorded_output(step.key)) is not None:
                # Completed before a crash but after the last checkpoint: restore, don't re-run.
                await self.ctx.log("info", f"{step.key}: restored from durable step record (not re-run)")
                return {"data": recorded, "completed": [step.key]}
            await self.ctx.emit("step.started", {"step": step.key})
            rules = {r.error: r for r in self.ctx.manifest.recovery}
            attempt = 0
            while True:
                try:
                    if step.kind == "approval":
                        update_ = await self._approval(step, state.get("data", {}))
                    else:
                        update_ = await self.program.handlers[self.workflow.key][step.key](self.ctx, state.get("data", {}))
                    break
                except GraphInterrupt:
                    raise
                except StepError as exc:
                    rule = rules.get(exc.code)
                    max_attempts = rule.max_attempts if rule else (1 if exc.retriable else 0)
                    if exc.retriable and attempt < max_attempts and step.on_failure in ("retry", "fallback_model", "replan"):
                        attempt += 1
                        await self.ctx.log("warn", f"{step.key}: {exc.code.value} — retry {attempt}/{max_attempts}")
                        await asyncio.sleep(min(4.0, 0.25 * 2**attempt))
                        continue
                    err = {"code": exc.code.value, "message": exc.message[:500], "retriable": exc.retriable, "step": step.key}
                    await self.ctx.emit("step.failed", {"step": step.key, "error": err})
                    if step.on_failure == "skip" and exc.code not in (ErrorCode.BUDGET_EXCEEDED, ErrorCode.POLICY_VIOLATION):
                        skipped = {f"skipped:{step.key}": exc.message}
                        await self.ctx.sink.emit("step.completed", {"step": step.key, "skipped": True}, step_output=(step.key, skipped))
                        await self._record_progress(step)
                        return {"data": skipped, "completed": [step.key]}
                    if exc.code == ErrorCode.BUDGET_EXCEEDED:
                        raise _Partial(exc.message) from exc
                    if exc.code in (ErrorCode.APPROVAL_REJECTED, ErrorCode.APPROVAL_EXPIRED):
                        raise _NeedsInput([f"{exc.message}. Tell me what to change and I'll prepare a new version for approval."]) from exc
                    if step.on_failure == "ask_user" or exc.code in (ErrorCode.MISSING_CONTEXT, ErrorCode.UPSTREAM_DATA_INVALID):
                        raise _NeedsInput([exc.message]) from exc
                    raise
            output = update_ or {}
            await self.ctx.sink.emit("step.completed", {"step": step.key}, step_output=(step.key, _jsonable(output)))
            await self._record_progress(step)
            return {"data": output, "completed": [step.key]}

        return node

    async def _approval(self, step: WorkflowStep, data: dict[str, Any]) -> dict[str, Any]:
        assert self.ctx and self.program
        gated = [t for t in step.tools if self.ctx.registry.effective_approval(self.ctx.manifest.key, t) == ApprovalPolicy.REQUIRE]
        scope = getattr(self.program, "approval_scope", lambda *_: None)(self.ctx, step.key, data)
        if scope is not None:  # the program knows which action it prepared (e.g. a post, not a budget change)
            gated = [t for t in gated if t in scope]
        if not gated:
            # The user didn't ask for the gated action (e.g. "refactor" without "open a PR"):
            # nothing to approve, and the following tool step will not run it.
            return {f"approval:{step.key}": "not_requested"}
        tool_key = ",".join(gated)
        async with self._session() as s:
            req = (
                await s.execute(
                    select(ApprovalRequest)
                    .where(ApprovalRequest.execution_id == self.execution_id, ApprovalRequest.tool_key == tool_key)
                    .order_by(ApprovalRequest.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if req is None and len(gated) == 1:
            req = await self._standing_approval(step, gated[0], data)
        if req is None:
            spec = self.ctx.registry.tools[gated[0]]
            rule = next((r for r in self.ctx.manifest.approvals if gated[0] in r.tools), None)
            order = ["none", "internal", "external", "financial", "destructive"]
            side_effect = max((self.ctx.registry.tools[t].side_effect.value for t in gated), key=order.index)
            title, preview = step.title, self.program.approval_preview(self.ctx, step.key, data)
            if preview and any(k.startswith("fixture:") and v for k, v in data.items()):
                preview += "\n\n⚠ Prepared from FIXTURE data (test mode), not your real systems."
            async with self._session() as s:
                agent_id = await s.scalar(select(Agent.id).where(Agent.key == self.ctx.manifest.key))
                req = ApprovalRequest(
                    org_id=self.org_id,
                    execution_id=self.execution_id,
                    agent_id=agent_id,
                    tool_key=tool_key,
                    title=title,
                    reason=rule.description if rule else spec.description,
                    preview=preview,
                    side_effect=side_effect,
                )
                s.add(req)
                await s.flush()
                approval_id = req.id
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == self.execution_id)
                    .values(status="waiting_approval", stage=f"Awaiting approval: {title}"[:240])
                )
            await self.ctx.emit(
                "approval.requested", {"approval_id": str(approval_id), "tool": gated[0], "side_effect": side_effect, "title": title, "preview": preview}
            )
            await self.ctx.emit("execution.status", {"status": "waiting_approval"})
            interrupt({"approval_id": str(approval_id)})
            raise AssertionError("unreachable: interrupt() raises on first run")
        if req.status == "pending":
            interrupt({"approval_id": str(req.id)})
        if req.status == "approved":
            self.ctx.approved_tools.update(gated)
            perms = await self._permissions_of(req.decided_by)
            self.ctx.approver_permissions.update(dict.fromkeys(gated, perms))
            return {f"approval:{step.key}": "approved"}
        if req.status == "rejected" and step.on_failure in ("replan", "skip"):
            # Spec §7: rejected → replan. The gated action never runs; the program revises or reports.
            await self.ctx.log("info", f"{step.title}: rejected{f' — {req.note}' if req.note else ''}; the action will not run")
            return {f"approval:{step.key}": "rejected", f"approval_note:{step.key}": req.note or ""}
        code = ErrorCode.APPROVAL_REJECTED if req.status == "rejected" else ErrorCode.APPROVAL_EXPIRED
        raise StepError(code, f"Approval {req.status}: {req.note or req.title}")

    async def _standing_approval(self, step: WorkflowStep, tool: str, data: dict[str, Any]) -> ApprovalRequest | None:
        """A standing approval may cover this one action (ADR 0006): conditions are checked against
        the facts the program reports, the creator's current authority is re-checked, and the use
        is counted atomically. The approval is recorded and shown like any other."""
        from agentfirm.modules.governance import standing

        assert self.ctx and self.program
        facts = getattr(self.program, "approval_facts", lambda *_: {})(self.ctx, step.key, data) or {}
        async with self._session() as s:
            row = await standing.claim(s, org_id=self.org_id, tool=tool, agent=self.ctx.manifest.key, facts=facts, perms_of=self._permissions_of)
            if row is None:
                return None
            agent_id = await s.scalar(select(Agent.id).where(Agent.key == self.ctx.manifest.key))
            spec = self.ctx.registry.tools[tool]
            preview = self.program.approval_preview(self.ctx, step.key, data)
            req = ApprovalRequest(
                org_id=self.org_id,
                execution_id=self.execution_id,
                agent_id=agent_id,
                tool_key=tool,
                title=step.title,
                reason=spec.description,
                preview=preview,
                side_effect=spec.side_effect.value,
                status="approved",
                decided_by=row.created_by,
                decided_at=datetime.now(UTC),
                note=f"Standing approval: {row.note}",
                standing_approval_id=row.id,
            )
            s.add(req)
            await s.flush()
            s.expunge(req)
        await self.ctx.emit("approval.requested", {"approval_id": str(req.id), "tool": tool, "side_effect": req.side_effect, "title": req.title, "preview": preview})
        await self.ctx.emit("approval.resolved", {"approval_id": str(req.id), "decision": "approved", "standing_approval_id": str(row.id), "note": row.note, "facts": facts})
        await self.ctx.log("info", f"{step.title}: approved by a standing approval ({row.note}); use {row.uses + 1} of {row.max_uses}")
        return req

    def build(self, workflow: Workflow):  # type: ignore[no-untyped-def]
        g = StateGraph(GraphState)
        groups = layers(workflow)
        for s in workflow.steps:
            g.add_node(s.key, self._node(s))
        for s in groups[0]:
            g.add_edge(START, s.key)
        for a, b in itertools.pairwise(groups):
            for x in a:
                for y in b:
                    g.add_edge(x.key, y.key)
        for s in groups[-1]:
            g.add_edge(s.key, END)
        return g.compile(checkpointer=self.checkpointer)

    # ── main ─────────────────────────────────────────────────────────────────
    async def execute(self) -> str:
        """Run or resume. Returns the resulting execution status."""
        sink = None
        try:
            ex, task, manifest, perms = await self._load()
            sink = EventSink(org_id=self.org_id, task_id=task.id, execution_id=self.execution_id)
            program = PROGRAMS.get(manifest.key)
            if program is None:
                raise StepError(ErrorCode.INTERNAL, f"The {manifest.name} agent is specified but not implemented yet (Phase 4b).")
            self.program = program
            self.ctx = ExecutionContext(
                org_id=self.org_id,
                task_id=task.id,
                execution_id=self.execution_id,
                requested_by=task.created_by,
                agent_version_id=ex.agent_version_id,
                manifest=manifest,
                registry=registry(),
                permissions=perms,
                budget_credits=ex.budget_credits or manifest.limits.max_credits,
                credits_used=ex.credits_used,
                gateway=self.gateway,
                sink=sink,
                objective=ex.objective or task.objective,
                parameters=dict(ex.parameters if ex.parameters is not None else (task.parameters or {})),
                project_id=task.project_id,
                upstream=list((ex.context or {}).get("upstream", [])),
            )
            self.ctx.approved_tools, self.ctx.approver_permissions = await self._approvals()
            await self.check_control()
            config = {"configurable": {"thread_id": str(self.execution_id)}, "recursion_limit": manifest.limits.max_steps + 10}

            workflow_key = await self._plan()
            fresh = workflow_key is None
            if fresh:
                await self.ctx.emit("execution.status", {"status": "running"})
                intent, workflow_key, confidence = await self._classify(manifest)
                wf = manifest.workflow(workflow_key)
                min_conf = next(i.min_confidence for i in manifest.intents if i.key == intent)
                if confidence < min_conf:
                    return await self._finish_needs_input(
                        [f"I'm not sure what you need ({confidence:.0%} confident it's '{intent}'). Could you say more about the outcome you want?"]
                    )
                await self.ctx.emit(
                    "plan.created",
                    {
                        "intent": intent,
                        "confidence": confidence,
                        "workflow": wf.key,
                        "steps": [{"key": s.key, "title": s.title, "weight": s.weight, "agent": manifest.key} for s in wf.steps],
                    },
                )
                await self._set(steps_total=len(wf.steps), steps_completed=0, stage="Planned")
            self.workflow = manifest.workflow(workflow_key)  # type: ignore[arg-type]
            graph = self.build(self.workflow)
            snapshot = await graph.aget_state(config)
            if fresh or not snapshot.values:
                payload: Any = {"data": {"objective": self.ctx.objective}, "completed": []}
            elif snapshot.next and any(t.interrupts for t in snapshot.tasks):
                payload = Command(resume={"resumed_at": datetime.now(UTC).isoformat()})
            else:
                payload = None  # crash recovery: continue from the last checkpoint
            await self._set(status="running")
            if not fresh:  # resumed (after pause, approval or a crash): say so on the stream
                await self.ctx.emit("execution.status", {"status": "running", "resumed": True})
            result_state = await graph.ainvoke(payload, config, durability="sync")  # checkpoint before the next step starts
            after = await graph.aget_state(config)
            if after.next:
                await self._set(lease_owner=None, lease_expires_at=None)
                return "waiting_approval"
            data = result_state.get("data", {}) if isinstance(result_state, dict) else {}
            return await self._finish(program.finalize(self.ctx, data))
        except ExecutionHalted as halt:
            await self._set(lease_owner=None, lease_expires_at=None)
            return halt.reason
        except _NeedsInput as ni:
            return await self._finish_needs_input(ni.questions)
        except _Partial as p:
            assert self.ctx and self.program
            snap = await self.build(self.workflow).aget_state({"configurable": {"thread_id": str(self.execution_id)}}) if self.workflow else None  # type: ignore[arg-type]
            data = (snap.values.get("data", {}) if snap else {}) | {"_partial_reason": str(p)}
            return await self._finish(self.program.finalize(self.ctx, data).model_copy(update={"status": "partial"}))
        except StepError as exc:
            return await self._fail(exc, sink)

    async def _finish(self, result: AgentResult) -> str:
        assert self.ctx
        stored = result.model_dump(mode="json")
        values: dict[str, Any] = {"progress": Decimal(1)} if result.status == "completed" else {}  # partial keeps real progress
        await self._set_terminal(
            status="completed",
            finished_at=datetime.now(UTC),
            result=stored,
            lease_owner=None,
            lease_expires_at=None,
            stage="Completed" if result.status == "completed" else f"Completed ({result.status})",
            **values,
        )
        await self.ctx.emit("execution.status", {"status": "completed", "result_status": result.status})
        return "completed"

    async def _finish_needs_input(self, questions: list[str]) -> str:
        assert self.ctx
        result = AgentResult(execution_id=self.execution_id, status="needs_input", summary=questions[0], questions=questions)
        await self._set_terminal(
            status="completed",
            finished_at=datetime.now(UTC),
            result=result.model_dump(mode="json"),
            lease_owner=None,
            lease_expires_at=None,
            stage="Needs your input",
        )
        await self.ctx.emit("execution.status", {"status": "completed", "result_status": "needs_input"})
        return "completed"

    async def _fail(self, exc: StepError, sink: EventSink | None) -> str:
        err = {"code": exc.code.value, "message": exc.message[:1000], "retriable": exc.retriable}
        await self._set_terminal(
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


class _OrgSession:
    def __init__(self, org_id: UUID) -> None:
        self.org_id = org_id

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        self._cm = sessionmaker()()
        self.s = await self._cm.__aenter__()
        self._tx = self.s.begin()
        await self._tx.__aenter__()
        await apply_context(self.s, DbContext(org_id=self.org_id))
        return self.s

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        await self._tx.__aexit__(*exc)
        await self._cm.__aexit__(*exc)
