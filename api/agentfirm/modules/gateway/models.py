from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, uuid_pk

CAPABILITIES = ("reasoning", "text", "code", "summarize", "classify", "creative", "vision", "long_context", "embeddings")


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id: Mapped[UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(32), unique=True)  # openai | gemini | gn7t
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(String(400))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at()


class ProviderCredential(Base):
    """Envelope-encrypted API key. Only `last4` is ever returned by the API."""

    __tablename__ = "provider_credentials"

    id: Mapped[UUID] = uuid_pk()
    provider_id: Mapped[UUID] = mapped_column(ForeignKey("model_providers.id", ondelete="CASCADE"), index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    key_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(String(32))
    last4: Mapped[str] = mapped_column(String(8))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Model(Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("provider_id", "name"),)

    id: Mapped[UUID] = uuid_pk()
    provider_id: Mapped[UUID] = mapped_column(ForeignKey("model_providers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(120))
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    price_in_per_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    price_out_per_1m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at()


class ModelRoute(Base):
    """priority 0 = primary, 1.. = ordered fallbacks. Scope resolution order:
    agent_version → org → platform (see docs/ARCHITECTURE.md §5.1)."""

    __tablename__ = "model_routes"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "capability", "priority", postgresql_nulls_not_distinct=True),
        CheckConstraint("scope IN ('platform','org','agent_version')", name="scope"),
        CheckConstraint("(scope = 'platform') = (scope_id IS NULL)", name="scope_id"),
        CheckConstraint(f"capability IN {CAPABILITIES}", name="capability"),
        CheckConstraint("priority >= 0 AND priority <= 3", name="priority"),
    )

    id: Mapped[UUID] = uuid_pk()
    scope: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[UUID | None] = mapped_column()
    capability: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer)
    model_id: Mapped[UUID] = mapped_column(ForeignKey("models.id", ondelete="RESTRICT"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = created_at()
