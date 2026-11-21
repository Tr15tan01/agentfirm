"""Idea board: ideas saved by the Creative agent; people move them between columns.

Rejecting an idea also appends it to the org's `rejected_ideas` memory so the agent stops
suggesting it (the user asked for it explicitly, so no extra confirmation is needed).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.errors import NotFound
from agentfirm.core.permissions import Perm
from agentfirm.modules.audit.service import record
from agentfirm.modules.memory.models import Memory

from .models import Idea

router = APIRouter(prefix="/ideas", tags=["ideas"])
Column = Literal["new", "shortlisted", "developing", "parked", "rejected"]


class IdeaOut(BaseModel):
    id: UUID
    title: str
    summary: str
    approach: str
    lens: str | None
    tags: list[str]
    scores: dict[str, Any] | None
    column: Column
    project_id: UUID | None
    execution_id: UUID | None
    created_at: datetime


class IdeaPatch(BaseModel):
    column: Column | None = None
    tags: list[str] | None = Field(default=None, max_length=12)


def _out(i: Idea) -> IdeaOut:
    return IdeaOut(
        id=i.id, title=i.title, summary=i.summary, approach=i.approach, lens=i.lens, tags=list(i.tags or []), scores=i.scores,
        column=i.board_column, project_id=i.project_id, execution_id=i.execution_id, created_at=i.created_at,  # type: ignore[arg-type]
    )


@router.get("", response_model=list[IdeaOut])
async def list_ideas(
    session: DbSession,
    column: Column | None = None,
    project_id: UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    principal: Principal = require(Perm.WORKSPACE_READ),
) -> list[IdeaOut]:
    q = select(Idea).where(Idea.org_id == principal.org_id)
    if column:
        q = q.where(Idea.board_column == column)
    if project_id:
        q = q.where(Idea.project_id == project_id)
    return [_out(i) for i in (await session.execute(q.order_by(Idea.created_at.desc()).limit(limit))).scalars()]


@router.patch("/{idea_id}", response_model=IdeaOut)
async def update_idea(idea_id: UUID, body: IdeaPatch, session: DbSession, principal: Principal = require(Perm.AGENTS_USE)) -> IdeaOut:
    idea = (await session.execute(select(Idea).where(Idea.id == idea_id, Idea.org_id == principal.org_id).with_for_update())).scalar_one_or_none()
    if idea is None:
        raise NotFound("Idea not found.")
    before = {"column": idea.board_column}
    if body.tags is not None:
        idea.tags = [t[:48] for t in body.tags]
    if body.column and body.column != idea.board_column:
        idea.board_column = body.column
        if body.column == "rejected":
            mem = (
                await session.execute(select(Memory).where(Memory.org_id == principal.org_id, Memory.project_id.is_(None), Memory.key == "rejected_ideas").with_for_update())
            ).scalar_one_or_none()
            if mem is None:
                session.add(Memory(org_id=principal.org_id, key="rejected_ideas", value=idea.title, updated_by=principal.user_id))
            elif idea.title not in mem.value.split("\n"):
                mem.value = f"{mem.value}\n{idea.title}"[-20_000:]
                mem.updated_by, mem.updated_at = principal.user_id, datetime.now(UTC)
    await session.flush()
    await record(session, action="idea.updated", target_type="idea", target_id=idea.id, actor=principal, before=before, after={"column": idea.board_column})
    return _out(idea)
