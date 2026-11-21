"""Named organisation memories (brand_voice, preferred_approaches, rejected_ideas, …).

Agents only *propose* memory writes (`memory.write` returns a proposal); people save them
here. Readable by the workspace, writable by admins (agents:configure) because memories
steer every future agent run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from sqlalchemy import select

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.permissions import Perm
from agentfirm.modules.audit.service import record
from agentfirm.modules.projects.service import get_project

from .models import Memory

router = APIRouter(prefix="/memories", tags=["memories"])
KEY = r"^[a-z][a-z0-9_]{1,63}$"


class MemoryOut(BaseModel):
    key: str
    value: str
    project_id: UUID | None
    updated_at: datetime


class MemoryIn(BaseModel):
    value: str = Field(max_length=20_000)
    project_id: UUID | None = None


@router.get("", response_model=list[MemoryOut])
async def list_memories(session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)) -> list[MemoryOut]:
    rows = (await session.execute(select(Memory).where(Memory.org_id == principal.org_id).order_by(Memory.key))).scalars()
    return [MemoryOut(key=m.key, value=m.value, project_id=m.project_id, updated_at=m.updated_at) for m in rows]


@router.put("/{key}", response_model=MemoryOut)
async def put_memory(body: MemoryIn, session: DbSession, key: str = Path(pattern=KEY), principal: Principal = require(Perm.AGENTS_CONFIGURE)) -> MemoryOut:
    if body.project_id:
        await get_project(session, principal, body.project_id)
    scope = Memory.project_id.is_(None) if body.project_id is None else Memory.project_id == body.project_id
    m = (await session.execute(select(Memory).where(Memory.org_id == principal.org_id, Memory.key == key, scope).with_for_update())).scalar_one_or_none()
    before = {"value": m.value[:500]} if m else None
    if m is None:
        m = Memory(org_id=principal.org_id, project_id=body.project_id, key=key, value=body.value, updated_by=principal.user_id)
        session.add(m)
    else:
        m.value, m.updated_by, m.updated_at = body.value, principal.user_id, datetime.now(UTC)
    await session.flush()
    await record(session, action="memory.updated", target_type="memory", target_id=m.id, actor=principal, before=before, after={"key": key, "value": body.value[:500]})
    return MemoryOut(key=m.key, value=m.value, project_id=m.project_id, updated_at=m.updated_at)
