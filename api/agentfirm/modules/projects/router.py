from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.permissions import Perm

from . import service
from .service import ProjectIn, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)):  # type: ignore[no-untyped-def]
    return await service.list_projects(session, principal)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: UUID, session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)):  # type: ignore[no-untyped-def]
    return await service.get_project(session, principal, project_id)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, session: DbSession, principal: Principal = require(Perm.PROJECTS_MANAGE)):  # type: ignore[no-untyped-def]
    return await service.create_project(session, principal, body)
