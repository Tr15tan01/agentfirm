from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.errors import NotFound
from agentfirm.core.permissions import Perm
from agentfirm.runtime.events import notify_task, wake_workers

from . import service
from .service import Action, ApprovalOut, DecisionIn, EventOut, TaskDetailOut, TaskIn, TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    session: DbSession,
    status_: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = require(Perm.TASKS_READ),
) -> list[TaskOut]:
    return await service.list_tasks(session, principal, status=status_, limit=limit)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED, responses={200: {"model": TaskOut, "description": "Idempotent replay"}})
async def create_task(
    body: TaskIn,
    response: Response,
    session: DbSession,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, max_length=128),
    principal: Principal = require(Perm.TASKS_CREATE),
) -> TaskOut:
    task, created = await service.create_task(session, principal, body, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    else:
        background.add_task(wake_workers, "task.created")  # runs after the transaction commits
    return task


@router.get("/{task_id}", response_model=TaskDetailOut)
async def get_task(task_id: UUID, session: DbSession, principal: Principal = require(Perm.TASKS_READ)) -> TaskDetailOut:
    return await service.get_task(session, principal, task_id)


@router.get("/{task_id}/events", response_model=list[EventOut])
async def list_events(
    task_id: UUID, session: DbSession, after: int = Query(default=0, ge=0), principal: Principal = require(Perm.TASKS_READ)
) -> list[EventOut]:
    """JSON replay of persisted events (`after` = per-execution seq). For live updates use /stream."""
    return await service.list_events(session, principal, task_id, after)


@router.get(
    "/{task_id}/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events; `id` = event id, resume with Last-Event-ID"}},
)
async def stream(
    task_id: UUID,
    request: Request,
    session: DbSession,
    last_event_id: str | None = Header(default=None, max_length=20),
    after_id: int = Query(default=0, ge=0, description="Event id cursor when Last-Event-ID can't be sent"),
    principal: Principal = require(Perm.TASKS_READ),
) -> StreamingResponse:
    """Live task events. Ends with `event: end` when the task is terminal, or after 5 minutes
    (the browser reconnects with Last-Event-ID and is re-authorised)."""
    await service.get_task_record(session, principal, task_id)  # 404 for other organisations' tasks
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after_id
    return StreamingResponse(
        service.event_stream(principal.org_id, task_id, cursor, request.is_disconnected),  # type: ignore[arg-type]
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/reply", response_model=TaskOut)
async def reply(
    task_id: UUID, body: service.ReplyIn, session: DbSession, background: BackgroundTasks, principal: Principal = require(Perm.TASKS_CREATE)
) -> TaskOut:
    """Answer the task's question(s): starts a new attempt that continues from where it stopped."""
    out = await service.reply(session, principal, task_id, body)
    background.add_task(notify_task, task_id)
    background.add_task(wake_workers, "task.reply")
    return out


@router.post("/stop", response_model=service.StopOut)
async def stop_all(body: service.StopIn, session: DbSession, principal: Principal = require(Perm.TASKS_CONTROL)) -> service.StopOut:
    """Stop every running/queued task in this workspace, or only one agent's (`{"agent": "research"}`)."""
    return await service.stop_executions(session, principal, body.model_copy(update={"org_id": None}), platform=False)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, session: DbSession, principal: Principal = require(Perm.TASKS_CONTROL)) -> None:
    """Stop and delete a task (and its history and files). Cannot be undone."""
    await service.delete_task(session, principal, task_id)


@router.post("/{task_id}/{action}", response_model=TaskOut)
async def control(
    task_id: UUID, action: Action, session: DbSession, background: BackgroundTasks, principal: Principal = require(Perm.TASKS_CONTROL)
) -> TaskOut:
    out = await service.control(session, principal, task_id, action)
    background.add_task(notify_task, task_id)
    if action in ("resume", "retry"):
        background.add_task(wake_workers, f"task.{action}")
    return out


@approvals_router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: DbSession, status_: str | None = Query(default=None, alias="status", max_length=16), principal: Principal = require(Perm.TASKS_READ)
) -> list[ApprovalOut]:
    return await service.list_approvals(session, principal, status_)


@approvals_router.post("/{approval_id}/decision", response_model=ApprovalOut)
async def decide(
    approval_id: UUID, body: DecisionIn, session: DbSession, background: BackgroundTasks, principal: Principal = require(Perm.APPROVALS_DECIDE)
) -> ApprovalOut:
    out = await service.decide(session, principal, approval_id, body)
    background.add_task(wake_workers, "approval.decided")
    return out


# ── artifacts (Phase 7: download, served safely) ─────────────────────────────

artifacts_router = APIRouter(prefix="/artifacts", tags=["tasks"])

#: Kinds shown inline in the browser; everything else downloads as an attachment.
INLINE = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg"}
TEXT = {
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "diff": "text/x-diff; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


@artifacts_router.get("/{artifact_id}", response_class=Response, responses={200: {"content": {"application/octet-stream": {}}}})
async def download_artifact(artifact_id: UUID, session: DbSession, principal: Principal = require(Perm.TASKS_READ)) -> Response:
    """Artifact content for members of its organisation (RLS + explicit org filter).

    Agent output is untrusted: it's served with `nosniff`, a sandboxing CSP (an SVG can't run
    script or load anything), and as an attachment unless it's an image."""
    from agentfirm.modules.tasks.models import Artifact
    from agentfirm.runtime.artifacts import get_store

    a = (await session.execute(select(Artifact).where(Artifact.id == artifact_id, Artifact.org_id == principal.org_id))).scalar_one_or_none()
    if a is None:
        raise NotFound("Artifact not found.")
    body = await get_store().get(a.storage_key)
    inline = a.kind in INLINE
    media = INLINE.get(a.kind) or TEXT.get(a.kind) or "application/octet-stream"
    safe = "".join(ch for ch in a.name if ch.isalnum() or ch in "._- ")[:120] or "artifact"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{safe}"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
