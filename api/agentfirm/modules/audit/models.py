from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Identity, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table


class AuditLog(Base):
    """Append-only. The application role has no UPDATE/DELETE grant and a trigger
    rejects modifications even for roles that do. org_id NULL = platform action."""

    __tablename__ = tenant_table("audit_logs")

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # No FKs: audit history must survive deletion of the organisation or user it mentions.
    org_id: Mapped[UUID | None] = mapped_column(index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(48))
    target_id: Mapped[str | None] = mapped_column(String(80))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
