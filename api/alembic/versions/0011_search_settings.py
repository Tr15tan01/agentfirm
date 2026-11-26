"""Web search settings: which provider the research tools use, chosen by a super-admin.

Revision ID: 0011
Revises: 0010

One settings row (id = 1) plus an envelope-encrypted Brave key. `provider` NULL means "use the
AGENTFIRM_SEARCH_PROVIDER / AGENTFIRM_BRAVE_API_KEY environment defaults", so existing installs
keep working until an admin changes something. Gemini grounding re-uses the Gemini provider key.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

APP_ROLE = "agentfirm_app"


def upgrade() -> None:
    op.create_table(
        "search_settings",
        sa.Column("id", sa.SmallInteger, primary_key=True, server_default="1"),
        sa.Column("provider", sa.String(16)),
        sa.Column("fallback", sa.String(16)),
        sa.Column("gemini_model", sa.String(120), nullable=False, server_default="gemini-3.5-flash-lite"),
        sa.Column("updated_by", sa.Uuid, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_search_settings_singleton"),
        sa.CheckConstraint("provider IS NULL OR provider IN ('brave','gemini','none')", name="ck_search_settings_provider"),
        sa.CheckConstraint("fallback IS NULL OR fallback IN ('brave','gemini','none')", name="ck_search_settings_fallback"),
    )
    op.create_table(
        "search_credentials",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary, nullable=False),
        sa.Column("key_nonce", sa.LargeBinary, nullable=False),
        sa.Column("key_id", sa.String(32), nullable=False),
        sa.Column("last4", sa.String(8), nullable=False),
        sa.Column("created_by", sa.Uuid, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("provider IN ('brave')", name="ck_search_credentials_provider"),
    )
    op.create_index("ix_search_credentials_active", "search_credentials", ["provider"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.execute("INSERT INTO search_settings (id) VALUES (1)")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON search_settings, search_credentials TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("search_credentials")
    op.drop_table("search_settings")
