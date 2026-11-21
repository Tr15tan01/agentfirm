from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk


class Conversation(Base):
    __tablename__ = tenant_table("conversations")
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        # Composite FK: a conversation can only reference a project in the SAME organisation.
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="SET NULL (project_id)"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"))
    project_id: Mapped[UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = tenant_table("messages")
    __table_args__ = (
        ForeignKeyConstraint(["org_id", "conversation_id"], ["conversations.org_id", "conversations.id"], ondelete="CASCADE"),
        CheckConstraint("role IN ('user','assistant')", name="role"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    execution_id: Mapped[UUID | None] = mapped_column()
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
