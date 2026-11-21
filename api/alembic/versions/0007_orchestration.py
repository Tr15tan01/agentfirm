"""Orchestration: an orchestrator execution plans subtasks (child executions) across agents.

* `kind` = agent | orchestrator. An orchestrator execution has no agent version.
* Subtasks carry their own objective, parameters, upstream context (handoffs), dependencies,
  delegation depth and origin (orchestrator, or the agent whose handoff created them).
* New statuses: `blocked` (a subtask waiting for its dependencies), `waiting_subtasks` (the
  orchestrator, idle until a subtask finishes) and `skipped` (a dependency failed).
* Subtasks are claimable by workers; blocked ones are not.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

OLD = ("queued", "running", "waiting_approval", "paused", "completed", "failed", "cancelled")
NEW = (*OLD, "blocked", "waiting_subtasks", "skipped")


def _status_check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("task_executions", sa.Column("kind", sa.String(16), server_default="agent", nullable=False))
    op.add_column("task_executions", sa.Column("subtask_key", sa.String(48)))
    op.add_column("task_executions", sa.Column("objective", sa.Text))
    op.add_column("task_executions", sa.Column("parameters", pg.JSONB))
    op.add_column("task_executions", sa.Column("context", pg.JSONB))
    op.add_column("task_executions", sa.Column("depends_on", pg.JSONB, server_default="[]", nullable=False))
    op.add_column("task_executions", sa.Column("delegation_depth", sa.SmallInteger, server_default="0", nullable=False))
    op.add_column("task_executions", sa.Column("origin", sa.String(48)))
    op.alter_column("task_executions", "agent_version_id", nullable=True)
    op.create_check_constraint("kind", "task_executions", "kind IN ('agent', 'orchestrator')")
    op.create_check_constraint("agent_version", "task_executions", "kind = 'orchestrator' OR agent_version_id IS NOT NULL")
    op.create_check_constraint("delegation_depth", "task_executions", "delegation_depth BETWEEN 0 AND 2")
    op.execute("ALTER TABLE task_executions DROP CONSTRAINT ck_task_executions_status")
    op.create_check_constraint("status", "task_executions", _status_check(NEW))
    op.create_index(
        "uq_task_executions_subtask",
        "task_executions",
        ["parent_execution_id", "subtask_key"],
        unique=True,
        postgresql_where=sa.text("subtask_key IS NOT NULL"),
    )
    op.create_index("ix_task_executions_parent", "task_executions", ["parent_execution_id"])

    # Children are now claimable too (blocked / waiting_subtasks are not in the status list).
    op.execute(
        "CREATE OR REPLACE FUNCTION claimable_executions(p_limit int) RETURNS TABLE (id uuid, org_id uuid) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ "
        "SELECT e.id, e.org_id FROM task_executions e "
        "WHERE e.status IN ('queued', 'running') AND (e.lease_expires_at IS NULL OR e.lease_expires_at < now()) "
        "ORDER BY e.queued_at LIMIT p_limit $$"
    )


def downgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION claimable_executions(p_limit int) RETURNS TABLE (id uuid, org_id uuid) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ "
        "SELECT e.id, e.org_id FROM task_executions e "
        "WHERE e.status IN ('queued', 'running') AND (e.lease_expires_at IS NULL OR e.lease_expires_at < now()) "
        "  AND e.parent_execution_id IS NULL "
        "ORDER BY e.queued_at LIMIT p_limit $$"
    )
    op.execute("DELETE FROM task_executions WHERE kind = 'orchestrator' OR parent_execution_id IS NOT NULL")
    op.drop_index("ix_task_executions_parent", table_name="task_executions")
    op.drop_index("uq_task_executions_subtask", table_name="task_executions")
    op.execute("ALTER TABLE task_executions DROP CONSTRAINT ck_task_executions_status")
    op.create_check_constraint("status", "task_executions", _status_check(OLD))
    for name in ("delegation_depth", "agent_version", "kind"):
        op.execute(f"ALTER TABLE task_executions DROP CONSTRAINT ck_task_executions_{name}")
    op.alter_column("task_executions", "agent_version_id", nullable=False)
    for col in ("origin", "delegation_depth", "depends_on", "context", "parameters", "objective", "subtask_key", "kind"):
        op.drop_column("task_executions", col)
