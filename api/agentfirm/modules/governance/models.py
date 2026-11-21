from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk


class StandingApproval(Base):
    """A pre-approval for a recurring gated action, limited by conditions, uses and expiry (ADR 0006)."""

    __tablename__ = tenant_table("standing_approvals")

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(80))
    agent_key: Mapped[str | None] = mapped_column(String(48))
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    note: Mapped[str] = mapped_column(Text)
    max_uses: Mapped[int] = mapped_column(Integer)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class ToolOverride(Base):
    """Platform kill-switch for a tool (super-admin)."""

    __tablename__ = "tool_overrides"

    tool: Mapped[str] = mapped_column(String(80), primary_key=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = created_at()
