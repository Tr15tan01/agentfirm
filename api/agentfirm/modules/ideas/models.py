from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, CheckConstraint, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk


class Idea(Base):
    __tablename__ = tenant_table("ideas")
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_ideas_org_id_id"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="SET NULL (project_id)"),
        CheckConstraint("board_column IN ('new','shortlisted','developing','parked','rejected')", name="ck_ideas_board_column"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID | None] = mapped_column()
    execution_id: Mapped[UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text)
    approach: Mapped[str] = mapped_column(String(32))
    lens: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(48)), default=list, server_default="{}")
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    board_column: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
