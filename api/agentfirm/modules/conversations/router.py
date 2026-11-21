from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.permissions import Perm

from . import service
from .service import ConversationIn, ConversationOut, MessageIn, MessageOut

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    session: DbSession, agent: str | None = Query(default=None, max_length=48), principal: Principal = require(Perm.WORKSPACE_READ)
) -> list[ConversationOut]:
    return await service.list_conversations(session, principal, agent)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: ConversationIn, session: DbSession, principal: Principal = require(Perm.AGENTS_USE)) -> ConversationOut:
    return await service.create_conversation(session, principal, body)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: UUID, session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)):  # type: ignore[no-untyped-def]
    return await service.list_messages(session, principal, conversation_id)


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
async def post_message(conversation_id: UUID, body: MessageIn, session: DbSession, principal: Principal = require(Perm.AGENTS_USE)):  # type: ignore[no-untyped-def]
    return await service.post_message(session, principal, conversation_id, body)
