"""Organisation connections and agent-owned workspace records (migration 0006)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk


class Connection(Base):
    """A connected external system. `config` holds non-secret settings; the secret (token,
    password, signing key) is envelope-encrypted and only `secret_last4` is ever returned."""

    __tablename__ = tenant_table("connections")

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_id: Mapped[str | None] = mapped_column(String(32))
    secret_last4: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContentCalendarEntry(Base):
    __tablename__ = tenant_table("content_calendar_entries")

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID | None] = mapped_column()
    channel: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    scheduled_for: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = created_at()


class EmailDraft(Base):
    __tablename__ = tenant_table("email_drafts")

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID | None] = mapped_column()
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class ReportSchedule(Base):
    __tablename__ = tenant_table("report_schedules")

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    agent_key: Mapped[str] = mapped_column(String(48))
    objective: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cadence: Mapped[str] = mapped_column(String(40))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
