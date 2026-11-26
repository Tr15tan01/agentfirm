"""Task Manager: durable task + execution records, state machine, append-only events and
approvals. Workers (agentfirm.worker) claim queued executions and drive the same state
machine; this module never executes agents itself."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.db import DbContext, apply_context
from agentfirm.core.deps import Principal
from agentfirm.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from agentfirm.core.permissions import Perm
from agentfirm.modules.agents.models import Agent, AgentVersion
from agentfirm.modules.agents.service import current_version
from agentfirm.modules.audit.service import record
from agentfirm.modules.projects.service import get_project

from .models import TERMINAL_STATUSES, ApprovalRequest, Artifact, ExecutionEvent, Task, TaskExecution

log = logging.getLogger("agentfirm.tasks")

Action = Literal["pause", "resume", "cancel", "retry"]

#: Allowed transitions for user-initiated controls. Workers add queued→running etc. in Phase 4.
TRANSITIONS: dict[Action, tuple[set[str], str]] = {
    "pause": ({"queued", "running", "waiting_subtasks"}, "paused"),
    "resume": ({"paused"}, "queued"),
    "cancel": ({"queued", "running", "waiting_approval", "paused", "waiting_subtasks"}, "cancelled"),
    "retry": ({"failed", "cancelled"}, "queued"),
}


# ── Schemas ──────────────────────────────────────────────────────────────────


class TaskIn(BaseModel):
    objective: str = Field(min_length=3, max_length=8000)
    title: str | None = Field(default=None, max_length=240)
    agents: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="One agent = run it directly. Several = the orchestrator plans subtasks across them. Empty = the orchestrator chooses.",
    )
    project_id: UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict, description="Agent inputs declared in the manifest (e.g. depth, approach)")


class ExecutionOut(BaseModel):
    id: UUID
    kind: Literal["agent", "orchestrator"] = "agent"
    agent: str = Field(description="Agent key, or 'orchestrator'")
    agent_version: str
    status: str
    progress: float | None = Field(description="0-1 from plan steps; null when unknown")
    stage: str | None
    steps_completed: int
    steps_total: int | None
    parent_execution_id: UUID | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    credits_used: int = 0
    result: dict[str, Any] | None = Field(default=None, description="AgentResult once finished (summary, claims, artifacts, handoffs)")
    # Subtasks of an orchestrated task:
    subtask_key: str | None = None
    objective: str | None = Field(default=None, description="The subtask's own objective (null = the task's)")
    depends_on: list[str] = Field(default_factory=list)
    origin: str | None = Field(default=None, description="'orchestrator', or the agent whose handoff created this subtask")
    delegation_depth: int = 0


class TaskOut(BaseModel):
    id: UUID
    title: str
    objective: str
    project_id: UUID | None
    created_by: UUID
    created_at: datetime
    status: str
    executions: list[ExecutionOut]


class EventOut(BaseModel):
    id: int = Field(description="Global event id; SSE Last-Event-ID cursor")
    seq: int
    execution_id: UUID
    type: str
    payload: dict[str, Any]
    created_at: datetime


class ApprovalOut(BaseModel):
    id: UUID
    execution_id: UUID
    agent: str
    tool_key: str
    title: str
    reason: str
    preview: str | None
    side_effect: str
    status: str
    decided_by: UUID | None
    decided_at: datetime | None
    created_at: datetime


class ArtifactOut(BaseModel):
    id: UUID
    execution_id: UUID
    name: str
    kind: str
    size_bytes: int
    created_at: datetime


class TaskDetailOut(TaskOut):
    approvals: list[ApprovalOut]
    artifacts: list[ArtifactOut]


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _progress(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


async def append_event(session: AsyncSession, ex: TaskExecution, type_: str, payload: dict[str, Any]) -> ExecutionEvent:
    """Events are persisted first (source of truth), then fanned out over Redis/SSE (Phase 4)."""
    # Serialise event allocation per TASK (same lock as the runtime EventSink), so event ids
    # become visible in id order and the SSE cursor never skips an event.
    await session.execute(select(Task.id).where(Task.id == ex.task_id).with_for_update())
    seq = int(await session.scalar(select(func.coalesce(func.max(ExecutionEvent.seq), 0)).where(ExecutionEvent.execution_id == ex.id)) or 0) + 1
    ev = ExecutionEvent(org_id=ex.org_id, execution_id=ex.id, seq=seq, type=type_, payload=payload)
    session.add(ev)
    await session.flush()
    return ev


async def _executions(session: AsyncSession, principal: Principal, task_ids: list[UUID]) -> dict[UUID, list[ExecutionOut]]:
    if not task_ids:
        return {}
    rows = (
        await session.execute(
            select(TaskExecution, AgentVersion.version, Agent.key)
            .outerjoin(AgentVersion, AgentVersion.id == TaskExecution.agent_version_id)  # orchestrators have no agent version
            .outerjoin(Agent, Agent.id == AgentVersion.agent_id)
            .where(TaskExecution.task_id.in_(task_ids), TaskExecution.org_id == principal.org_id)
            # roots first; root and children share a timestamp when created together
            .order_by(TaskExecution.parent_execution_id.is_not(None), TaskExecution.queued_at, TaskExecution.id)
        )
    ).all()
    out: dict[UUID, list[ExecutionOut]] = {}
    for ex, ver, key in rows:
        out.setdefault(ex.task_id, []).append(
            ExecutionOut(
                id=ex.id,
                kind=ex.kind,  # type: ignore[arg-type]
                agent=key or "orchestrator",
                agent_version=ver or "—",
                status=ex.status,
                progress=_progress(ex.progress),
                stage=ex.stage,
                steps_completed=ex.steps_completed,
                steps_total=ex.steps_total,
                parent_execution_id=ex.parent_execution_id,
                queued_at=ex.queued_at,
                started_at=ex.started_at,
                finished_at=ex.finished_at,
                credits_used=ex.credits_used or 0,
                result=ex.result,
                subtask_key=ex.subtask_key,
                objective=ex.objective,
                depends_on=list(ex.depends_on or []),
                origin=ex.origin,
                delegation_depth=ex.delegation_depth or 0,
            )
        )
    return out


def _task_out(t: Task, execs: list[ExecutionOut]) -> TaskOut:
    roots = [e for e in execs if e.parent_execution_id is None] or execs
    root = max(roots, key=lambda e: e.queued_at) if roots else None
    status = root.status if root else "queued"
    if root is not None and root.kind == "orchestrator" and status in ("queued", "running", "waiting_subtasks"):
        # An orchestrated task needs approval whenever one of its subtasks does.
        children = [e for e in execs if e.parent_execution_id == root.id]
        status = "waiting_approval" if any(c.status == "waiting_approval" for c in children) else "running" if status == "waiting_subtasks" else status
    return TaskOut(
        id=t.id,
        title=t.title,
        objective=t.objective,
        project_id=t.project_id,
        created_by=t.created_by,
        created_at=t.created_at,
        status=status,
        executions=execs,
    )


async def _get_task(session: AsyncSession, principal: Principal, task_id: UUID) -> Task:
    t = (await session.execute(select(Task).where(Task.id == task_id, Task.org_id == principal.org_id))).scalar_one_or_none()
    if t is None:
        raise NotFound("Task not found.")
    return t


def _orchestration_budget(params: dict[str, Any]) -> int:
    """Orchestrated tasks accept only a task-wide credit budget; agent inputs need a single-agent task."""
    from agentfirm.runtime.orchestrator import DEFAULT_TASK_CREDITS, MAX_TASK_CREDITS

    extra = sorted(set(params) - {"max_credits"})
    if extra:
        raise Unprocessable(f"Agent parameters ({', '.join(extra)}) need a task for a single agent; multi-agent tasks accept only max_credits.")
    v = params.get("max_credits", DEFAULT_TASK_CREDITS)
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_TASK_CREDITS:
        raise Unprocessable(f"max_credits must be an integer between 1 and {MAX_TASK_CREDITS}.")
    return v


def _validate_parameters(manifest: dict[str, Any], params: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    """Check parameters against the manifest `inputs` (names, enums, basic types) and return
    them with the execution's credit budget (manifest limit, optionally lowered by `max_credits`)."""
    inputs = {i["name"]: i for i in manifest.get("inputs", [])}
    limit = (manifest.get("limits") or {}).get("max_credits")
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k == "max_credits":
            if not isinstance(v, int) or v < 1 or (limit and v > limit):
                raise Unprocessable(f"max_credits must be an integer between 1 and {limit}.")
            limit = v
            continue
        if k == "intent":
            if v not in {i["key"] for i in manifest.get("intents", [])}:
                raise Unprocessable(f"Unknown intent '{v}'.")
            out[k] = v
            continue
        spec = inputs.get(k)
        if spec is None:
            raise Unprocessable(f"Unknown parameter '{k}'.")
        if spec["type"] == "enum" and v not in (spec.get("enum") or []):
            raise Unprocessable(f"'{k}' must be one of {spec.get('enum')}.")
        if spec["type"] == "number" and not isinstance(v, int | float):
            raise Unprocessable(f"'{k}' must be a number.")
        if spec["type"] in ("list", "file") and not isinstance(v, list | str):
            raise Unprocessable(f"'{k}' must be a list.")
        if isinstance(v, str) and len(v) > 4000:
            raise Unprocessable(f"'{k}' is too long.")
        out[k] = v
    return out, limit


