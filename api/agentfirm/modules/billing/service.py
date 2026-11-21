from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.deps import Principal
from agentfirm.modules.identity.models import Membership, User

from .models import UsageRecord

Range = Literal["7d", "30d", "90d"]


class DailyPoint(BaseModel):
    day: date
    tokens: int
    credits: int


class AgentUsage(BaseModel):
    agent: str
    requests: int
    tokens: int
    credits: int


class ModelUsage(BaseModel):
    model: str
    provider: str
    capability: str
    requests: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


class MemberUsage(BaseModel):
    user_id: str
    name: str
    role: str
    requests: int
    credits: int


class UsageReport(BaseModel):
    range: Range
    totals: dict[str, int]
    daily: list[DailyPoint]
    by_agent: list[AgentUsage]
    by_model: list[ModelUsage]
    by_member: list[MemberUsage]


async def report(session: AsyncSession, principal: Principal, range_: Range) -> UsageReport:
    days = {"7d": 7, "30d": 30, "90d": 90}[range_]
    since = datetime.now(UTC) - timedelta(days=days)
    base = (UsageRecord.org_id == principal.org_id) & (UsageRecord.created_at >= since)
    tokens = UsageRecord.tokens_in + UsageRecord.tokens_out

    t = (await session.execute(select(func.count(), func.coalesce(func.sum(tokens), 0), func.coalesce(func.sum(UsageRecord.credits), 0)).where(base))).one()
    day = cast(UsageRecord.created_at, Date)
    daily = (await session.execute(select(day, func.sum(tokens), func.sum(UsageRecord.credits)).where(base).group_by(day).order_by(day))).all()
    agents = (
        await session.execute(
            select(UsageRecord.agent_key, func.count(), func.sum(tokens), func.sum(UsageRecord.credits))
            .where(base)
            .group_by(UsageRecord.agent_key)
            .order_by(func.sum(UsageRecord.credits).desc())
        )
    ).all()
    models = (
        await session.execute(
            select(
                UsageRecord.model,
                UsageRecord.provider,
                UsageRecord.capability,
                func.count(),
                func.sum(UsageRecord.tokens_in),
                func.sum(UsageRecord.tokens_out),
                func.sum(UsageRecord.cost_usd),
            )
            .where(base)
            .group_by(UsageRecord.model, UsageRecord.provider, UsageRecord.capability)
            .order_by(func.sum(UsageRecord.cost_usd).desc())
        )
    ).all()
    members = (
        await session.execute(
            select(User.id, User.name, Membership.role, func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.credits), 0))
            .join(UsageRecord, (UsageRecord.user_id == User.id) & base)
            .join(Membership, (Membership.user_id == User.id) & (Membership.org_id == principal.org_id))
            .group_by(User.id, User.name, Membership.role)
            .order_by(func.sum(UsageRecord.credits).desc())
        )
    ).all()
    return UsageReport(
        range=range_,
        totals={"requests": int(t[0]), "tokens": int(t[1]), "credits": int(t[2])},
        daily=[DailyPoint(day=d, tokens=int(tk or 0), credits=int(c or 0)) for d, tk, c in daily],
        by_agent=[AgentUsage(agent=a, requests=int(n), tokens=int(tk or 0), credits=int(c or 0)) for a, n, tk, c in agents],
        by_model=[
            ModelUsage(model=m, provider=p, capability=cap, requests=int(n), tokens_in=int(ti or 0), tokens_out=int(to or 0), cost_usd=Decimal(cost or 0))
            for m, p, cap, n, ti, to, cost in models
        ],
        by_member=[MemberUsage(user_id=str(u), name=nm, role=r, requests=int(n), credits=int(c)) for u, nm, r, n, c in members],
    )
