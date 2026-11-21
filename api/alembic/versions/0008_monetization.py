"""Monetization and platform admin (Phase 6).

Platform tables (no org_id; written only through super-admin endpoints or verified webhooks):
  plans, credit_packs, billing_events, tool_overrides.
Tenant tables (RLS): subscriptions, credit_balances, credit_ledger, invoices, standing_approvals.

Every existing organisation is backfilled onto the free plan with a fresh monthly allowance.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("AGENTFIRM_DB_APP_ROLE", "agentfirm_app")
TENANT = ("subscriptions", "credit_balances", "credit_ledger", "invoices", "standing_approvals")
PLATFORM = ("plans", "credit_packs", "billing_events", "tool_overrides")


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("monthly_credits", sa.Integer, nullable=False),
        sa.Column("max_seats", sa.Integer, nullable=False),
        sa.Column("max_concurrent_tasks", sa.Integer, nullable=False),
        sa.Column("agents", pg.JSONB),  # null = every agent
        sa.Column("price_cents", sa.Integer),  # null = not for sale yet (set by a super-admin)
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("paddle_price_id", sa.String(64), unique=True),
        sa.Column("is_public", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("sort", sa.Integer, server_default="0", nullable=False),
        _ts("updated_at"),
        sa.CheckConstraint("monthly_credits >= 0 AND max_seats >= 1 AND max_concurrent_tasks >= 1", name="ck_plans_limits"),
        sa.CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="ck_plans_price"),
    )
    op.create_table(
        "credit_packs",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("credits", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.Integer),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("paddle_price_id", sa.String(64), unique=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        _ts("updated_at"),
        sa.CheckConstraint("credits > 0", name="ck_credit_packs_credits"),
    )
    op.create_table(
        # Verified provider webhooks, stored once (idempotency) with their outcome. A platform log,
        # not tenant data: it is written before the organisation is known, never read by tenants
        # (only the webhook handler and super-admins), so it has no RLS and no org_id column.
        "billing_events",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("subject_org_id", sa.Uuid),
        sa.Column("payload", pg.JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        _ts("received_at"),
    )
    op.create_table(
        "tool_overrides",  # platform kill-switch per tool
        sa.Column("tool", sa.String(80), primary_key=True),
        sa.Column("disabled", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("updated_by", sa.Uuid, sa.ForeignKey("users.id")),
        _ts("updated_at"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan_key", sa.String(32), sa.ForeignKey("plans.key"), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("provider", sa.String(16), server_default="none", nullable=False),
        sa.Column("provider_customer_id", sa.String(64)),
        sa.Column("provider_subscription_id", sa.String(64), unique=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean, server_default=sa.false(), nullable=False),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('active', 'trialing', 'past_due', 'paused', 'canceled')", name="ck_subscriptions_status"),
        sa.CheckConstraint("provider IN ('none', 'paddle', 'manual')", name="ck_subscriptions_provider"),
    )
    op.create_table(
        "credit_balances",
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan_remaining", sa.Integer, nullable=False),  # this period's allowance; resets, never rolls over
        sa.Column("purchased_remaining", sa.Integer, server_default="0", nullable=False),  # top-ups and grants; kept
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        _ts("updated_at"),
        sa.CheckConstraint("plan_remaining >= 0", name="ck_credit_balances_plan"),
    )
    op.create_table(
        "credit_ledger",  # append-only record of every grant and adjustment
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("reference", sa.String(160), unique=True),  # idempotency (e.g. paddle:txn_…, period:<org>:<start>)
        sa.Column("note", sa.Text),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id")),
        _ts(),
        sa.CheckConstraint("bucket IN ('plan', 'purchased')", name="ck_credit_ledger_bucket"),
        sa.CheckConstraint("reason IN ('period_grant', 'top_up', 'admin_grant', 'admin_debit', 'refund')", name="ck_credit_ledger_reason"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_transaction_id", sa.String(64), nullable=False, unique=True),
        sa.Column("number", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("total_cents", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("billed_at", sa.DateTime(timezone=True)),
        _ts(),
    )
    op.create_table(
        "standing_approvals",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("agent_key", sa.String(48)),  # null = any agent granted the tool
        sa.Column("conditions", pg.JSONB, server_default="[]", nullable=False),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("max_uses", sa.Integer, nullable=False),
        sa.Column("uses", sa.Integer, server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.Uuid, sa.ForeignKey("users.id")),
        _ts(),
        sa.CheckConstraint("max_uses BETWEEN 1 AND 1000 AND uses >= 0 AND uses <= max_uses", name="ck_standing_approvals_uses"),
    )
    op.add_column("approval_requests", sa.Column("standing_approval_id", sa.Uuid, sa.ForeignKey("standing_approvals.id")))

    for t in TENANT:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (org_id = app_current_org() OR app_is_platform_admin()) WITH CHECK (org_id = app_current_org())")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TENANT)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(PLATFORM)} TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON credit_ledger FROM {APP_ROLE}")  # append-only

    # Default plans. Limits are operational defaults (documented assumption); prices are a business
    # decision, so paid plans start without a price and can't be bought until a super-admin sets one.
    op.execute(
        "INSERT INTO plans (key, name, description, monthly_credits, max_seats, max_concurrent_tasks, price_cents, sort) VALUES "
        "('free', 'Free', 'Try every agent with a small monthly allowance.', 1000, 2, 2, 0, 0), "
        "('pro', 'Pro', 'For small teams running agents every day.', 10000, 10, 5, NULL, 1), "
        "('business', 'Business', 'For teams that automate across departments.', 50000, 50, 20, NULL, 2)"
    )
    op.execute(
        "INSERT INTO subscriptions (org_id, plan_key, current_period_start, current_period_end) "
        "SELECT id, 'free', now(), now() + interval '1 month' FROM organizations"
    )
    op.execute(
        "INSERT INTO credit_balances (org_id, plan_remaining, period_start, period_end) "
        "SELECT id, 1000, now(), now() + interval '1 month' FROM organizations"
    )

    # The worker rolls allowances over across organisations through this narrow function only.
    op.execute(
        "CREATE FUNCTION due_credit_periods(p_limit int) RETURNS TABLE (org_id uuid) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ "
        "SELECT b.org_id FROM credit_balances b WHERE b.period_end <= now() ORDER BY b.period_end LIMIT p_limit $$"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION due_credit_periods(int) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS due_credit_periods(int)")
    op.drop_column("approval_requests", "standing_approval_id")
    for t in (*reversed(TENANT), *reversed(PLATFORM)):
        op.execute(f"DROP TABLE IF EXISTS {t}")
