from __future__ import annotations

from fastapi import APIRouter

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.permissions import Perm

from . import service
from .service import AgentOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut])
async def list_agents(session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)) -> list[AgentOut]:
    return await service.list_agents(session, principal)


@router.get("/{key}", response_model=AgentOut)
async def get_agent(key: str, session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)) -> AgentOut:
    return await service.get_agent(session, principal, key)