#: Who may decide an approval depends on the side effect (Agent Interface §8).
APPROVER: dict[str, Perm] = {
    "external": Perm.APPROVALS_DECIDE,
    "internal": Perm.APPROVALS_DECIDE,
    "financial": Perm.BILLING_MANAGE,
    "destructive": Perm.AGENTS_CONFIGURE,
}


# ── Commands & queries ───────────────────────────────────────────────────────


async def create_task(session: AsyncSession, principal: Principal, body: TaskIn, idempotency_key: str | None) -> tuple[TaskOut, bool]:
    """Returns (task, created). Re-sending the same Idempotency-Key returns the original task."""
    if idempotency_key:
        existing = (await session.execute(select(Task).where(Task.org_id == principal.org_id, Task.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing:
            return _task_out(existing, (await _executions(session, principal, [existing.id])).get(existing.id, [])), False

    if body.project_id:
        await get_project(session, principal, body.project_id)
    agent_keys = list(dict.fromkeys(body.agents))
    title = (body.title or body.objective.split("\n")[0])[:240]
    from agentfirm.modules.billing.accounts import check_can_start

    await check_can_start(session, principal.org_id, agent_keys)  # credits, plan agents, concurrency (server-side)
    if len(agent_keys) == 1:
        # One agent: run it directly (its parameters are validated against its manifest).
        _agent, version = await current_version(session, agent_keys[0])
        params, budget = _validate_parameters(version.manifest, body.parameters)
        task = Task(
            org_id=principal.org_id,
            title=title,
            objective=body.objective,
            project_id=body.project_id,
            created_by=principal.user_id,
            idempotency_key=idempotency_key,
            parameters=params,
        )
        session.add(task)
        await session.flush()
        root = TaskExecution(org_id=principal.org_id, task_id=task.id, agent_version_id=version.id, status="queued", stage="Queued", budget_credits=budget)
    else:
        # Several agents, or none: the orchestrator plans subtasks (ADR 0005). Selected agents must
        # exist and be usable by this member now; the orchestrator re-checks when it plans.
        for key in agent_keys:
            _agent, version = await current_version(session, key)
            needed = set((version.manifest or {}).get("permissions", []))
            if not needed <= {p.value for p in principal.permissions}:
                raise Forbidden(f"You don't have permission to use the {key} agent.")
        budget = _orchestration_budget(body.parameters)
        task = Task(
            org_id=principal.org_id,
            title=title,
            objective=body.objective,
            project_id=body.project_id,
            created_by=principal.user_id,
            idempotency_key=idempotency_key,
            parameters={},
        )
        session.add(task)
        await session.flush()
        root = TaskExecution(
            org_id=principal.org_id,
            task_id=task.id,
            agent_version_id=None,
            kind="orchestrator",
            parameters={"agents": agent_keys},
            status="queued",
            stage="Planning",
            budget_credits=budget,
        )
    session.add(root)
    await session.flush()
    await append_event(session, root, "execution.status", {"status": "queued", "agents": agent_keys})
    await record(session, action="task.created", target_type="task", target_id=task.id, actor=principal, after={"agents": agent_keys, "title": title})
    return _task_out(task, (await _executions(session, principal, [task.id]))[task.id]), True


async def get_task_record(session: AsyncSession, principal: Principal, task_id: UUID) -> Task:
    return await _get_task(session, principal, task_id)


async def list_tasks(session: AsyncSession, principal: Principal, *, status: str | None, limit: int) -> list[TaskOut]:
    tasks = list((await session.execute(select(Task).where(Task.org_id == principal.org_id).order_by(Task.created_at.desc()).limit(limit))).scalars())
    execs = await _executions(session, principal, [t.id for t in tasks])
    out = [_task_out(t, execs.get(t.id, [])) for t in tasks]
    return [t for t in out if status is None or t.status == status]


async def get_task(session: AsyncSession, principal: Principal, task_id: UUID) -> TaskDetailOut:
    t = await _get_task(session, principal, task_id)
    execs = (await _executions(session, principal, [t.id])).get(t.id, [])
    ex_ids = [e.id for e in execs]
    approvals = await _approvals(session, principal, execution_ids=ex_ids) if ex_ids else []
    arts = (
        list(
            (
                await session.execute(
                    select(Artifact).where(Artifact.execution_id.in_(ex_ids), Artifact.org_id == principal.org_id).order_by(Artifact.created_at)
                )
            ).scalars()
        )
        if ex_ids
        else []
    )
    base = _task_out(t, execs)
    return TaskDetailOut(
        **base.model_dump(),
        approvals=approvals,
        artifacts=[ArtifactOut(id=a.id, execution_id=a.execution_id, name=a.name, kind=a.kind, size_bytes=a.size_bytes, created_at=a.created_at) for a in arts],
    )


async def list_events(session: AsyncSession, principal: Principal, task_id: UUID, after_seq: int = 0) -> list[EventOut]:
    t = await _get_task(session, principal, task_id)
    rows = (
        await session.execute(
            select(ExecutionEvent)
            .join(TaskExecution, (TaskExecution.id == ExecutionEvent.execution_id) & (TaskExecution.org_id == ExecutionEvent.org_id))
            .where(TaskExecution.task_id == t.id, ExecutionEvent.org_id == principal.org_id, ExecutionEvent.seq > after_seq)
            .order_by(ExecutionEvent.created_at, ExecutionEvent.seq)
        )
    ).scalars()
    return [EventOut(id=e.id, seq=e.seq, execution_id=e.execution_id, type=e.type, payload=e.payload, created_at=e.created_at) for e in rows]


class ReplyIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


async def reply(session: AsyncSession, principal: Principal, task_id: UUID, body: ReplyIn) -> TaskOut:
    """Resume a task that stopped to ask the user something (result status needs_input).

    A new attempt starts with the answer added to its objective. An orchestrated task reuses the
    subtasks that already finished (their results, not their actions: nothing is re-published or
    re-sent) and runs only the ones that were stuck or skipped (ADR 0006)."""
    t = await _get_task(session, principal, task_id)
    root = (
        await session.execute(
            select(TaskExecution)
            .where(TaskExecution.task_id == t.id, TaskExecution.org_id == principal.org_id, TaskExecution.parent_execution_id.is_(None))
            .order_by(TaskExecution.queued_at.desc())
            .limit(1)
            .with_for_update(key_share=True)
        )
    ).scalar_one()
    result = root.result or {}
    if root.status != "completed" or result.get("status") != "needs_input":
        raise Conflict("This task isn't waiting for an answer.")
    from agentfirm.modules.billing.accounts import check_can_start

    keys = list((root.parameters or {}).get("agents", [])) if root.kind == "orchestrator" else []
    await check_can_start(session, principal.org_id, keys)
    questions = [str(q) for q in (result.get("questions") or [result.get("summary", "")]) if q]
    clarified = f"{root.objective or t.objective}\n\nYou asked:\n" + "\n".join(f"- {q}" for q in questions) + f"\n\nThe user answered:\n{body.message.strip()}"
    params = dict(root.parameters or {})
    if root.kind == "orchestrator":
        params |= {"resume_from": str(root.id), "clarification": body.message.strip()}
    new = TaskExecution(
        org_id=root.org_id,
        task_id=t.id,
        agent_version_id=root.agent_version_id,
        kind=root.kind,
        objective=clarified[:20000],
        parameters=params if root.kind == "orchestrator" else root.parameters,  # agent runs keep the task's parameters
        status="queued",
        stage="Queued (answer received)",
        budget_credits=root.budget_credits,
    )
    session.add(new)
    await session.flush()
    await append_event(session, new, "execution.status", {"status": "queued", "reply": True})
    await record(session, action="task.replied", target_type="task", target_id=t.id, actor=principal, after={"execution": str(new.id)})
    execs = await _executions(session, principal, [t.id])
    return _task_out(t, execs.get(t.id, []))


async def control(session: AsyncSession, principal: Principal, task_id: UUID, action: Action) -> TaskOut:
    t = await _get_task(session, principal, task_id)
    root = (
        await session.execute(
            select(TaskExecution)
            .where(TaskExecution.task_id == t.id, TaskExecution.org_id == principal.org_id, TaskExecution.parent_execution_id.is_(None))
            .order_by(TaskExecution.queued_at.desc())
            .limit(1)
            .with_for_update(key_share=True)  # FOR NO KEY UPDATE: doesn't block event inserts' FK checks
        )
    ).scalar_one()
    allowed, target = TRANSITIONS[action]
    if root.status not in allowed:
        raise Conflict(f"Cannot {action} an execution that is {root.status}.", code="invalid_transition")

    before = root.status
    if action == "retry":
        # A retry is a NEW execution (attempt) pinned to the same agent version; history is preserved.
        new = TaskExecution(
            org_id=root.org_id,
            task_id=t.id,
            agent_version_id=root.agent_version_id,
            kind=root.kind,
            parameters=root.parameters,
            status="queued",
            stage="Queued (retry)",
            budget_credits=root.budget_credits,
        )
        session.add(new)
        await session.flush()
        await append_event(session, new, "execution.status", {"status": "queued", "retry_of": str(root.id)})
    else:
        root.status = target
        children = list(
            (await session.execute(select(TaskExecution).where(TaskExecution.parent_execution_id == root.id, TaskExecution.org_id == root.org_id))).scalars()
        )
        if target == "cancelled":
            root.finished_at = _now()
            for c in children:
                if c.status not in TERMINAL_STATUSES:
                    c.status, c.finished_at, c.stage = "cancelled", _now(), "Cancelled"
        elif action == "pause":  # subtasks stop at their next step boundary
            for c in children:
                if c.status in ("queued", "running"):
                    c.status = "paused"
        elif action == "resume":
            for c in children:
                if c.status == "paused":
                    c.status = "queued"
        await append_event(session, root, "execution.status", {"status": target, "requested_by": str(principal.user_id), "action": action})
    await record(session, action=f"task.{action}", target_type="task", target_id=t.id, actor=principal, before={"status": before}, after={"status": target})
    await session.flush()
    return _task_out(t, (await _executions(session, principal, [t.id]))[t.id])


async def _approvals(session: AsyncSession, principal: Principal, *, execution_ids: list[UUID] | None = None, status: str | None = None) -> list[ApprovalOut]:
    q = select(ApprovalRequest, Agent.key).join(Agent, Agent.id == ApprovalRequest.agent_id).where(ApprovalRequest.org_id == principal.org_id)
    if execution_ids is not None:
        q = q.where(ApprovalRequest.execution_id.in_(execution_ids))
    if status:
        q = q.where(ApprovalRequest.status == status)
    rows = (await session.execute(q.order_by(ApprovalRequest.created_at.desc()))).all()
    return [
        ApprovalOut(
            id=a.id,
            execution_id=a.execution_id,
            agent=k,
            tool_key=a.tool_key,
            title=a.title,
            reason=a.reason,
            preview=a.preview,
            side_effect=a.side_effect,
            status=a.status,
            decided_by=a.decided_by,
            decided_at=a.decided_at,
            created_at=a.created_at,
        )
        for a, k in rows
    ]


async def list_approvals(session: AsyncSession, principal: Principal, status: str | None) -> list[ApprovalOut]:
    return await _approvals(session, principal, status=status)


async def decide(session: AsyncSession, principal: Principal, approval_id: UUID, body: DecisionIn) -> ApprovalOut:
    a = (
        await session.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id, ApprovalRequest.org_id == principal.org_id).with_for_update())
    ).scalar_one_or_none()
    if a is None:
        raise NotFound("Approval request not found.")
    if a.status != "pending":
        raise Conflict(f"Approval is already {a.status}.", code="already_decided")
    needed = APPROVER.get(a.side_effect, Perm.APPROVALS_DECIDE)
    if not principal.can(needed):
        raise Forbidden(f"Approving a {a.side_effect} action requires the {needed.value} permission.")
    # The approver authorises the action itself, so they must also hold each tool's permission.
    from agentfirm.agents.registry import registry

    tools = registry().tools
    for key in a.tool_key.split(","):
        spec = tools.get(key)
        if spec is not None and not principal.can(Perm(spec.required_permission)):
            raise Forbidden(f"Approving {key} requires the {spec.required_permission} permission.")
    a.status, a.decided_by, a.decided_at, a.note = body.decision, principal.user_id, _now(), body.note
    ex = (await session.execute(select(TaskExecution).where(TaskExecution.id == a.execution_id, TaskExecution.org_id == principal.org_id))).scalar_one()
    if ex.status == "waiting_approval":
        ex.status = "queued"  # the worker resumes (approved) or re-plans (rejected)
    await append_event(session, ex, "approval.resolved", {"approval_id": str(a.id), "decision": body.decision})
    await record(
        session,
        action=f"approval.{body.decision}",
        target_type="approval",
        target_id=a.id,
        actor=principal,
        after={"tool": a.tool_key, "side_effect": a.side_effect, "note": body.note},
    )
    await session.flush()
    return next(x for x in await _approvals(session, principal, execution_ids=[ex.id]) if x.id == a.id)


# ── Live stream (SSE) ────────────────────────────────────────────────────────

TERMINAL = {"completed", "failed", "cancelled"}
STREAM_MAX_SECONDS = 300  # ≤ access-token lifetime: clients reconnect (Last-Event-ID) and are re-authorised
HEARTBEAT_SECONDS = 15


async def event_stream(org_id: UUID, task_id: UUID, cursor: int, is_disconnected: Any) -> Any:
    """Yield SSE frames for a task: persisted events after `cursor`, then live ones.

    Postgres is the source of truth; Redis pub/sub only wakes the loop early. Each poll
    uses its own short transaction under the caller's org context (RLS applies)."""
    import asyncio
    import json
    import time

    from agentfirm.core.db import DbContext, apply_context, sessionmaker
    from agentfirm.runtime.events import redis_client, task_channel

    pubsub = None
    r = await redis_client()
    if r is not None:
        try:
            pubsub = r.pubsub()
            await pubsub.subscribe(task_channel(task_id))
        except Exception:
            pubsub = None
    started = last_beat = time.monotonic()
    sent_terminal = False  # a terminal execution.status event for the root has been delivered
    terminal_polls = 0
    yield "retry: 2000\n\n"
    try:
        while time.monotonic() - started < STREAM_MAX_SECONDS:
            if await is_disconnected():
                return
            async with sessionmaker()() as s, s.begin():
                await apply_context(s, DbContext(org_id=org_id))
                rows = (
                    (
                        await s.execute(
                            select(ExecutionEvent)
                            .join(TaskExecution, (TaskExecution.id == ExecutionEvent.execution_id) & (TaskExecution.org_id == ExecutionEvent.org_id))
                            .where(TaskExecution.task_id == task_id, ExecutionEvent.org_id == org_id, ExecutionEvent.id > cursor)
                            .order_by(ExecutionEvent.id)
                            .limit(500)
                        )
                    )
                    .scalars()
                    .all()
                )
                root_row = (
                    await s.execute(
                        select(TaskExecution.id, TaskExecution.status)
                        .where(TaskExecution.task_id == task_id, TaskExecution.org_id == org_id, TaskExecution.parent_execution_id.is_(None))
                        .order_by(TaskExecution.queued_at.desc())
                        .limit(1)
                    )
                ).one_or_none()
                root_id, latest = (root_row[0], root_row[1]) if root_row else (None, None)
            for e in rows:
                cursor = e.id
                # Only the root's terminal event ends the stream (subtasks finish before the task does).
                if e.type == "execution.status" and e.execution_id == root_id and (e.payload or {}).get("status") in TERMINAL:
                    sent_terminal = True
                body = EventOut(id=e.id, seq=e.seq, execution_id=e.execution_id, type=e.type, payload=e.payload, created_at=e.created_at)
                yield f"id: {e.id}\nevent: {e.type}\ndata: {json.dumps(body.model_dump(mode='json'))}\n\n"
            if rows:
                last_beat = time.monotonic()
                continue
            if latest in TERMINAL:
                # The status row commits a moment before the final event: end only once that event
                # was delivered (or after a short grace period for runs that end without one).
                terminal_polls += 1
                if sent_terminal or terminal_polls >= 3:
                    yield f"event: end\ndata: {json.dumps({'status': latest})}\n\n"
                    return
                await asyncio.sleep(0.3)
                continue
            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                last_beat = time.monotonic()
                yield ": ping\n\n"
            if pubsub is not None:
                try:
                    await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    continue
                except Exception:
                    pubsub = None
            await asyncio.sleep(1.0)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:  # noqa: S110 - advisory
                pass


# ── Stop / delete ────────────────────────────────────────────────────────────

ACTIVE_STATUSES = ("queued", "running", "waiting_approval", "paused", "waiting_subtasks")


class StopIn(BaseModel):
    #: Agent key to stop (e.g. "research"); omit to stop every agent.
    agent: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    #: Super-admin only: restrict to one workspace. Omit for the whole platform.
    org_id: UUID | None = None


class StopOut(BaseModel):
    executions_stopped: int
    tasks_affected: int


async def _cancel_executions(session: AsyncSession, rows: list[TaskExecution], *, actor: Principal, reason: str) -> int:
    """Marks executions cancelled and records why. The worker notices within about two seconds and
    interrupts the run, even in the middle of a model call. Caller must have the org context set."""
    now = _now()
    for ex in rows:
        ex.status, ex.finished_at, ex.stage, ex.lease_owner, ex.lease_expires_at = "cancelled", now, "Cancelled", None, None
        await append_event(session, ex, "execution.status", {"status": "cancelled", "requested_by": str(actor.user_id), "action": "stop", "reason": reason})
    if rows:
        await session.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.execution_id.in_([e.id for e in rows]), ApprovalRequest.status == "pending")
            .values(status="expired", note="Execution was stopped.")
        )
    await session.flush()
    return len(rows)


