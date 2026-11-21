"""Billing API service: account overview, checkout, plan changes, portal, invoices and the Paddle
webhook (the only thing that changes paid plans, invoices and purchased credits)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.config import get_settings
from agentfirm.core.db import DbContext, apply_context
from agentfirm.core.deps import Principal
from agentfirm.core.errors import Conflict, NotFound, Unprocessable
from agentfirm.modules.audit.service import record
from agentfirm.modules.identity.models import Membership, Organization

from . import accounts, paddle
from .models import BillingEvent, CreditBalance, CreditLedgerEntry, CreditPack, Invoice, Plan, Subscription

# ── schemas ──────────────────────────────────────────────────────────────────


class PlanOut(BaseModel):
    key: str
    name: str
    description: str
    monthly_credits: int
    max_seats: int
    max_concurrent_tasks: int
    agents: list[str] | None
    price_cents: int | None
    currency: str
    purchasable: bool = Field(description="Has a price and a Paddle price, and billing is enabled")


class PackOut(BaseModel):
    key: str
    name: str
    credits: int
    price_cents: int | None
    currency: str
    purchasable: bool


class Catalog(BaseModel):
    plans: list[PlanOut]
    credit_packs: list[PackOut]
    billing_enabled: bool
    provider_mode: Literal["live", "fixture", "disabled"]


class AccountOut(BaseModel):
    plan: PlanOut
    status: str
    provider: str
    cancel_at_period_end: bool
    period_start: datetime
    period_end: datetime
    credits_plan_remaining: int
    credits_plan_monthly: int
    credits_purchased: int
    credits_available: int
    seats_used: int
    seats_max: int
    tasks_active: int
    tasks_max: int
    can_manage: bool = Field(description="The caller may change the plan and buy credits (billing:manage)")
    portal_available: bool


class InvoiceOut(BaseModel):
    id: UUID
    number: str | None
    status: str
    kind: str
    total_cents: int
    currency: str
    description: str
    billed_at: datetime | None


class LedgerOut(BaseModel):
    id: int
    delta: int
    bucket: str
    reason: str
    note: str | None
    created_at: datetime


class CheckoutIn(BaseModel):
    plan: str | None = None
    credit_pack: str | None = None

    @model_validator(mode="after")
    def _one(self) -> CheckoutIn:
        if bool(self.plan) == bool(self.credit_pack):
            raise ValueError("Choose exactly one of plan or credit_pack.")
        return self


class CheckoutOut(BaseModel):
    checkout_url: str | None = Field(default=None, description="Open this to pay (new subscription or top-up)")
    changed: bool = Field(default=False, description="An existing subscription was switched to the new plan")
    transaction_id: str | None = None


class UrlOut(BaseModel):
    url: str


def _enabled() -> bool:
    return get_settings().paddle_mode != "disabled"


def plan_out(p: Plan) -> PlanOut:
    return PlanOut(
        key=p.key,
        name=p.name,
        description=p.description,
        monthly_credits=p.monthly_credits,
        max_seats=p.max_seats,
        max_concurrent_tasks=p.max_concurrent_tasks,
        agents=p.agents,
        price_cents=p.price_cents,
        currency=p.currency,
        purchasable=_enabled() and p.is_active and bool(p.price_cents) and bool(p.paddle_price_id),
    )


def pack_out(p: CreditPack) -> PackOut:
    return PackOut(key=p.key, name=p.name, credits=p.credits, price_cents=p.price_cents, currency=p.currency, purchasable=_enabled() and p.is_active and bool(p.price_cents) and bool(p.paddle_price_id))


# ── reads ────────────────────────────────────────────────────────────────────


async def catalog(session: AsyncSession) -> Catalog:
    plans = (await session.execute(select(Plan).where(Plan.is_public.is_(True), Plan.is_active.is_(True)).order_by(Plan.sort))).scalars()
    packs = (await session.execute(select(CreditPack).where(CreditPack.is_active.is_(True)).order_by(CreditPack.credits))).scalars()
    return Catalog(plans=[plan_out(p) for p in plans], credit_packs=[pack_out(p) for p in packs], billing_enabled=_enabled(), provider_mode=get_settings().paddle_mode)


async def account(session: AsyncSession, principal: Principal) -> AccountOut:
    from agentfirm.core.permissions import Perm
    from agentfirm.modules.tasks.models import TaskExecution

    assert principal.org_id
    acc = await accounts.load(session, principal.org_id)
    seats = await session.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == principal.org_id, Membership.status == "active"))
    active = await session.scalar(
        select(func.count())
        .select_from(TaskExecution)
        .where(TaskExecution.org_id == principal.org_id, TaskExecution.parent_execution_id.is_(None), TaskExecution.status.in_(("queued", "running", "waiting_approval", "waiting_subtasks")))
    )
    s, b = acc.subscription, acc.balance
    return AccountOut(
        plan=plan_out(acc.plan),
        status=s.status,
        provider=s.provider,
        cancel_at_period_end=s.cancel_at_period_end,
        period_start=b.period_start,
        period_end=b.period_end,
        credits_plan_remaining=b.plan_remaining,
        credits_plan_monthly=acc.plan.monthly_credits,
        credits_purchased=b.purchased_remaining,
        credits_available=acc.available,
        seats_used=seats or 0,
        seats_max=acc.plan.max_seats,
        tasks_active=active or 0,
        tasks_max=acc.plan.max_concurrent_tasks,
        can_manage=principal.can(Perm.BILLING_MANAGE),
        portal_available=_enabled() and bool(s.provider_customer_id),
    )


async def invoices(session: AsyncSession, principal: Principal) -> list[InvoiceOut]:
    rows = (await session.execute(select(Invoice).where(Invoice.org_id == principal.org_id).order_by(Invoice.billed_at.desc().nulls_last()).limit(100))).scalars()
    return [InvoiceOut(id=i.id, number=i.number, status=i.status, kind=i.kind, total_cents=i.total_cents, currency=i.currency, description=i.description, billed_at=i.billed_at) for i in rows]


async def ledger(session: AsyncSession, principal: Principal) -> list[LedgerOut]:
    rows = (await session.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.org_id == principal.org_id).order_by(CreditLedgerEntry.id.desc()).limit(100))).scalars()
    return [LedgerOut(id=r.id, delta=r.delta, bucket=r.bucket, reason=r.reason, note=r.note, created_at=r.created_at) for r in rows]


async def invoice_pdf(session: AsyncSession, principal: Principal, invoice_id: UUID) -> UrlOut:
    inv = (await session.execute(select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == principal.org_id))).scalar_one_or_none()
    if inv is None:
        raise NotFound("Invoice not found.")
    try:
        return UrlOut(url=await paddle.client().invoice_url(inv.provider_transaction_id))
    except paddle.PaddleError as exc:
        raise Unprocessable(str(exc)) from exc


# ── changes (billing:manage) ─────────────────────────────────────────────────


async def _customer(session: AsyncSession, principal: Principal, sub: Subscription) -> str:
    if sub.provider_customer_id:
        return sub.provider_customer_id
    org = await session.get(Organization, principal.org_id)
    cid = await paddle.client().create_customer(principal.email, org.name if org else principal.name)
    sub.provider_customer_id = cid
    await session.flush()
    return cid


async def checkout(session: AsyncSession, principal: Principal, body: CheckoutIn) -> CheckoutOut:
    assert principal.org_id
    acc = await accounts.load(session, principal.org_id)
    sub = acc.subscription
    try:
        if body.plan:
            plan = await session.get(Plan, body.plan)
            if plan is None or not plan.is_active:
                raise NotFound("Plan not found.")
            if not plan_out(plan).purchasable or not plan.paddle_price_id:
                raise Unprocessable(f"The {plan.name} plan isn't available for purchase yet.")
            if sub.provider == "paddle" and sub.provider_subscription_id and sub.status in accounts.PAID_ACCESS:
                if sub.plan_key == plan.key:
                    raise Conflict(f"You're already on the {plan.name} plan.")
                # Existing subscription: switch price (prorated now). Paddle's webhook applies it.
                await paddle.client().change_subscription_price(sub.provider_subscription_id, plan.paddle_price_id)
                await record(session, action="billing.plan_change_requested", target_type="organization", target_id=principal.org_id, actor=principal, before={"plan": sub.plan_key}, after={"plan": plan.key})
                return CheckoutOut(changed=True)
            if sub.provider == "manual":
                raise Conflict("Your plan is managed by AgentFirm support. Contact them to change it.")
            price, custom = plan.paddle_price_id, {"org_id": str(principal.org_id), "kind": "subscription", "key": plan.key}
        else:
            pack = await session.get(CreditPack, body.credit_pack)
            if pack is None or not pack.is_active:
                raise NotFound("Credit pack not found.")
            if not pack_out(pack).purchasable or not pack.paddle_price_id:
                raise Unprocessable(f"{pack.name} isn't available for purchase yet.")
            price, custom = pack.paddle_price_id, {"org_id": str(principal.org_id), "kind": "credit_pack", "key": pack.key}
        cid = await _customer(session, principal, sub)
        co = await paddle.client().create_transaction(price, cid, custom)
    except paddle.PaddleError as exc:
        raise Unprocessable(str(exc)) from exc
    await record(session, action="billing.checkout_started", target_type="organization", target_id=principal.org_id, actor=principal, after={**custom, "transaction": co.transaction_id})
    return CheckoutOut(checkout_url=co.url, transaction_id=co.transaction_id)


async def portal(session: AsyncSession, principal: Principal) -> UrlOut:
    acc = await accounts.load(session, principal.org_id)  # type: ignore[arg-type]
    s = acc.subscription
    if not s.provider_customer_id:
        raise Unprocessable("There's no billing account yet. It's created with your first purchase.")
    try:
        return UrlOut(url=await paddle.client().portal_url(s.provider_customer_id, [s.provider_subscription_id] if s.provider_subscription_id else []))
    except paddle.PaddleError as exc:
        raise Unprocessable(str(exc)) from exc


async def cancel(session: AsyncSession, principal: Principal) -> AccountOut:
    acc = await accounts.load(session, principal.org_id)  # type: ignore[arg-type]
    s = acc.subscription
    if s.provider != "paddle" or not s.provider_subscription_id or s.status not in accounts.PAID_ACCESS:
        raise Conflict("There's no paid subscription to cancel.")
    try:
        await paddle.client().cancel_subscription(s.provider_subscription_id)
    except paddle.PaddleError as exc:
        raise Unprocessable(str(exc)) from exc
    s.cancel_at_period_end = True  # Paddle confirms with subscription.updated (scheduled_change)
    await record(session, action="billing.cancel_requested", target_type="organization", target_id=principal.org_id, actor=principal, after={"plan": s.plan_key})
    return await account(session, principal)


# ── webhooks ─────────────────────────────────────────────────────────────────

SUBSCRIPTION_EVENTS = {
    "subscription.created",
    "subscription.updated",
    "subscription.activated",
    "subscription.trialing",
    "subscription.past_due",
    "subscription.paused",
    "subscription.resumed",
    "subscription.canceled",
}


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


async def apply_event(session: AsyncSession, event: dict[str, Any]) -> str:
    """Store a verified event once and apply it. Returns processed | duplicate | ignored | error."""
    eid, etype, data = str(event.get("event_id") or ""), str(event.get("event_type") or ""), event.get("data") or {}
    if not eid or not etype:
        raise Unprocessable("Not a Paddle event.")
    if await session.get(BillingEvent, eid) is not None:
        return "duplicate"
    org_id = paddle.org_from(data)
    ev = BillingEvent(id=eid, provider="paddle", type=etype, subject_org_id=org_id, payload=event, occurred_at=_dt(event.get("occurred_at")))
    session.add(ev)
    await session.flush()
    if etype not in SUBSCRIPTION_EVENTS and etype != "transaction.completed":
        ev.processed_at = datetime.now(UTC)
        return "ignored"
    try:
        if org_id is None:
            raise ValueError("custom_data.org_id is missing")
        await apply_context(session, DbContext(org_id=org_id))  # RLS: this organisation only, from here on
        if await session.scalar(select(Organization.id).where(Organization.id == org_id)) is None:
            raise ValueError("custom_data.org_id is unknown")
        async with session.begin_nested():
            if etype in SUBSCRIPTION_EVENTS:
                await _subscription(session, org_id, eid, data)
            else:
                await _transaction(session, org_id, data)
        ev.processed_at = datetime.now(UTC)
        return "processed"
    except ValueError as exc:  # permanent: recorded for super-admins, acknowledged so Paddle stops retrying
        ev.error = str(exc)[:1000]
        return "error"


async def _subscription(session: AsyncSession, org_id: UUID, event_id: str, d: dict[str, Any]) -> None:
    price = ((d.get("items") or [{}])[0].get("price") or {}).get("id")
    plan = (await session.execute(select(Plan).where(Plan.paddle_price_id == price))).scalar_one_or_none() if price else None
    if plan is None:
        raise ValueError(f"no plan has Paddle price {price!r}")
    acc = await accounts.load(session, org_id, lock=True)
    sub = acc.subscription
    if sub.provider_customer_id and d.get("customer_id") and sub.provider_customer_id != d.get("customer_id"):
        raise ValueError("customer doesn't match this organisation's billing account")
    status = str(d.get("status") or "active")
    if status not in ("active", "trialing", "past_due", "paused", "canceled"):
        raise ValueError(f"unknown subscription status {status!r}")
    old_plan = acc.plan
    period = d.get("current_billing_period") or {}
    start, end = _dt(period.get("starts_at")), _dt(period.get("ends_at"))
    sub.provider = "paddle"
    sub.provider_customer_id = d.get("customer_id") or sub.provider_customer_id
    sub.provider_subscription_id = d.get("id") or sub.provider_subscription_id
    sub.plan_key, sub.status = plan.key, status
    sub.cancel_at_period_end = ((d.get("scheduled_change") or {}).get("action") == "cancel")
    sub.updated_at = datetime.now(UTC)
    if start and end:
        sub.current_period_start, sub.current_period_end = start, end
    await session.flush()

    if status == "canceled":  # back to free from now on; purchased credits are kept
        sub.plan_key, sub.provider, sub.provider_subscription_id, sub.cancel_at_period_end = accounts.FREE, "none", None, False
        await session.flush()
        acc = await accounts.load(session, org_id, lock=True)
        now = datetime.now(UTC)
        from dateutil.relativedelta import relativedelta

        await accounts.roll_period(session, acc, start=now, end=now + relativedelta(months=1))
        return
    if status not in accounts.PAID_ACCESS or not (start and end):
        return
    acc = await accounts.load(session, org_id, lock=True)
    if start != acc.balance.period_start:
        await accounts.roll_period(session, acc, start=start, end=end)  # new billing period: full allowance
    elif old_plan.key != plan.key:
        # Plan changed mid-period: the allowance moves by the difference (never below zero).
        diff = plan.monthly_credits - old_plan.monthly_credits
        await session.execute(
            update(CreditBalance).where(CreditBalance.org_id == org_id).values(plan_remaining=func.greatest(CreditBalance.plan_remaining + diff, 0), updated_at=func.now())
        )
        await accounts._ledger(session, org_id, diff, "plan", "period_grant", f"plan_change:{event_id}", f"{old_plan.name} → {plan.name}")


async def _transaction(session: AsyncSession, org_id: UUID, d: dict[str, Any]) -> None:
    txn = str(d.get("id") or "")
    custom = d.get("custom_data") or {}
    price = ((d.get("items") or [{}])[0].get("price") or {}).get("id")
    total = int(str(((d.get("details") or {}).get("totals") or {}).get("grand_total") or "0"))
    pack = (await session.execute(select(CreditPack).where(CreditPack.paddle_price_id == price))).scalar_one_or_none() if price else None
    kind = "credit_pack" if (custom.get("kind") == "credit_pack" or pack is not None) and not d.get("subscription_id") else "subscription"
    desc = (pack.name if f"{pack.credits:,}" in pack.name else f"{pack.name} ({pack.credits:,} credits)") if kind == "credit_pack" and pack else "Subscription"
    if kind == "subscription":
        plan = (await session.execute(select(Plan).where(Plan.paddle_price_id == price))).scalar_one_or_none() if price else None
        desc = f"{plan.name} plan" if plan else "Subscription"
    exists = await session.scalar(select(Invoice.id).where(Invoice.provider_transaction_id == txn))
    if exists is None:
        session.add(
            Invoice(
                id=uuid4(),
                org_id=org_id,
                provider="paddle",
                provider_transaction_id=txn,
                number=d.get("invoice_number"),
                status=str(d.get("status") or "completed"),
                kind=kind,
                total_cents=total,
                currency=str(d.get("currency_code") or "EUR"),
                description=desc,
                billed_at=_dt(d.get("billed_at")),
            )
        )
        await session.flush()
    if kind == "credit_pack":
        if pack is None:
            raise ValueError(f"no credit pack has Paddle price {price!r}")
        await accounts.grant(session, org_id, pack.credits, reason="top_up", reference=f"paddle:{txn}", note=pack.name)


async def fixture_complete(session: AsyncSession, principal: Principal, transaction_id: str) -> list[str]:
    """Fixture mode only: finish a checkout the way Paddle would, through signed webhooks."""
    if get_settings().paddle_mode != "fixture":
        raise NotFound("Not available.")
    t = paddle.FIXTURE.transactions.get(transaction_id)
    if t is None or t["custom_data"].get("org_id") != str(principal.org_id):
        raise NotFound("Checkout not found.")
    key, kind = t["custom_data"]["key"], t["custom_data"]["kind"]
    item = await session.get(Plan if kind == "subscription" else CreditPack, key)
    if item is None:
        raise NotFound("Checkout not found.")
    outcomes = []
    for ev in paddle.fixture_events(transaction_id, price_cents=item.price_cents or 0, currency=item.currency, recurring=kind == "subscription"):
        raw = paddle.encode(ev)
        header = paddle.sign(raw, paddle.FIXTURE_SECRET)
        assert paddle.verify(raw, header, paddle.webhook_secret(), tolerance_s=get_settings().paddle_webhook_tolerance_seconds)
        outcomes.append(await apply_event(session, ev))
    return outcomes
