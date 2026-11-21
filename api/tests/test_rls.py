"""Database-level isolation: even a query with NO tenant filter cannot see or write
another organisation's rows when running as the application role."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from .conftest import register


async def _in_org(conn: asyncpg.Connection, org: str | None, sql: str, *args):
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.org_id', $1, true)", org or "")
        return await conn.fetch(sql, *args)


async def test_unfiltered_select_is_scoped(client, app_db):
    a = await register(client, org="RLS A", name="Ra")
    b = await register(client, org="RLS B", name="Rb")
    await client.post("/v1/projects", headers=a.h, json={"name": "A-only"})
    await client.post("/v1/projects", headers=b.h, json={"name": "B-only"})

    rows_a = await _in_org(app_db, a.org_id, "SELECT name, org_id FROM projects")  # no WHERE clause
    assert {r["org_id"] for r in rows_a} == {uuid.UUID(a.org_id)}
    assert "B-only" not in {r["name"] for r in rows_a}


async def test_no_context_sees_nothing(client, app_db):
    a = await register(client, org="RLS C", name="Rc")
    await client.post("/v1/tasks", headers=a.h, json={"objective": "hidden", "agents": ["research"]})
    for table in ("tasks", "task_executions", "projects", "conversations", "memberships", "organizations", "audit_logs"):
        assert await _in_org(app_db, None, f"SELECT 1 FROM {table}") == [], table


async def test_cannot_insert_into_other_org(client, app_db):
    a = await register(client, org="RLS D", name="Rd")
    b = await register(client, org="RLS E", name="Re")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _in_org(
            app_db,
            a.org_id,
            "INSERT INTO projects (id, org_id, name, created_by) VALUES (gen_random_uuid(), $1, 'planted', $2)",
            uuid.UUID(b.org_id),
            uuid.UUID(a.user_id),
        )


async def test_composite_fk_blocks_cross_org_reference(client, owner_db):
    """Even the schema owner (no RLS) cannot link a task to another org's project."""
    a = await register(client, org="FK A", name="Fa")
    b = await register(client, org="FK B", name="Fb")
    proj_b = (await client.post("/v1/projects", headers=b.h, json={"name": "B project"})).json()
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await owner_db.execute(
            "INSERT INTO tasks (id, org_id, project_id, title, objective, created_by) VALUES (gen_random_uuid(), $1, $2, 't', 'o', $3)",
            uuid.UUID(a.org_id),
            uuid.UUID(proj_b["id"]),
            uuid.UUID(a.user_id),
        )


async def test_app_role_cannot_bypass_rls(database):
    from agentfirm.core.db import assert_safe_db_role, get_engine

    await assert_safe_db_role(get_engine())  # would raise for superuser / BYPASSRLS / owner


async def test_every_org_scoped_table_has_rls(owner_db):
    """Self-maintaining: a new table with an org_id column fails CI until it has RLS."""
    rows = await owner_db.fetch(
        "SELECT c.relname, c.relrowsecurity, EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname) AS has_policy "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'org_id' AND NOT a.attisdropped)"
    )
    tables = {r["relname"] for r in rows}
    assert {"step_results", "tool_executions", "ideas", "memories", "knowledge_documents", "knowledge_chunks"} <= tables
    # auth_sessions belongs to a USER; its org_id is only the "selected organisation" pointer and is
    # read during token verification before any org context exists. Access is by session id + user.
    exempt = {"auth_sessions"}
    unprotected = [r["relname"] for r in rows if r["relname"] not in exempt and not (r["relrowsecurity"] and r["has_policy"])]
    assert not unprotected, f"org-scoped tables without RLS: {unprotected}"


async def test_runtime_tables_hidden_without_context(client, app_db):
    a = await register(client, org="RLS F", name="Rf")
    await client.post("/v1/knowledge/documents", headers=a.h, json={"title": "t", "content": "private words"})
    for table in ("knowledge_documents", "knowledge_chunks", "ideas", "memories", "tool_executions", "step_results"):
        assert await _in_org(app_db, None, f"SELECT 1 FROM {table}") == [], table
    assert len(await _in_org(app_db, a.org_id, "SELECT 1 FROM knowledge_chunks")) == 1
