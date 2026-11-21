"""Plans, credit balances and plan limits (Phase 6, ADR 0006).

Credits come in two buckets:
* **plan** — the plan's monthly allowance; reset at each billing period, never rolled over.
* **purchased** — top-ups and administrator grants; kept until used.
Usage draws on the plan bucket first. Balances live in `credit_balances` (one row per
organisation, updated atomically with every model charge); every grant is also written to the
append-only `credit_ledger` with an idempotency reference.

Limits are enforced here, on the server: credits (before a task starts and before every model
call), concurrent tasks, seats and which agents a plan includes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.errors import PaymentRequired, TooManyRequests

from .models import CreditBalance, CreditLedgerEntry, Plan, Subscription

FREE = "free"
#: Subscription states in which the paid plan applies (past_due keeps access during dunning).
PAID_ACCESS = {"active", "trialing", "past_due"}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Account:
    subscription: Subscription
    plan: Plan  # the plan in effect (free when a paid plan is paused or canceled)
    balance: CreditBalance

    @property
    def available(self) -> int:
        return self.balance.plan_remaining + self.balance.purchased_remaining


async def ensure_account(session: AsyncSession, org_id: UUID) -> None:
    """Every organisation starts on the free plan with a full allowance (idempotent)."""
    free = await session.get(Plan, FREE)
    assert free is not None, "the free plan must exist (migration 0008)"
    now = _now()
    end = now + relativedelta(months=1)
    await session.execute(
        insert(Subscription).values(org_id=org_id, plan_key=FREE, status="active", provider="none", current_period_start=now, current_period_end=end).on_conflict_do_nothing()
    )
    await session.execute(
        insert(CreditBalance).values(org_id=org_id, plan_remaining=free.monthly_credits, purchased_remaining=0, period_start=now, period_end=end).on_conflict_do_nothing()
    )


async def load(session: AsyncSession, org_id: UUID, *, lock: bool = False) -> Account:
    await ensure_account(session, org_id)
    q = select(CreditBalance).where(CreditBalance.org_id == org_id)
    balance = (await session.execute(q.with_for_update() if lock else q)).scalar_one()
    sub = (await session.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one()
    plan = await effective_plan(session, sub)
    acc = Account(sub, plan, balance)
    if balance.period_end <= _now() and sub.provider != "paddle":
        # Paddle periods move on the provider's webhook; free and manual plans roll here.
        await roll_period(session, acc)
    return acc


async def effective_plan(session: AsyncSession, sub: Subscription) -> Plan:
    key = sub.plan_key if (sub.plan_key == FREE or sub.status in PAID_ACCESS) else FREE
    plan = await session.get(Plan, key)
    assert plan is not None
    return plan


async def roll_period(session: AsyncSession, acc: Account, *, start: datetime | None = None, end: datetime | None = None) -> bool:
    """Start a new allowance period. Explicit bounds come from the billing provider; otherwise
    monthly steps from the previous end until the period contains now. Idempotent per period."""
    b = acc.balance
    if start is None or end is None:
        start, end = b.period_start, b.period_end
        while end <= _now():
            start, end = end, end + relativedelta(months=1)
    ref = f"period:{b.org_id}:{start.isoformat()}"
    inserted = await _ledger(session, b.org_id, acc.plan.monthly_credits, "plan", "period_grant", ref, f"{acc.plan.name} allowance")
    if not inserted:
        return False
    await session.execute(
        update(CreditBalance).where(CreditBalance.org_id == b.org_id).values(plan_remaining=acc.plan.monthly_credits, period_start=start, period_end=end, updated_at=func.now())
    )
    if acc.subscription.provider != "paddle":
        await session.execute(update(Subscription).where(Subscription.org_id == b.org_id).values(current_period_start=start, current_period_end=end, updated_at=func.now()))
    await session.refresh(b)
    return True


async def _ledger(session: AsyncSession, org_id: UUID, delta: int, bucket: str, reason: str, reference: str | None, note: str | None, created_by: UUID | None = None) -> bool:
    stmt = insert(CreditLedgerEntry).values(org_id=org_id, delta=delta, bucket=bucket, reason=reason, reference=reference, note=note, created_by=created_by)
    if reference:
        stmt = stmt.on_conflict_do_nothing(index_elements=["reference"])
    res = await session.execute(stmt.returning(CreditLedgerEntry.id))
    return res.scalar_one_or_none() is not None


async def grant(
    session: AsyncSession, org_id: UUID, credits: int, *, reason: str, reference: str | None = None, note: str | None = None, created_by: UUID | None = None
) -> bool:
    """Add (or with admin_debit, remove) purchased credits. Returns False for a repeated reference."""
    await ensure_account(session, org_id)
    if not await _ledger(session, org_id, credits, "purchased", reason, reference, note, created_by):
        return False
    await session.execute(
        update(CreditBalance).where(CreditBalance.org_id == org_id).values(purchased_remaining=CreditBalance.purchased_remaining + credits, updated_at=func.now())
    )
    return True


async def charge(session: AsyncSession, org_id: UUID, credits: int) -> None:
    """Draw usage from the plan bucket first, then purchased credits. One statement, so
    concurrent charges can't both spend the same credit. The last call before running out
    may overdraw purchased credits slightly; the next check then stops further work."""
    await session.execute(
        text(
            "UPDATE credit_balances SET plan_remaining = greatest(plan_remaining - :c, 0), "
            "purchased_remaining = purchased_remaining - greatest(:c - plan_remaining, 0), updated_at = now() "
            "WHERE org_id = :org"
        ),
        {"c": credits, "org": org_id},
    )


async def available(session: AsyncSession, org_id: UUID) -> int:
    return (await load(session, org_id)).available


# ── limits ───────────────────────────────────────────────────────────────────


async def check_can_start(session: AsyncSession, org_id: UUID, agent_keys: list[str]) -> Account:
    from agentfirm.modules.tasks.models import TaskExecution

    acc = await load(session, org_id)
    if acc.available <= 0:
        raise PaymentRequired(
            f"Your workspace has used all its credits for this period (resets {acc.balance.period_end:%d %b %Y}). Buy credits or upgrade in Usage & Billing.",
            code="out_of_credits",
        )
    if acc.plan.agents is not None and (blocked := sorted(set(agent_keys) - set(acc.plan.agents))):
        raise PaymentRequired(f"The {acc.plan.name} plan doesn't include: {', '.join(blocked)}. Upgrade to use them.", code="plan_agent")
    active = await session.scalar(
        select(func.count())
        .select_from(TaskExecution)
        .where(TaskExecution.org_id == org_id, TaskExecution.parent_execution_id.is_(None), TaskExecution.status.in_(("queued", "running", "waiting_approval", "waiting_subtasks")))
    )
    if (active or 0) >= acc.plan.max_concurrent_tasks:
        raise TooManyRequests(
            f"The {acc.plan.name} plan runs up to {acc.plan.max_concurrent_tasks} tasks at a time. Wait for one to finish, or upgrade.", code="plan_concurrency"
        )
    return acc


async def check_seat(session: AsyncSession, org_id: UUID) -> None:
    from agentfirm.modules.identity.models import Membership

    acc = await load(session, org_id)
    seats = await session.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == org_id, Membership.status == "active"))
    if (seats or 0) >= acc.plan.max_seats:
        raise PaymentRequired(f"The {acc.plan.name} plan includes {acc.plan.max_seats} seats, and they're all in use. Upgrade to add members.", code="plan_seats")
