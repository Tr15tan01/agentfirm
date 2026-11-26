"""Super-admin platform administration (Phase 6): plans and pricing, credit packs, organisation
accounts (credits, manual plans), tool kill-switches, agent enablement and rollback, billing events.

Authorization is the platform super-admin flag, checked on the server for every request. Every
change is audit-logged with before/after values.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from agentfirm.agents.registry import registry
from agentfirm.core.db import DbContext, apply_context
from agentfirm.core.deps import DbSession, SuperAdmin
from agentfirm.core.errors import Conflict, NotFound, Unprocessable
from agentfirm.modules.agents.models import Agent, AgentVersion
from agentfirm.modules.audit.service import record
from agentfirm.modules.billing import accounts
from agentfirm.modules.billing.models import BillingEvent, CreditBalance, CreditPack, Plan, Subscription, UsageRecord
from agentfirm.modules.billing.subscriptions import PackOut, PlanOut, pack_out, plan_out
from agentfirm.modules.identity.models import Membership, Organization
from agentfirm.modules.tasks.service import StopIn, StopOut, stop_executions

from .models import ToolOverride

router = APIRouter(prefix="/admin", tags=["admin"])


# ── plans & packs ────────────────────────────────────────────────────────────


class PlanIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)
    monthly_credits: int = Field(ge=0, le=100_000_000)
    max_seats: int = Field(ge=1, le=10_000)
    max_concurrent_tasks: int = Field(ge=1, le=1_000)
    agents: list[str] | None = Field(default=None, description="null = every agent")
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    paddle_price_id: str | None = Field(default=None, pattern=r"^pri_[a-z0-9_]{3,60}$")
    is_public: bool = True
    is_active: bool = True
    sort: int = 0


class AdminPlanOut(PlanOut):
    paddle_price_id: str | None
    is_public: bool
    is_active: bool
    sort: int
    organizations: int


class PackIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    credits: int = Field(ge=1, le=100_000_000)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    paddle_price_id: str | None = Field(default=None, pattern=r"^pri_[a-z0-9_]{3,60}$")
    is_active: bool = True


class AdminPackOut(PackOut):
    paddle_price_id: str | None
    is_active: bool


def _plan_dict(p: Plan) -> dict[str, Any]:
    return {k: getattr(p, k) for k in PlanIn.model_fields}


@router.get("/plans", response_model=list[AdminPlanOut])
async def list_plans(admin: SuperAdmin, session: DbSession) -> list[AdminPlanOut]:
    counts = dict((await session.execute(select(Subscription.plan_key, func.count()).group_by(Subscription.plan_key))).all())
    rows = (await session.execute(select(Plan).order_by(Plan.sort, Plan.key))).scalars()
    return [
        AdminPlanOut(
            **plan_out(p).model_dump(),
            paddle_price_id=p.paddle_price_id,
            is_public=p.is_public,
            is_active=p.is_active,
            sort=p.sort,
            organizations=counts.get(p.key, 0),
        )
        for p in rows
    ]


@router.put("/plans/{key}", response_model=list[AdminPlanOut])
async def put_plan(key: str, body: PlanIn, admin: SuperAdmin, session: DbSession) -> list[AdminPlanOut]:
    if not (2 <= len(key) <= 32 and key.replace("_", "").isalnum() and key.islower()):
        raise Unprocessable("Plan keys are 2-32 lowercase letters, digits or underscores.")
    if body.agents is not None and (unknown := sorted(set(body.agents) - set(registry().agents))):
        raise Unprocessable(f"Unknown agents: {', '.join(unknown)}")
    if key == accounts.FREE and (body.price_cents or body.paddle_price_id or not body.is_active):
        raise Unprocessable("The free plan must stay active and free; every workspace falls back to it.")
    existing = await session.get(Plan, key)
    before = _plan_dict(existing) if existing else None
    values = {**body.model_dump(), "updated_at": datetime.now(UTC)}
    await session.execute(insert(Plan).values(key=key, **values).on_conflict_do_update(index_elements=["key"], set_=values))
    await record(
        session,
        action="plan.updated" if existing else "plan.created",
        target_type="plan",
        target_id=None,
        actor=admin,
        before=before,
        after={"key": key, **body.model_dump()},
    )
    return await list_plans(admin, session)


@router.get("/credit-packs", response_model=list[AdminPackOut])
async def list_packs(admin: SuperAdmin, session: DbSession) -> list[AdminPackOut]:
    rows = (await session.execute(select(CreditPack).order_by(CreditPack.credits))).scalars()
    return [AdminPackOut(**pack_out(p).model_dump(), paddle_price_id=p.paddle_price_id, is_active=p.is_active) for p in rows]


@router.put("/credit-packs/{key}", response_model=list[AdminPackOut])
async def put_pack(key: str, body: PackIn, admin: SuperAdmin, session: DbSession) -> list[AdminPackOut]:
    if not (2 <= len(key) <= 32 and key.replace("_", "").isalnum() and key.islower()):
        raise Unprocessable("Pack keys are 2-32 lowercase letters, digits or underscores.")
    existing = await session.get(CreditPack, key)
    before = {k: getattr(existing, k) for k in PackIn.model_fields} if existing else None
    values = {**body.model_dump(), "updated_at": datetime.now(UTC)}
    await session.execute(insert(CreditPack).values(key=key, **values).on_conflict_do_update(index_elements=["key"], set_=values))
    await record(
        session,
        action="credit_pack.updated" if existing else "credit_pack.created",
        target_type="credit_pack",
        target_id=None,
        actor=admin,
        before=before,
        after={"key": key, **body.model_dump()},
    )
    return await list_packs(admin, session)


# ── organisation accounts ────────────────────────────────────────────────────


class AccountRow(BaseModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime
    plan: str
    status: str
    provider: str
    credits_available: int
    credits_used_30d: int
    members: int


class GrantIn(BaseModel):
    credits: int = Field(description="Positive to grant, negative to remove purchased credits")
    note: str = Field(min_length=3, max_length=500)


class ManualPlanIn(BaseModel):
    plan: str
    note: str = Field(min_length=3, max_length=500)


@router.get("/accounts", response_model=list[AccountRow])
async def list_accounts(admin: SuperAdmin, session: DbSession) -> list[AccountRow]:
    since = datetime.now(UTC) - timedelta(days=30)
    members = dict((await session.execute(select(Membership.org_id, func.count()).where(Membership.status == "active").group_by(Membership.org_id))).all())
    used = dict(
        (
            await session.execute(
                select(UsageRecord.org_id, func.coalesce(func.sum(UsageRecord.credits), 0)).where(UsageRecord.created_at >= since).group_by(UsageRecord.org_id)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(Organization, Subscription, CreditBalance)
            .outerjoin(Subscription, Subscription.org_id == Organization.id)
            .outerjoin(CreditBalance, CreditBalance.org_id == Organization.id)
            .order_by(Organization.created_at.desc())
            .limit(500)
        )
    ).all()
    return [
        AccountRow(
            id=o.id,
            name=o.name,
            slug=o.slug,
            created_at=o.created_at,
            plan=s.plan_key if s else accounts.FREE,
            status=s.status if s else "active",
            provider=s.provider if s else "none",
            credits_available=(b.plan_remaining + b.purchased_remaining) if b else 0,
            credits_used_30d=int(used.get(o.id, 0)),
            members=members.get(o.id, 0),
        )
        for o, s, b in rows
    ]


async def _org(session: DbSession, org_id: UUID) -> Organization:
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFound("Organisation not found.")
    await apply_context(session, DbContext(org_id=org_id, platform_admin=True))  # writes must target this org (RLS WITH CHECK)
    return org


@router.post("/accounts/{org_id}/credits", response_model=list[AccountRow])
async def grant_credits(org_id: UUID, body: GrantIn, admin: SuperAdmin, session: DbSession) -> list[AccountRow]:
    if body.credits == 0:
        raise Unprocessable("Give a non-zero number of credits.")
    await _org(session, org_id)
    acc = await accounts.load(session, org_id, lock=True)
    if body.credits < 0 and acc.balance.purchased_remaining + body.credits < 0:
        raise Unprocessable(f"Only {acc.balance.purchased_remaining} purchased credits can be removed.")
    await accounts.grant(session, org_id, body.credits, reason="admin_grant" if body.credits > 0 else "admin_debit", note=body.note, created_by=admin.user_id)
    await record(
        session,
        action="credits.granted" if body.credits > 0 else "credits.removed",
        target_type="organization",
        target_id=org_id,
        actor=admin,
        after={"credits": body.credits, "note": body.note},
        org_id=org_id,
    )
    return await list_accounts(admin, session)


@router.put("/accounts/{org_id}/plan", response_model=list[AccountRow])
async def set_manual_plan(org_id: UUID, body: ManualPlanIn, admin: SuperAdmin, session: DbSession) -> list[AccountRow]:
    """For invoiced customers outside Paddle. Paddle-managed subscriptions change only in Paddle."""
    await _org(session, org_id)
    plan = await session.get(Plan, body.plan)
    if plan is None or not plan.is_active:
        raise NotFound("Plan not found.")
    acc = await accounts.load(session, org_id, lock=True)
    sub = acc.subscription
    if sub.provider == "paddle" and sub.status in accounts.PAID_ACCESS:
        raise Conflict("This workspace pays through Paddle; change or cancel its subscription there.")
    before = {"plan": sub.plan_key, "provider": sub.provider}
    now = datetime.now(UTC)
    from dateutil.relativedelta import relativedelta

    await session.execute(
        update(Subscription)
        .where(Subscription.org_id == org_id)
        .values(plan_key=plan.key, status="active", provider="none" if plan.key == accounts.FREE else "manual", cancel_at_period_end=False, updated_at=now)
    )
    await session.flush()
    acc = await accounts.load(session, org_id, lock=True)
    await accounts.roll_period(session, acc, start=now, end=now + relativedelta(months=1))
    await record(
        session,
        action="plan.assigned",
        target_type="organization",
        target_id=org_id,
        actor=admin,
        before=before,
        after={"plan": plan.key, "note": body.note},
        org_id=org_id,
    )
    return await list_accounts(admin, session)


# ── tools ────────────────────────────────────────────────────────────────────


class ToolRow(BaseModel):
    key: str
    description: str
    side_effect: str
    required_permission: str
    agents: list[str]
    disabled: bool
    reason: str | None
    updated_at: datetime | None


class ToolSwitchIn(BaseModel):
    disabled: bool
    reason: str = Field(min_length=3, max_length=500)


@router.get("/tools", response_model=list[ToolRow])
async def list_tools(admin: SuperAdmin, session: DbSession) -> list[ToolRow]:
    reg = registry()
    overrides = {o.tool: o for o in (await session.execute(select(ToolOverride))).scalars()}
    out = []
    for key, spec in sorted(reg.tools.items()):
        o = overrides.get(key)
        out.append(
            ToolRow(
                key=key,
                description=spec.description,
                side_effect=spec.side_effect.value,
                required_permission=spec.required_permission,
                agents=sorted(a for a, m in reg.agents.items() if any(g.tool == key for g in m.tools)),
                disabled=bool(o and o.disabled),
                reason=o.reason if o else None,
                updated_at=o.updated_at if o else None,
            )
        )
    return out


@router.put("/tools/{key}", response_model=list[ToolRow])
async def switch_tool(key: str, body: ToolSwitchIn, admin: SuperAdmin, session: DbSession) -> list[ToolRow]:
    if key not in registry().tools:
        raise NotFound("Unknown tool.")
    values = {"disabled": body.disabled, "reason": body.reason, "updated_by": admin.user_id, "updated_at": datetime.now(UTC)}
    await session.execute(insert(ToolOverride).values(tool=key, **values).on_conflict_do_update(index_elements=["tool"], set_=values))
    await record(
        session,
        action="tool.disabled" if body.disabled else "tool.enabled",
        target_type="tool",
        target_id=None,
        actor=admin,
        after={"tool": key, "reason": body.reason},
    )
    from agentfirm.runtime.tools.runtime import reset_override_cache

    reset_override_cache()
    return await list_tools(admin, session)


# ── agents ───────────────────────────────────────────────────────────────────


class AgentAdminRow(BaseModel):
    key: str
    name: str
    enabled: bool
    current_version: str | None
    versions: list[str]


class AgentPatch(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=500)


class RollbackIn(BaseModel):
    version: str
    reason: str = Field(min_length=3, max_length=500)


@router.get("/agents", response_model=list[AgentAdminRow])
async def list_agent_admin(admin: SuperAdmin, session: DbSession) -> list[AgentAdminRow]:
    agents = (await session.execute(select(Agent).order_by(Agent.key))).scalars().all()
    out = []
    for a in agents:
        vers = (
            await session.execute(
                select(AgentVersion.version, AgentVersion.is_current).where(AgentVersion.agent_id == a.id).order_by(AgentVersion.created_at.desc())
            )
        ).all()
        out.append(
            AgentAdminRow(
                key=a.key, name=a.name, enabled=a.is_enabled, current_version=next((v for v, cur in vers if cur), None), versions=[v for v, _ in vers]
            )
        )
    return out


@router.patch("/agents/{key}", response_model=list[AgentAdminRow])
async def patch_agent(key: str, body: AgentPatch, admin: SuperAdmin, session: DbSession) -> list[AgentAdminRow]:
    agent = (await session.execute(select(Agent).where(Agent.key == key))).scalar_one_or_none()
    if agent is None:
        raise NotFound("Unknown agent.")
    before = agent.is_enabled
    agent.is_enabled = body.enabled
    await record(
        session,
        action="agent.enabled" if body.enabled else "agent.disabled",
        target_type="agent",
        target_id=agent.id,
        actor=admin,
        before={"enabled": before},
        after={"enabled": body.enabled, "reason": body.reason},
    )
    return await list_agent_admin(admin, session)


@router.post("/agents/stop", response_model=StopOut)
async def stop_agents(body: StopIn, admin: SuperAdmin, session: DbSession) -> StopOut:
    """Emergency stop: cancel all running/queued work of one agent (`agent`) or every agent, across
    all workspaces or just one (`org_id`). Running work is interrupted by the workers within seconds."""
    return await stop_executions(session, admin, body, platform=True)


@router.post("/agents/{key}/rollback", response_model=list[AgentAdminRow])
async def rollback_agent(key: str, body: RollbackIn, admin: SuperAdmin, session: DbSession) -> list[AgentAdminRow]:
    from agentfirm.agents.publishing import PublishError, rollback

    try:
        await rollback(session, key, body.version)
    except PublishError as exc:
        raise Unprocessable(str(exc)) from exc
    await record(
        session,
        action="agent.rolled_back",
        target_type="agent",
        target_id=None,
        actor=admin,
        after={"agent": key, "version": body.version, "reason": body.reason},
    )
    return await list_agent_admin(admin, session)


# ── billing events ───────────────────────────────────────────────────────────


class BillingEventRow(BaseModel):
    id: str
    type: str
    org_id: UUID | None
    received_at: datetime
    processed_at: datetime | None
    error: str | None


@router.get("/billing-events", response_model=list[BillingEventRow])
async def billing_events(admin: SuperAdmin, session: DbSession) -> list[BillingEventRow]:
    rows = (await session.execute(select(BillingEvent).order_by(BillingEvent.received_at.desc()).limit(200))).scalars()
    return [BillingEventRow(id=e.id, type=e.type, org_id=e.subject_org_id, received_at=e.received_at, processed_at=e.processed_at, error=e.error) for e in rows]
