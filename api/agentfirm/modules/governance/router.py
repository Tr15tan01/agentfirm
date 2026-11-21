from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.permissions import Perm

from . import standing

router = APIRouter(prefix="/standing-approvals", tags=["approvals"])


@router.get("", response_model=list[standing.StandingOut])
async def list_standing(session: DbSession, principal: Principal = require(Perm.TASKS_READ)) -> list[standing.StandingOut]:
    return await standing.list_(session, principal)


@router.get("/tools", response_model=dict[str, list[str]])
async def tool_facts(principal: Principal = require(Perm.TASKS_READ)) -> dict[str, list[str]]:
    """Tools that can be pre-approved and the facts their conditions can use."""
    return standing.TOOL_FACTS


@router.post("", response_model=standing.StandingOut, status_code=201)
async def create_standing(body: standing.StandingIn, session: DbSession, principal: Principal = require(Perm.APPROVALS_DECIDE)) -> standing.StandingOut:
    return await standing.create(session, principal, body)


@router.post("/{standing_id}/revoke", response_model=standing.StandingOut)
async def revoke_standing(standing_id: UUID, session: DbSession, principal: Principal = require(Perm.APPROVALS_DECIDE)) -> standing.StandingOut:
    return await standing.revoke(session, principal, standing_id)
