from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.deps import Principal
from agentfirm.core.errors import NotFound
from agentfirm.modules.agents.models import Agent
from agentfirm.modules.agents.service import current_version
from agentfirm.modules.projects.service import get_project

from .models import Conversation, Message


class ConversationIn(BaseModel):
    agent: str = Field(max_length=48)
    title: str = Field(min_length=1, max_length=200)
    project_id: UUID | None = None


class ConversationOut(BaseModel):
    id: UUID
    agent: str
    title: str
    project_id: UUID | None
    pinned: bool
    updated_at: datetime


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=32_000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    content: str
    model: str | None
    execution_id: UUID | None
    created_at: datetime


async def list_conversations(session: AsyncSession, principal: Principal, agent: str | None) -> list[ConversationOut]:
    q = select(Conversation, Agent.key).join(Agent, Agent.id == Conversation.agent_id).where(Conversation.org_id == principal.org_id)
    if agent:
        q = q.where(Agent.key == agent)
    rows = (await session.execute(q.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()))).all()
    return [ConversationOut(id=c.id, agent=k, title=c.title, project_id=c.project_id, pinned=c.pinned, updated_at=c.updated_at) for c, k in rows]


async def _get(session: AsyncSession, principal: Principal, conversation_id: UUID) -> Conversation:
    c = (await session.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.org_id == principal.org_id))).scalar_one_or_none()
    if c is None:
        raise NotFound("Conversation not found.")
    return c


async def create_conversation(session: AsyncSession, principal: Principal, body: ConversationIn) -> ConversationOut:
    agent, _ = await current_version(session, body.agent)
    if body.project_id:
        await get_project(session, principal, body.project_id)
    c = Conversation(org_id=principal.org_id, agent_id=agent.id, project_id=body.project_id, title=body.title.strip(), created_by=principal.user_id)
    session.add(c)
    await session.flush()
    await session.refresh(c)
    return ConversationOut(id=c.id, agent=agent.key, title=c.title, project_id=c.project_id, pinned=c.pinned, updated_at=c.updated_at)


async def list_messages(session: AsyncSession, principal: Principal, conversation_id: UUID) -> list[Message]:
    await _get(session, principal, conversation_id)
    q = select(Message).where(Message.conversation_id == conversation_id, Message.org_id == principal.org_id).order_by(Message.created_at)
    return list((await session.execute(q)).scalars())


async def post_message(session: AsyncSession, principal: Principal, conversation_id: UUID, body: MessageIn) -> Message:
    """Stores the user's message. The agent reply is produced by the Agent Engine (Phase 4)
    and streamed over SSE; this endpoint therefore returns 202 Accepted."""
    c = await _get(session, principal, conversation_id)
    m = Message(org_id=principal.org_id, conversation_id=c.id, role="user", content=body.content, author_id=principal.user_id)
    session.add(m)
    c.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(m)
    return m
