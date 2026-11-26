"""Agent worker: claims queued executions and runs them through the engine.

The database is authoritative. A worker claims an execution with a compare-and-swap
UPDATE on (lease_owner, lease_expires_at) and keeps the lease alive with a heartbeat.
If a worker dies, its lease expires and any other worker resumes the execution from the
last LangGraph checkpoint. Redis (`af:wake`) only shortens the wait between polls.

    python -m agentfirm.worker            # run forever
    python -m agentfirm.worker --once     # drain the queue and exit (CI / cron)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from prometheus_client import start_http_server
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select, text, update

from agentfirm.core.config import get_settings
from agentfirm.core.db import DbContext, apply_context, assert_safe_db_role, get_engine, sessionmaker
from agentfirm.core.observability import REGISTRY, RUNS, WORKER_HEARTBEAT, configure_logging
from agentfirm.modules.tasks.models import TaskExecution
from agentfirm.runtime.engine import Run
from agentfirm.runtime.events import WAKE_STREAM, redis_client
from agentfirm.runtime.gateway.gateway import ModelGateway
from agentfirm.runtime.orchestrator import OrchestratorRun

log = logging.getLogger("agentfirm.worker")
MAX_ATTEMPTS = 5


class Worker:
    def __init__(self, *, worker_id: str | None = None, concurrency: int | None = None) -> None:
        s = get_settings()
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:6]}"
        self.concurrency = concurrency or s.worker_concurrency
        self.lease = s.worker_lease_seconds
        self.poll = s.worker_poll_seconds
        self.halt_poll = max(0.5, min(self.poll, 2.0))
        self._sem = asyncio.Semaphore(self.concurrency)
        self._running: set[asyncio.Task[None]] = set()
        self._pool: AsyncConnectionPool | None = None
        self._http: httpx.AsyncClient | None = None
        self.checkpointer: AsyncPostgresSaver | None = None
        self.gateway: ModelGateway | None = None

    async def __aenter__(self) -> Worker:
        await assert_safe_db_role(get_engine())
        self._pool = AsyncConnectionPool(
            get_settings().psycopg_dsn,
            min_size=1,
            max_size=self.concurrency + 1,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await self._pool.open()
        self.checkpointer = AsyncPostgresSaver(self._pool)  # tables are created by Alembic 0005, not setup()
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
        self.gateway = ModelGateway(http=self._http)
        return self

    async def __aexit__(self, *exc: object) -> None:
        for t in list(self._running):
            t.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)
        if self._http:
            await self._http.aclose()
        if self._pool:
            await self._pool.close()

    # ── claiming ─────────────────────────────────────────────────────────────
    async def claim(self, limit: int) -> list[tuple[UUID, UUID]]:
        if limit <= 0:
            return []
        async with sessionmaker()() as s, s.begin():
            candidates = (await s.execute(text("SELECT id, org_id FROM claimable_executions(:n)"), {"n": limit * 2})).all()
        claimed: list[tuple[UUID, UUID]] = []
        for ex_id, org_id in candidates:
            if len(claimed) >= limit:
                break
            now = datetime.now(UTC)
            async with sessionmaker()() as s, s.begin():
                await apply_context(s, DbContext(org_id=org_id))
                row = (
                    await s.execute(
                        update(TaskExecution)
                        .where(
                            TaskExecution.id == ex_id,
                            TaskExecution.status.in_(("queued", "running")),
                            (TaskExecution.lease_expires_at.is_(None)) | (TaskExecution.lease_expires_at < now),
                        )
                        .values(lease_owner=self.id, lease_expires_at=now + timedelta(seconds=self.lease), attempts=TaskExecution.attempts + 1)
                        .returning(TaskExecution.attempts, TaskExecution.started_at)
                    )
                ).one_or_none()
                if row is None:
                    continue  # another worker won the race
                if row.started_at is None:
                    await s.execute(update(TaskExecution).where(TaskExecution.id == ex_id).values(started_at=now))
            if row.attempts > MAX_ATTEMPTS:
                await self._give_up(ex_id, org_id, row.attempts)
                continue
            claimed.append((ex_id, org_id))
        return claimed

    async def _give_up(self, ex_id: UUID, org_id: UUID, attempts: int) -> None:
        from agentfirm.runtime.events import EventSink

        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(org_id=org_id))
            ex = await s.get(TaskExecution, ex_id)
            assert ex is not None
            task_id = ex.task_id
            ex.status, ex.finished_at, ex.lease_owner, ex.lease_expires_at = "failed", datetime.now(UTC), None, None
            ex.error = f"Execution abandoned after {attempts - 1} worker attempts"
        await EventSink(org_id=org_id, task_id=task_id, execution_id=ex_id).emit(
            "execution.status", {"status": "failed", "error": {"code": "internal_error", "message": "Worker attempts exhausted", "retriable": False}}
        )

    # ── report schedules ────────────────────────────────────────────────────
    async def roll_credit_periods(self, limit: int = 50) -> int:
        """Start new monthly allowances for free and manual plans whose period ended
        (Paddle subscriptions move on the provider's webhooks instead)."""
        from agentfirm.modules.billing import accounts

        async with sessionmaker()() as s, s.begin():
            due = [r[0] for r in (await s.execute(text("SELECT org_id FROM due_credit_periods(:n)"), {"n": limit})).all()]
        for org_id in due:
            async with sessionmaker()() as s, s.begin():
                await apply_context(s, DbContext(org_id=org_id))
                await accounts.load(s, org_id, lock=True)  # rolls the period if it is due
        return len(due)

    async def run_due_schedules(self, limit: int = 20) -> int:
        """Turn due report schedules into tasks (as the member who created them, re-checked now).
        Idempotent per run: the task's Idempotency-Key is the schedule id + its due time."""
        from agentfirm.core.deps import Principal
        from agentfirm.core.permissions import ROLE_PERMISSIONS, Perm, Role
        from agentfirm.modules.identity.models import Membership, User
        from agentfirm.modules.integrations.models import ReportSchedule
        from agentfirm.modules.tasks import service as tasks
        from agentfirm.runtime.schedules import next_run

        async with sessionmaker()() as s, s.begin():
            due = (await s.execute(text("SELECT id, org_id FROM due_report_schedules(:n)"), {"n": limit})).all()
        created = 0
        for sid, org_id in due:
            async with sessionmaker()() as s, s.begin():
                await apply_context(s, DbContext(org_id=org_id))
                sched = (
                    await s.execute(
                        select(ReportSchedule)
                        .where(ReportSchedule.id == sid, ReportSchedule.active, ReportSchedule.next_run_at <= datetime.now(UTC))
                        .with_for_update(skip_locked=True)
                    )
                ).scalar_one_or_none()
                if sched is None:
                    continue
                row = (
                    await s.execute(
                        select(Membership, User)
                        .join(User, User.id == Membership.user_id)
                        .where(Membership.org_id == org_id, Membership.user_id == sched.created_by, Membership.status == "active")
                    )
                ).first()
                perms = frozenset(ROLE_PERMISSIONS[Role(row[0].role)]) if row else frozenset()
                if Perm.TASKS_CREATE not in perms:
                    sched.active = False  # creator left or lost permission: stop, don't run as someone else
                    log.info("schedule %s disabled: creator can no longer create tasks", sid)
                    continue
                principal = Principal(
                    user_id=row[1].id,
                    session_id=uuid4(),
                    email=row[1].email,
                    name=row[1].name,
                    is_super_admin=False,
                    org_id=org_id,
                    membership_id=row[0].id,
                    role=Role(row[0].role),
                    permissions=perms,
                )
                body = tasks.TaskIn(
                    objective=sched.objective, title=f"{sched.title} (scheduled)", agents=[sched.agent_key], parameters={**sched.parameters, "schedule": "off"}
                )
                due_at = sched.next_run_at
                await tasks.create_task(s, principal, body, idempotency_key=f"schedule:{sid}:{due_at.isoformat()}")
                sched.last_run_at, sched.next_run_at = due_at, next_run(sched.cadence, sched.timezone, max(due_at, datetime.now(UTC)))
                created += 1
        return created

    # ── running ──────────────────────────────────────────────────────────────
    async def _heartbeat(self, ex_id: UUID, org_id: UUID) -> None:
        while True:
            await asyncio.sleep(max(1.0, self.lease / 3))
            async with sessionmaker()() as s, s.begin():
                await apply_context(s, DbContext(org_id=org_id))
                await s.execute(
                    update(TaskExecution)
                    .where(TaskExecution.id == ex_id, TaskExecution.lease_owner == self.id)
                    .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=self.lease))
                )

    async def _watch_halt(self, ex_id: UUID, org_id: UUID, work: asyncio.Task[tuple[str, str]]) -> None:
        """Hard stop: when a user cancels (or deletes) the task, interrupt the run right away, even in the
        middle of a model call, instead of waiting for the next step boundary. Pause stays cooperative:
        a paused run resumes later from its checkpoint, so it is never cut off in the middle of a tool call."""
        while not work.done():
            await asyncio.sleep(self.halt_poll)
            try:
                async with sessionmaker()() as s, s.begin():
                    await apply_context(s, DbContext(org_id=org_id))
                    status = await s.scalar(select(TaskExecution.status).where(TaskExecution.id == ex_id))
            except Exception:  # a database blip must not kill a healthy run; the next poll retries
                log.warning("halt check for execution %s failed; retrying", ex_id, exc_info=True)
                continue
            if status is None or status == "cancelled":
                log.info("execution %s was %s; interrupting", ex_id, status or "deleted", extra={"execution_id": str(ex_id)})
                work.cancel()
                return

    async def _execute(self, ex_id: UUID, org_id: UUID) -> tuple[str, str]:
        """Returns (kind, final status)."""
        assert self.checkpointer and self.gateway
        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(org_id=org_id))
            kind = await s.scalar(select(TaskExecution.kind).where(TaskExecution.id == ex_id))
        if kind == "orchestrator":
            return kind, await OrchestratorRun(execution_id=ex_id, org_id=org_id, worker_id=self.id, gateway=self.gateway).execute()
        return kind or "agent", await Run(execution_id=ex_id, org_id=org_id, worker_id=self.id, gateway=self.gateway, checkpointer=self.checkpointer).execute()

    async def run_one(self, ex_id: UUID, org_id: UUID) -> str:
        assert self.checkpointer and self.gateway
        hb = asyncio.create_task(self._heartbeat(ex_id, org_id))
        work = asyncio.create_task(self._execute(ex_id, org_id))
        watch = asyncio.create_task(self._watch_halt(ex_id, org_id, work))
        try:
            try:
                kind, status = await work
            except asyncio.CancelledError:
                me = asyncio.current_task()
                if work.cancelled() and me is not None and me.cancelling() == 0:
                    RUNS.labels("agent", "halted").inc()
                    return "halted"  # interrupted on purpose by _watch_halt
                raise
            log.info("execution %s → %s", ex_id, status, extra={"execution_id": str(ex_id), "org_id": str(org_id), "event": "execution.turn"})
            RUNS.labels(kind, status).inc()
            return status
        except Exception:
            log.exception("execution %s crashed; lease will expire and another attempt will resume it", ex_id, extra={"execution_id": str(ex_id)})
            RUNS.labels("unknown", "crashed").inc()
            return "crashed"
        finally:
            for t in (hb, watch):
                t.cancel()
            for t in (hb, watch):
                with contextlib.suppress(asyncio.CancelledError):
                    await t

    def _spawn(self, ex_id: UUID, org_id: UUID) -> None:
        async def guarded() -> None:
            async with self._sem:
                await self.run_one(ex_id, org_id)

        t = asyncio.create_task(guarded())
        self._running.add(t)
        t.add_done_callback(self._running.discard)

    async def run_until_idle(self, max_rounds: int = 200) -> int:
        """Process executions until none are claimable (used by tests, evals and --once)."""
        done = 0
        await self.run_due_schedules()
        await self.roll_credit_periods()
        for _ in range(max_rounds):
            batch = await self.claim(self.concurrency)
            if not batch:
                return done
            results = await asyncio.gather(*(self.run_one(e, o) for e, o in batch))
            done += len(results)
        return done

    async def _wait_for_wake(self, last_id: str) -> str:
        try:
            r = await redis_client()
            if r is None:
                raise RuntimeError("redis not configured")
            res = await r.xread({WAKE_STREAM: last_id}, block=int(self.poll * 1000), count=10)
            return res[0][1][-1][0] if res else last_id
        except Exception:  # Redis is advisory; the DB poll keeps working without it
            await asyncio.sleep(self.poll)
            return last_id

    async def serve(self) -> None:
        log.info("worker %s started (concurrency %d)", self.id, self.concurrency)
        last = "$"
        while True:
            WORKER_HEARTBEAT.set_to_current_time()
            try:
                await self.run_due_schedules()
                await self.roll_credit_periods()
            except Exception:
                log.exception("running due report schedules failed; will retry")
            free = self.concurrency - len(self._running)
            for ex_id, org_id in await self.claim(free):
                self._spawn(ex_id, org_id)
            last = await self._wait_for_wake(last)


async def _main(once: bool) -> None:
    async with Worker() as w:
        if once:
            n = await w.run_until_idle()
            log.info("processed %d executions", n)
        else:
            await w.serve()


def main() -> None:
    ap = argparse.ArgumentParser(description="AgentFirm agent worker")
    ap.add_argument("--once", action="store_true", help="drain the queue and exit")
    args = ap.parse_args()
    s = get_settings()
    configure_logging(s.log_format, s.log_level)
    if s.worker_metrics_port:
        start_http_server(s.worker_metrics_port, registry=REGISTRY)  # private network only (see deploy/)
    asyncio.run(_main(args.once))


if __name__ == "__main__":
    main()
