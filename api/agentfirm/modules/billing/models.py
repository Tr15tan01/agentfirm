from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk


class UsageRecord(Base):
    """Append-only metering row; records the model ACTUALLY used (including fallbacks)."""

    __tablename__ = tenant_table("usage_records")

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID | None] = mapped_column()
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    agent_key: Mapped[str] = mapped_column(String(48))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    capability: Mapped[str] = mapped_column(String(32))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    created_at: Mapped[datetime] = created_at()


# ── Phase 6: plans, credits and billing ─────────────────────────────────────


class Plan(Base):
    """Platform plan catalogue (super-admin managed)."""

    __tablename__ = "plans"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    monthly_credits: Mapped[int] = mapped_column(Integer)
    max_seats: Mapped[int] = mapped_column(Integer)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer)
    agents: Mapped[list[str] | None] = mapped_column(JSONB)  # None = every agent
    price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    paddle_price_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = created_at()


class CreditPack(Base):
    __tablename__ = "credit_packs"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    credits: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    paddle_price_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = created_at()


class Subscription(Base):
    __tablename__ = tenant_table("subscriptions")

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    plan_key: Mapped[str] = mapped_column(ForeignKey("plans.key"))
    status: Mapped[str] = mapped_column(String(16), default="active")
    provider: Mapped[str] = mapped_column(String(16), default="none")
    provider_customer_id: Mapped[str | None] = mapped_column(String(64))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = created_at()


class CreditBalance(Base):
    __tablename__ = tenant_table("credit_balances")

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    plan_remaining: Mapped[int] = mapped_column(Integer)
    purchased_remaining: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = created_at()


class CreditLedgerEntry(Base):
    """Append-only (UPDATE/DELETE revoked from the app role)."""

    __tablename__ = tenant_table("credit_ledger")

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    bucket: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(24))
    reference: Mapped[str | None] = mapped_column(String(160), unique=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class Invoice(Base):
    __tablename__ = tenant_table("invoices")

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    number: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(16))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(Text, default="")
    billed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(64))
    subject_org_id: Mapped[UUID | None] = mapped_column()  # platform log: no RLS (see migration 0008)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = created_at()
