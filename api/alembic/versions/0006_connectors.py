"""Connectors and agent-owned workspace data: organisation connections (sealed secrets),
content calendar, email drafts, report schedules.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("AGENTFIRM_DB_APP_ROLE", "agentfirm_app")
TABLES = ["connections", "content_calendar_entries", "email_drafts", "report_schedules"]


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False),  # github | webhook | smtp | gn7t
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("config", pg.JSONB, server_default="{}", nullable=False),  # non-secret settings only
        sa.Column("ciphertext", sa.LargeBinary),
        sa.Column("nonce", sa.LargeBinary),
        sa.Column("wrapped_key", sa.LargeBinary),
        sa.Column("key_nonce", sa.LargeBinary),
        sa.Column("key_id", sa.String(32)),
        sa.Column("secret_last4", sa.String(8)),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
        _ts(),
        _ts("updated_at"),
        sa.UniqueConstraint("org_id", "id", name="uq_connections_org_id"),
        sa.CheckConstraint("kind IN ('github', 'webhook', 'smtp', 'gn7t')", name="ck_connections_kind"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_connections_status"),
    )
    op.create_table(
        "content_calendar_entries",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("execution_id", sa.Uuid),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("language", sa.String(16)),
        sa.Column("scheduled_for", sa.Date),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        _ts(),
        sa.CheckConstraint("status IN ('draft', 'approved', 'published', 'archived')", name="ck_calendar_status"),
    )
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("execution_id", sa.Uuid),
        sa.Column("to_addresses", pg.JSONB, server_default="[]", nullable=False),
        sa.Column("cc_addresses", pg.JSONB, server_default="[]", nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
        _ts(),
        sa.CheckConstraint("status IN ('draft', 'sent', 'discarded')", name="ck_email_status"),
    )
    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("agent_key", sa.String(48), nullable=False),
        sa.Column("objective", sa.Text, nullable=False),
        sa.Column("parameters", pg.JSONB, server_default="{}", nullable=False),
        sa.Column("cadence", sa.String(40), nullable=False),  # daily@08:00 | weekly:mon@08:00 | monthly:1@08:00
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
        _ts(),
    )
    op.create_index("ix_report_schedules_due", "report_schedules", ["active", "next_run_at"])

    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (org_id = app_current_org() OR app_is_platform_admin()) "
            f"WITH CHECK (org_id = app_current_org())"
        )

    # Workers find due schedules across organisations through this narrow function only.
    op.execute(
        "CREATE FUNCTION due_report_schedules(p_limit int) RETURNS TABLE (id uuid, org_id uuid) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ "
        "SELECT s.id, s.org_id FROM report_schedules s WHERE s.active AND s.next_run_at <= now() "
        "ORDER BY s.next_run_at LIMIT p_limit $$"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION due_report_schedules(int) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS due_report_schedules(int)")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
