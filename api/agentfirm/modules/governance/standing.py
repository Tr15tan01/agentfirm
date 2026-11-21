"""Standing approvals (Phase 6, ADR 0006): pre-approve a recurring gated action — e.g. the weekly
report email to your own domain, or LinkedIn posts — within explicit limits.

Rules (all enforced on the server):
* Only `external` and `financial` tools; never `destructive` ones (production deploys, deletions).
  Financial tools need an `amount ≤ X` condition.
* Required: an expiry (at most 90 days) and a maximum number of uses (1 to 1,000).
* The creator must be able to approve the action themselves (approver class permission and the
  tool's own permission, ADR 0004). This is re-checked against the creator's *current* role every
  time it's used; if they lose it, the standing approval stops applying.
* Conditions are checked against facts the agent program reports for the prepared action. A fact
  that's missing never matches (fail closed).
* Each use is counted atomically, recorded as an approved approval request linked to it, shown in
  the run, and audit-logged on creation and revocation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.agents.registry import registry
from agentfirm.core.deps import Principal
from agentfirm.core.errors import Forbidden, NotFound, Unprocessable
from agentfirm.core.permissions import Perm
from agentfirm.modules.audit.service import record

from .models import StandingApproval

MAX_DAYS = 90
ALLOWED_CLASSES = {"external", "financial"}
Fact = Literal["channel", "amount", "currency", "campaign", "payee", "recipient_domains", "recipient_count", "target_count", "environment", "repository"]
#: Facts each gated tool reports (programs' `approval_facts`), shown in the UI.
TOOL_FACTS: dict[str, list[str]] = {
    "social.publish": ["channel"],
    "ads.budget_change": ["amount", "currency", "campaign"],
    "email.send": ["recipient_domains", "recipient_count"],
    "payments.execute": ["amount", "currency", "payee"],
    "automation.run": ["target_count"],
    "calendar.create_event": [],
    "repo.open_pull_request": ["repository"],
    "deploy.preview": ["environment", "repository"],
}


class Condition(BaseModel):
    fact: Fact
    op: Literal["eq", "in", "lte", "gte", "all_in"]
    value: str | float | list[str]

    @model_validator(mode="after")
    def _shape(self) -> Condition:
        if self.op in ("lte", "gte") and not isinstance(self.value, int | float):
            raise ValueError(f"{self.op} needs a number")
        if self.op in ("in", "all_in") and not (isinstance(self.value, list) and self.value):
            raise ValueError(f"{self.op} needs a non-empty list")
        if self.op == "eq" and isinstance(self.value, list):
            raise ValueError("eq needs a single value")
        return self


class StandingIn(BaseModel):
    tool: str
    agent: str | None = Field(default=None, description="Limit to one agent (null = any agent granted the tool)")
    conditions: list[Condition] = Field(default_factory=list, max_length=10)
    note: str = Field(min_length=3, max_length=500, description="Why this is pre-approved (shown on every use)")
    max_uses: int = Field(ge=1, le=1000)
    expires_in_days: int = Field(ge=1, le=MAX_DAYS)


class StandingOut(BaseModel):
    id: UUID
    tool: str
    agent: str | None
    conditions: list[Condition]
    note: str
    max_uses: int
    uses: int
    expires_at: datetime
    created_by: UUID
    created_at: datetime
    revoked_at: datetime | None
    active: bool


def _out(s: StandingApproval) -> StandingOut:
    now = datetime.now(UTC)
    return StandingOut(
        id=s.id,
        tool=s.tool,
        agent=s.agent_key,
        conditions=[Condition.model_validate(c) for c in s.conditions],
        note=s.note,
        max_uses=s.max_uses,
        uses=s.uses,
        expires_at=s.expires_at,
        created_by=s.created_by,
        created_at=s.created_at,
        revoked_at=s.revoked_at,
        active=s.revoked_at is None and s.expires_at > now and s.uses < s.max_uses,
    )


def required_permissions(tool: str) -> set[str]:
    """What an approver must hold to pre-approve (and, later, to keep it applying)."""
    from agentfirm.modules.tasks.service import APPROVER

    spec = registry().tools[tool]
    return {APPROVER[spec.side_effect.value].value, spec.required_permission, Perm.APPROVALS_DECIDE.value}


async def create(session: AsyncSession, principal: Principal, body: StandingIn) -> StandingOut:
    reg = registry()
    spec = reg.tools.get(body.tool)
    if spec is None:
        raise NotFound("Unknown tool.")
    if spec.side_effect.value not in ALLOWED_CLASSES:
        raise Unprocessable(f"{body.tool} is {spec.side_effect.value}: it always needs a person to approve each time.")
    if body.agent is not None and body.agent not in reg.agents:
        raise NotFound("Unknown agent.")
    agents = [body.agent] if body.agent else list(reg.agents)
    from agentfirm.agents.contracts import ApprovalPolicy

    if not any(any(g.tool == body.tool for g in reg.agents[a].tools) and reg.effective_approval(a, body.tool) == ApprovalPolicy.REQUIRE for a in agents):
        raise Unprocessable(f"No agent{' ' + body.agent if body.agent else ''} needs approval for {body.tool}, so there's nothing to pre-approve.")
    if spec.side_effect.value == "financial" and not any(c.fact == "amount" and c.op == "lte" for c in body.conditions):
        raise Unprocessable("Financial actions need a maximum amount (amount ≤ …).")
    allowed = set(TOOL_FACTS.get(body.tool, []))
    if bad := sorted({c.fact for c in body.conditions} - allowed):
        raise Unprocessable(f"{body.tool} doesn't report: {', '.join(bad)} (available: {', '.join(sorted(allowed)) or 'none'}).")
    missing = required_permissions(body.tool) - {p.value for p in principal.permissions}
    if missing:
        raise Forbidden(f"You can only pre-approve what you could approve yourself (missing: {', '.join(sorted(missing))}).")
    row = StandingApproval(
        id=uuid4(),
        org_id=principal.org_id,
        tool=body.tool,
        agent_key=body.agent,
        conditions=[c.model_dump() for c in body.conditions],
        note=body.note.strip(),
        max_uses=body.max_uses,
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days),
        created_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await record(session, action="standing_approval.created", target_type="standing_approval", target_id=row.id, actor=principal, after=_out(row).model_dump(mode="json"))
    return _out(row)


async def list_(session: AsyncSession, principal: Principal) -> list[StandingOut]:
    rows = (await session.execute(select(StandingApproval).where(StandingApproval.org_id == principal.org_id).order_by(StandingApproval.created_at.desc()))).scalars()
    return [_out(r) for r in rows]


async def revoke(session: AsyncSession, principal: Principal, sid: UUID) -> StandingOut:
    row = (await session.execute(select(StandingApproval).where(StandingApproval.id == sid, StandingApproval.org_id == principal.org_id))).scalar_one_or_none()
    if row is None:
        raise NotFound("Standing approval not found.")
    if row.created_by != principal.user_id and not principal.can(Perm.WORKSPACE_MANAGE):
        raise Forbidden("Only its creator or a workspace admin can revoke it.")
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by = datetime.now(UTC), principal.user_id
        await record(session, action="standing_approval.revoked", target_type="standing_approval", target_id=row.id, actor=principal)
    return _out(row)


# ── matching (engine) ────────────────────────────────────────────────────────


def matches(conditions: list[dict[str, Any]], facts: dict[str, Any]) -> bool:
    for c in conditions:
        if c["fact"] not in facts or facts[c["fact"]] is None:
            return False  # fail closed
        v, want, op = facts[c["fact"]], c["value"], c["op"]
        try:
            ok = (
                (op == "eq" and str(v).lower() == str(want).lower())
                or (op == "in" and str(v).lower() in {str(w).lower() for w in want})
                or (op == "lte" and float(v) <= float(want))
                or (op == "gte" and float(v) >= float(want))
                or (op == "all_in" and isinstance(v, list) and len(v) > 0 and {str(x).lower() for x in v} <= {str(w).lower() for w in want})
            )
        except (TypeError, ValueError):
            ok = False
        if not ok:
            return False
    return True


async def claim(session: AsyncSession, *, org_id: UUID, tool: str, agent: str, facts: dict[str, Any], perms_of) -> StandingApproval | None:  # type: ignore[no-untyped-def]
    """Find a standing approval that covers this action and count one use (atomically)."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(StandingApproval)
            .where(
                StandingApproval.org_id == org_id,
                StandingApproval.tool == tool,
                StandingApproval.revoked_at.is_(None),
                StandingApproval.expires_at > now,
                StandingApproval.uses < StandingApproval.max_uses,
                (StandingApproval.agent_key.is_(None)) | (StandingApproval.agent_key == agent),
            )
            .order_by(StandingApproval.created_at)
        )
    ).scalars()
    for row in rows:
        if not matches(row.conditions, facts):
            continue
        if not required_permissions(tool) <= set(await perms_of(row.created_by)):
            continue  # the creator can no longer approve this themselves
        used = await session.scalar(
            update(StandingApproval)
            .where(StandingApproval.id == row.id, StandingApproval.uses < StandingApproval.max_uses, StandingApproval.revoked_at.is_(None))
            .values(uses=StandingApproval.uses + 1)
            .returning(StandingApproval.id)
        )
        if used is not None:
            return row
    return None
