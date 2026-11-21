from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.deps import Principal
from agentfirm.core.errors import NotFound
from agentfirm.modules.audit.service import record

from .models import Project


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    created_at: datetime


async def list_projects(session: AsyncSession, principal: Principal) -> list[Project]:
    return list((await session.execute(select(Project).where(Project.org_id == principal.org_id).order_by(Project.name))).scalars())


async def get_project(session: AsyncSession, principal: Principal, project_id: UUID) -> Project:
    p = (await session.execute(select(Project).where(Project.id == project_id, Project.org_id == principal.org_id))).scalar_one_or_none()
    if p is None:
        raise NotFound("Project not found.")
    return p


async def create_project(session: AsyncSession, principal: Principal, body: ProjectIn) -> Project:
    p = Project(org_id=principal.org_id, name=body.name.strip(), description=body.description, created_by=principal.user_id)
    session.add(p)
    await session.flush()
    await record(session, action="project.created", target_type="project", target_id=p.id, actor=principal, after={"name": p.name})
    return p
