"""Agent version integrity: one current version per agent; published versions immutable.

Revision ID: 0004
Revises: 0003

Executions pin agent_version_id, so a published manifest must never change — otherwise
past runs would no longer be traceable to the configuration that produced them (brief §21.9).
Rollback = moving the `is_current` flag, which this migration still allows.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_agent_versions_one_current ON agent_versions (agent_id) WHERE is_current")
    op.execute(
        "CREATE FUNCTION forbid_agent_version_rewrite() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "  IF OLD.published_at IS NOT NULL AND ("
        "     NEW.manifest IS DISTINCT FROM OLD.manifest OR NEW.version IS DISTINCT FROM OLD.version"
        "     OR NEW.agent_id IS DISTINCT FROM OLD.agent_id OR NEW.published_at IS DISTINCT FROM OLD.published_at) THEN "
        "    RAISE EXCEPTION 'published agent versions are immutable (publish a new version instead)' USING ERRCODE = '42501'; "
        "  END IF; "
        "  IF TG_OP = 'DELETE' AND OLD.published_at IS NOT NULL THEN "
        "    RAISE EXCEPTION 'published agent versions cannot be deleted' USING ERRCODE = '42501'; "
        "  END IF; "
        "  RETURN COALESCE(NEW, OLD); "
        "END $$"
    )
    op.execute("CREATE TRIGGER agent_versions_immutable BEFORE UPDATE OR DELETE ON agent_versions FOR EACH ROW EXECUTE FUNCTION forbid_agent_version_rewrite()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agent_versions_immutable ON agent_versions")
    op.execute("DROP FUNCTION IF EXISTS forbid_agent_version_rewrite()")
    op.execute("DROP INDEX IF EXISTS uq_agent_versions_one_current")