async def _active_executions(session: AsyncSession, *, org_id: UUID | None, agent: str | None) -> list[TaskExecution]:
    q = (
        select(TaskExecution)
        .outerjoin(AgentVersion, AgentVersion.id == TaskExecution.agent_version_id)
        .outerjoin(Agent, Agent.id == AgentVersion.agent_id)
        .where(TaskExecution.status.in_(ACTIVE_STATUSES))
        .order_by(TaskExecution.org_id, TaskExecution.queued_at)
        .with_for_update(of=TaskExecution, key_share=True)
    )
    if org_id is not None:
        q = q.where(TaskExecution.org_id == org_id)
    if agent is not None:
        q = q.where(Agent.key == agent)
    return list((await session.execute(q)).scalars())


async def stop_executions(session: AsyncSession, principal: Principal, body: StopIn, *, platform: bool) -> StopOut:
    """Stops running/queued/paused work: every agent or one agent, in this workspace (members) or
    across the platform / one workspace (super-admins)."""
    if platform:
        rows = await _active_executions(session, org_id=body.org_id, agent=body.agent)
    else:
        rows = await _active_executions(session, org_id=principal.org_id, agent=body.agent)
    if body.agent is not None and body.agent not in {a for (a,) in (await session.execute(select(Agent.key))).all()}:
        raise NotFound("Unknown agent.")
    reason = f"stop {body.agent or 'all agents'}"
    stopped, tasks = 0, set()
    by_org: dict[UUID, list[TaskExecution]] = {}
    for ex in rows:
        by_org.setdefault(ex.org_id, []).append(ex)
    for org_id, group in by_org.items():
        if platform:  # RLS WITH CHECK requires the write context to match the row's workspace
            await apply_context(session, DbContext(org_id=org_id, user_id=principal.user_id, platform_admin=True))
        stopped += await _cancel_executions(session, group, actor=principal, reason=reason)
        tasks.update(ex.task_id for ex in group)
    await record(
        session,
        action="platform.agents_stopped" if platform else "task.stop_all",
        target_type="agent" if body.agent else "platform",
        target_id=None,
        actor=principal,
        after={"agent": body.agent, "org_id": str(body.org_id) if body.org_id else None, "executions": stopped, "tasks": len(tasks)},
        platform=platform,
    )
    return StopOut(executions_stopped=stopped, tasks_affected=len(tasks))


