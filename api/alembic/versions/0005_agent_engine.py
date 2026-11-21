"""Agent Engine storage: execution leases, idempotent tool executions, idea board,
named memories, knowledge documents (full-text search) and LangGraph checkpoints.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("AGENTFIRM_DB_APP_ROLE", "agentfirm_app")
NEW_TENANT_TABLES = ["tool_executions", "step_results", "ideas", "memories", "knowledge_documents", "knowledge_chunks"]


def _tenant_fk(child_cols: list[str], parent: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["org_id", *child_cols], [f"{parent}.org_id", f"{parent}.id"], ondelete=ondelete)


def upgrade() -> None:
    # ── Execution leases (at-least-once workers; crash → lease expiry → resume) ──
    op.add_column("task_executions", sa.Column("lease_owner", sa.String(64)))
    op.add_column("task_executions", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("task_executions", sa.Column("attempts", sa.Integer, server_default="0", nullable=False))
    op.add_column("task_executions", sa.Column("budget_credits", sa.Integer))
    op.add_column("task_executions", sa.Column("credits_used", sa.Integer, server_default="0", nullable=False))
    op.add_column("task_executions", sa.Column("result", pg.JSONB))
    op.add_column("tasks", sa.Column("parameters", pg.JSONB, server_default="{}", nullable=False))
    op.create_index("ix_task_executions_claimable", "task_executions", ["status", "lease_expires_at"])

    # Workers discover work across organisations through this narrow function only; they
    # then switch into the execution's org context for every read/write (RLS applies).
    op.execute(
        "CREATE FUNCTION claimable_executions(p_limit int) RETURNS TABLE (id uuid, org_id uuid) "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$ "
        "SELECT e.id, e.org_id FROM task_executions e "
        "WHERE e.status IN ('queued', 'running') AND (e.lease_expires_at IS NULL OR e.lease_expires_at < now()) "
        "  AND e.parent_execution_id IS NULL "
        "ORDER BY e.queued_at LIMIT p_limit $$"
    )

    # ── Tool executions (idempotency for side effects across resumes) ─────────
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("execution_id", sa.Uuid, nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("side_effect", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_summary", sa.String(500)),
        sa.Column("output", pg.JSONB),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        _tenant_fk(["execution_id"], "task_executions"),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_tool_executions_idempotency"),
        sa.CheckConstraint("status IN ('ok','error','timeout','blocked')", name="ck_tool_executions_status"),
    )

    # ── Step results: written in the SAME transaction as step.completed, so a step whose
    #    completion was recorded is restored, never re-run, even if the worker died before
    #    LangGraph persisted its checkpoint. ─────────────────────────────────────────────
    op.create_table(
        "step_results",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("execution_id", sa.Uuid, nullable=False),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("output", pg.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        _tenant_fk(["execution_id"], "task_executions"),
        sa.UniqueConstraint("execution_id", "step", name="uq_step_results_execution_step"),
    )

    # ── Idea board (Creative agent + UI) ──────────────────────────────────────
    op.create_table(
        "ideas",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("project_id", sa.Uuid),
        sa.Column("execution_id", sa.Uuid),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("approach", sa.String(32), nullable=False),
        sa.Column("lens", sa.String(64)),
        sa.Column("tags", pg.ARRAY(sa.String(48)), server_default="{}", nullable=False),
        sa.Column("scores", pg.JSONB),
        sa.Column("board_column", sa.String(16), server_default="new", nullable=False),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_ideas_org_id_id"),
        _tenant_fk(["project_id"], "projects", "SET NULL (project_id)"),
        sa.CheckConstraint("board_column IN ('new','shortlisted','developing','parked','rejected')", name="ck_ideas_board_column"),
    )

    # ── Named memories (Memory Service: brand_voice, rejected_ideas, …) ───────
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("project_id", sa.Uuid),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_by", sa.Uuid, sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        _tenant_fk(["project_id"], "projects", "CASCADE"),
    )
    op.execute("CREATE UNIQUE INDEX uq_memories_scope_key ON memories (org_id, coalesce(project_id, '00000000-0000-0000-0000-000000000000'::uuid), key)")

    # ── Knowledge (full-text search now; pgvector embeddings added when the extension is present) ──
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("project_id", sa.Uuid),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("mime", sa.String(100)),
        sa.Column("chars", sa.Integer, nullable=False),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_knowledge_documents_org_id_id"),
        _tenant_fk(["project_id"], "projects", "SET NULL (project_id)"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("org_id", sa.Uuid, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", sa.Uuid, nullable=False, index=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("locator", sa.String(64)),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tsv", pg.TSVECTOR, sa.Computed("to_tsvector('simple', content)", persisted=True)),
        _tenant_fk(["document_id"], "knowledge_documents"),
    )
    op.execute("CREATE INDEX ix_knowledge_chunks_tsv ON knowledge_chunks USING gin (tsv)")

    for t in NEW_TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (org_id = app_current_org() OR app_is_platform_admin()) "
            f"WITH CHECK (org_id = app_current_org())"
        )

    # ── LangGraph checkpoints (worker-internal; thread_id = execution id) ─────
    for sql in BasePostgresSaver.MIGRATIONS:
        op.execute(sql.replace("CONCURRENTLY ", ""))  # tables are new and empty: plain DDL inside the transaction
    op.execute(
        sa.text("INSERT INTO checkpoint_migrations (v) SELECT generate_series(0, :n) ON CONFLICT DO NOTHING").bindparams(n=len(BasePostgresSaver.MIGRATIONS) - 1)
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    for t in ("audit_logs", "usage_records", "execution_events"):
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM {APP_ROLE}")
    for t in ("roles", "permissions", "role_permissions"):
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {t} FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON checkpoint_migrations FROM {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION claimable_executions(int) TO {APP_ROLE}")


def downgrade() -> None:
    for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    for t in reversed(NEW_TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("DROP FUNCTION IF EXISTS claimable_executions(int)")
    op.drop_index("ix_task_executions_claimable", table_name="task_executions")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS parameters")
    for c in ("result", "credits_used", "budget_credits", "attempts", "lease_expires_at", "lease_owner"):
        op.drop_column("task_executions", c)
