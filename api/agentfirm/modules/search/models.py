from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, uuid_pk


class SearchSettings(Base):
    """Singleton (id = 1). `provider` NULL = use the environment defaults."""

    __tablename__ = "search_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_search_settings_singleton"),
        CheckConstraint("provider IS NULL OR provider IN ('brave','gemini','none')", name="ck_search_settings_provider"),
        CheckConstraint("fallback IS NULL OR fallback IN ('brave','gemini','none')", name="ck_search_settings_fallback"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1, server_default="1")
    provider: Mapped[str | None] = mapped_column(String(16))
    fallback: Mapped[str | None] = mapped_column(String(16))
    gemini_model: Mapped[str] = mapped_column(String(120), default="gemini-3.5-flash-lite", server_default="gemini-3.5-flash-lite")
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchCredential(Base):
    """Envelope-encrypted search API key (Brave). Only `last4` is ever returned by the API."""

    __tablename__ = "search_credentials"
    __table_args__ = (
        CheckConstraint("provider IN ('brave')", name="ck_search_credentials_provider"),
        Index("ix_search_credentials_active", "provider", unique=True, postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(16))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    key_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(32))
    last4: Mapped[str] = mapped_column(String(8))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
