"""Ops metrics (Phase 7): aggregate execution counts for Prometheus, across organisations,
through one narrow SECURITY DEFINER function that returns counts only (no tenant data).

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import os

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("AGENTFIRM_DB_APP_ROLE", "agentfirm_app")


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION ops_execution_counts() RETURNS TABLE (status text, n bigint, oldest_seconds double precision) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ "
        "SELECT e.status::text, count(*), max(extract(epoch FROM now() - e.queued_at)) "
        "FROM task_executions e WHERE e.status NOT IN ('completed', 'failed', 'cancelled', 'skipped') GROUP BY e.status $$"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION ops_execution_counts() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS ops_execution_counts()")
