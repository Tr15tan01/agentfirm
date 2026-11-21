"""Event sink: persist first (Postgres is the source of truth), then publish a wake-up
on Redis so SSE streams deliver it immediately. Losing Redis only delays delivery."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from agentfirm.core.config import get_settings
from agentfirm.core.db import DbContext, apply_context, sessionmaker
from agentfirm.modules.tasks.models import ExecutionEvent, StepResult, Task

_redis = None


async def redis_client():  # type: ignore[no-untyped-def]
    global _redis
    url = get_settings().redis_url
    if not url:
        return None
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(url)
    return _redis


def task_channel(task_id: UUID) -> str:
    return f"af:task:{task_id}"


WAKE_STREAM = "af:wake"


async def wake_workers(reason: str) -> None:
    """Best-effort nudge; workers also poll the database, so correctness never depends on it."""
    r = await redis_client()
    if r is not None:
        try:
            await r.xadd(WAKE_STREAM, {"reason": reason}, maxlen=1000, approximate=True)
        except Exception:  # noqa: S110 - advisory
            pass


async def notify_task(task_id: UUID) -> None:
    """Nudge SSE streams of a task after an API-side event commits (advisory)."""
    r = await redis_client()
    if r is not None:
        try:
            await r.publish(task_channel(task_id), json.dumps({"id": None}))
        except Exception:  # noqa: S110 - advisory
            pass


class EventSink:
    def __init__(self, *, org_id: UUID, task_id: UUID, execution_id: UUID) -> None:
        self.org_id, self.task_id, self.execution_id = org_id, task_id, execution_id

    async def emit(self, type_: str, payload: dict[str, Any], *, step_output: tuple[str, dict[str, Any]] | None = None) -> int:
        """Persist an event. `step_output=(step, data)` is stored in the same transaction
        (used for step.completed, so completion and output are atomic)."""
        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(org_id=self.org_id))
            # Lock the TASK row: serialises every event of a task (all its executions), so event ids
            # become visible in id order per task and the SSE cursor (id > Last-Event-ID) never skips.
            await s.execute(select(Task.id).where(Task.id == self.task_id).with_for_update())
            seq = int(await s.scalar(select(func.coalesce(func.max(ExecutionEvent.seq), 0)).where(ExecutionEvent.execution_id == self.execution_id)) or 0) + 1
            ev = ExecutionEvent(org_id=self.org_id, execution_id=self.execution_id, seq=seq, type=type_, payload=payload)
            s.add(ev)
            if step_output is not None:
                s.add(StepResult(org_id=self.org_id, execution_id=self.execution_id, step=step_output[0], output=step_output[1]))
            await s.flush()
            event_id = ev.id
        r = await redis_client()
        if r is not None:
            try:
                await r.publish(task_channel(self.task_id), json.dumps({"id": event_id}))
            except Exception:  # noqa: S110 - advisory
                pass
        return event_id
