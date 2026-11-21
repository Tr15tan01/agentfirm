"""Row-level security, least-privilege grants, append-only guarantees, RBAC seed.

Revision ID: 0002
Revises: 0001

Tenant isolation is enforced in three layers:
  1. Application: every repository call requires a TenantContext.
  2. Schema: composite (org_id, id) foreign keys — cross-org references are impossible.
  3. PostgreSQL RLS (this migration): rows are filtered by `app.org_id`, set per
     transaction. The API connects as a NON-owner role, so policies always apply.
"""

from __future__ import annotations

import os

import sqlalchemy as sa

from agentfirm.core.permissions import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS, ROLE_RANK, Perm
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("AGENTFIRM_DB_APP_ROLE", "agentfirm_app")

# Tables with the plain "row belongs to the current organisation" policy.
SIMPLE_TENANT = [
    "org_agent_settings",
    "invitations",
    "projects",
    "conversations",
    "messages",
    "tasks",
    "task_executions",
    "execution_events",
    "approval_requests",
    "artifacts",
    "usage_records",
]
APPEND_ONLY = ["audit_logs", "usage_records", "execution_events"]


def upgrade() -> None:
    op.execute("CREATE FUNCTION app_current_org() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$")
    op.execute("CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$")
    op.execute(
        "CREATE FUNCTION app_is_platform_admin() RETURNS boolean LANGUAGE sql STABLE AS "
        "$$ SELECT coalesce(current_setting('app.platform_admin', true), 'off') = 'on' $$"
    )

    for t in SIMPLE_TENANT:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (org_id = app_current_org() OR app_is_platform_admin()) WITH CHECK (org_id = app_current_org())"
        )

    # Organisations: your current org, any org you belong to (workspace switcher), or platform admin.
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON organizations USING ("
        " id = app_current_org()"
        " OR id IN (SELECT m.org_id FROM memberships m WHERE m.user_id = app_current_user())"
        " OR app_is_platform_admin()) WITH CHECK (id = app_current_org())"
    )

    # Memberships: rows of the current org, or your own memberships across orgs.
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON memberships USING ("
        " org_id = app_current_org() OR user_id = app_current_user() OR app_is_platform_admin())"
        " WITH CHECK (org_id = app_current_org())"
    )

    # Audit log: org entries for that org; platform entries (org_id NULL) for platform admins only.
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_logs USING (org_id = app_current_org() OR app_is_platform_admin())"
        " WITH CHECK (org_id = app_current_org() OR (org_id IS NULL AND app_is_platform_admin()))"
    )

    # Invitation acceptance happens before the invitee belongs to the org. This narrow
    # SECURITY DEFINER function (runs as owner → RLS not applied) only maps a token hash to
    # its org id; everything else then runs inside that org's context.
    op.execute(
        """
        CREATE FUNCTION invitation_org(p_token_hash text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
          $$ SELECT org_id FROM invitations
             WHERE token_hash = p_token_hash AND accepted_at IS NULL AND expires_at > now() $$;
        """
    )

    # Workspace URLs are globally unique, but RLS hides other orgs' rows from the app role.
    # This function answers only "is this slug taken?" without exposing any other data.
    op.execute(
        "CREATE FUNCTION org_slug_taken(p_slug text) RETURNS boolean "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS "
        "$$ SELECT EXISTS (SELECT 1 FROM organizations WHERE slug = p_slug) $$"
    )

    # Platform-level audit entries (org_id NULL) written by non-admin flows such as sign-in.
    # SECURITY DEFINER so the insert does not require elevating the caller's RLS context.
    op.execute(
        "CREATE FUNCTION log_platform_audit(p_action text, p_target_type text, p_target_id text, p_actor uuid, p_ip text, p_after jsonb) "
        "RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS "
        "$$ INSERT INTO audit_logs (org_id, actor_user_id, action, target_type, target_id, after, ip) "
        "VALUES (NULL, p_actor, p_action, p_target_type, p_target_id, p_after, p_ip) $$"
    )

    # Append-only enforcement (belt and braces on top of revoked grants).
    op.execute(
        """
        CREATE FUNCTION forbid_modification() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME USING ERRCODE = '42501'; END $$;
        """
    )
    op.execute("CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION forbid_modification()")

    # Least-privilege grants for the application role.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    for t in APPEND_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM {APP_ROLE}")
    for t in ("roles", "permissions", "role_permissions"):
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {t} FROM {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION invitation_org(text) TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION org_slug_taken(text) TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION log_platform_audit(text, text, text, uuid, text, jsonb) TO {APP_ROLE}")

    # RBAC seed — mirrors agentfirm.core.permissions (a test keeps them identical).
    roles = sa.table("roles", sa.column("key"), sa.column("description"), sa.column("rank"))
    perms = sa.table("permissions", sa.column("key"))
    rp = sa.table("role_permissions", sa.column("role"), sa.column("permission"))
    op.bulk_insert(roles, [{"key": r.value, "description": ROLE_DESCRIPTIONS[r], "rank": ROLE_RANK[r]} for r in ROLE_PERMISSIONS])
    op.bulk_insert(perms, [{"key": p.value} for p in Perm])
    op.bulk_insert(rp, [{"role": r.value, "permission": p.value} for r, ps in ROLE_PERMISSIONS.items() for p in sorted(ps)])


def downgrade() -> None:
    for t in ("role_permissions", "permissions", "roles"):
        op.execute(f"DELETE FROM {t}")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS forbid_modification()")
    op.execute("DROP FUNCTION IF EXISTS invitation_org(text)")
    op.execute("DROP FUNCTION IF EXISTS org_slug_taken(text)")
    op.execute("DROP FUNCTION IF EXISTS log_platform_audit(text, text, text, uuid, text, jsonb)")
    for t in [*SIMPLE_TENANT, "organizations", "memberships", "audit_logs"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    for fn in ("app_is_platform_admin", "app_current_user", "app_current_org"):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")