async def delete_task(session: AsyncSession, principal: Principal, task_id: UUID) -> None:
    """Stops anything still running, then removes the task with its executions, events, approvals and
    artifacts (database rows cascade; stored artifact files are removed best-effort)."""
    from agentfirm.runtime.artifacts import get_store

    t = await _get_task(session, principal, task_id)
    live = list(
        (
            await session.execute(
                select(TaskExecution)
                .where(TaskExecution.task_id == t.id, TaskExecution.org_id == principal.org_id, TaskExecution.status.in_(ACTIVE_STATUSES))
                .with_for_update(key_share=True)
            )
        ).scalars()
    )
    await _cancel_executions(session, live, actor=principal, reason="task deleted")
    keys = list(
        (
            await session.execute(
                select(Artifact.storage_key).join(TaskExecution, TaskExecution.id == Artifact.execution_id).where(TaskExecution.task_id == t.id)
            )
        ).scalars()
    )
    await record(
        session, action="task.deleted", target_type="task", target_id=t.id, actor=principal, before={"title": t.title, "executions_stopped": len(live)}
    )
    await session.execute(delete(Task).where(Task.id == t.id, Task.org_id == principal.org_id))
    await session.flush()
    store = get_store()
    for key in keys:  # after the rows are gone; a leftover file is harmless, a dangling row is not
        try:
            await store.delete(key)
        except Exception:  # pragma: no cover - best effort
            log.warning("could not delete artifact file %s", key, exc_info=True)
