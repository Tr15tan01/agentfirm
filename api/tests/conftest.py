"""Test harness: a throw-away PostgreSQL database per test session, migrated by the
OWNER role, while the API under test connects as the NON-owner app role — exactly
as in production, so row-level security is genuinely exercised.

Requires a reachable PostgreSQL 16 server. Configure with AGENTFIRM_TEST_ADMIN_DSN
(a role allowed to create databases and roles), default postgres@localhost.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest

ADMIN_DSN = os.environ.get("AGENTFIRM_TEST_ADMIN_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
OWNER, OWNER_PW = "agentfirm_owner", os.environ.get("AGENTFIRM_TEST_OWNER_PW", "owner_dev_pw")
APP, APP_PW = "agentfirm_app", os.environ.get("AGENTFIRM_TEST_APP_PW", "app_dev_pw")
HOST = os.environ.get("AGENTFIRM_TEST_DB_HOST", "localhost:5432")
DB_NAME = f"agentfirm_test_{uuid.uuid4().hex[:8]}"
API_ROOT = Path(__file__).resolve().parents[1]


def _configure_env() -> None:
    keys = tempfile.mkdtemp(prefix="af-keys-")
    os.environ.update(
        {
            "AGENTFIRM_ENV": "test",
            "AGENTFIRM_DATABASE_URL": f"postgresql+asyncpg://{APP}:{APP_PW}@{HOST}/{DB_NAME}",
            "AGENTFIRM_MIGRATIONS_DATABASE_URL": f"postgresql+asyncpg://{OWNER}:{OWNER_PW}@{HOST}/{DB_NAME}",
            "AGENTFIRM_KEYS_DIR": keys,
            "AGENTFIRM_LOGIN_RATE_PER_MINUTE": "1000",
            "AGENTFIRM_REDIS_URL": "",
            "AGENTFIRM_ARTIFACTS_DIR": tempfile.mkdtemp(prefix="af-artifacts-"),
            "AGENTFIRM_GATEWAY_MODE": "simulated",
            "AGENTFIRM_WEB_MODE": "fixture",
        }
    )


_configure_env()


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        for role, pw in ((OWNER, OWNER_PW), (APP, APP_PW)):
            exists = await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            if not exists:
                await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{pw}' NOSUPERUSER NOBYPASSRLS")
        await admin.execute(f'CREATE DATABASE "{DB_NAME}" OWNER {OWNER}')
    finally:
        await admin.close()

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, check=True, env=os.environ.copy(), capture_output=True)  # noqa: ASYNC221 - one-off setup
    # Most tests aren't about plan limits: give the free plan room. Billing tests set their own.
    conn = await asyncpg.connect(f"postgresql://{OWNER}:{OWNER_PW}@{HOST}/{DB_NAME}")
    try:
        await conn.execute("UPDATE plans SET monthly_credits = 10000000, max_seats = 100, max_concurrent_tasks = 100 WHERE key = 'free'")
    finally:
        await conn.close()

    from agentfirm.core.config import get_settings

    get_settings.cache_clear()
    yield

    from agentfirm.core.db import dispose_engine

    await dispose_engine()
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
async def owner_db(database: None) -> AsyncIterator[asyncpg.Connection]:
    """Schema-owner connection (RLS not applied) for arranging fixtures the API can't create yet."""
    conn = await asyncpg.connect(f"postgresql://{OWNER}:{OWNER_PW}@{HOST}/{DB_NAME}")
    yield conn
    await conn.close()


@pytest.fixture(scope="session")
async def app_db(database: None) -> AsyncIterator[asyncpg.Connection]:
    """Connection as the application role — the one subject to RLS."""
    conn = await asyncpg.connect(f"postgresql://{APP}:{APP_PW}@{HOST}/{DB_NAME}")
    yield conn
    await conn.close()


@pytest.fixture(scope="session")
async def client(database: None) -> AsyncIterator[httpx.AsyncClient]:
    from agentfirm.main import create_app

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _public_dns() -> Iterator[None]:
    """Deterministic DNS for the whole run (no network): every hostname resolves to a public
    address. SSRF tests pass their own resolver to exercise private/metadata addresses."""
    import socket

    from agentfirm.runtime.tools import web

    saved = web.RESOLVER
    web.RESOLVER = lambda h: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))]
    yield
    web.RESOLVER = saved


@pytest.fixture(autouse=True)
def _fixture_world() -> None:
    """Fresh fixture world (repos, calendars, ad accounts, outbox…) for every test."""
    from agentfirm.runtime.connectors import fixtures

    fixtures.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    from agentfirm.core import ratelimit

    ratelimit.reset_local()


PASSWORD = "correct-horse-battery-9"


@dataclass
class Account:
    email: str
    user_id: str
    org_id: str
    access: str
    refresh: str

    @property
    def h(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.access}"}


async def register(client: httpx.AsyncClient, org: str = "Acme", name: str = "Ada") -> Account:
    email = f"{name.lower()}.{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/v1/auth/register", json={"email": email, "name": name, "password": PASSWORD, "organization_name": org})
    assert r.status_code == 201, r.text
    b = r.json()
    return Account(email, b["user"]["id"], b["organization"]["id"], b["access_token"], b["refresh_token"])


async def join_as(client: httpx.AsyncClient, inviter: Account, role: str, name: str = "Bob") -> Account:
    """Register a second user and add them to inviter's org with `role` via a real invitation."""
    other = await register(client, org=f"{name}'s space", name=name)
    inv = await client.post("/v1/members/invitations", headers=inviter.h, json={"email": other.email, "role": role})
    assert inv.status_code == 201, inv.text
    acc = await client.post("/v1/auth/invitations/accept", headers=other.h, json={"token": inv.json()["token"]})
    assert acc.status_code == 200, acc.text
    sw = await client.post("/v1/auth/switch-organization", headers=other.h, json={"organization_id": inviter.org_id})
    assert sw.status_code == 200, sw.text
    other.access, other.org_id = sw.json()["access_token"], inviter.org_id
    return other


async def seed_execution_children(owner_db: asyncpg.Connection, *, org_id: str, execution_id: str) -> dict[str, Any]:
    """Approvals, artifacts and usage are produced by workers (Phase 4); arrange them directly."""
    agent_id = await owner_db.fetchval("SELECT id FROM agents WHERE key = 'marketing'")
    approval_id = await owner_db.fetchval(
        "INSERT INTO approval_requests (id, org_id, execution_id, agent_id, tool_key, title, reason, side_effect) "
        "VALUES (gen_random_uuid(), $1, $2, $3, 'social.publish', 'Publish post', 'External action', 'external') RETURNING id",
        uuid.UUID(org_id),
        uuid.UUID(execution_id),
        agent_id,
    )
    artifact_id = await owner_db.fetchval(
        "INSERT INTO artifacts (id, org_id, execution_id, name, kind, size_bytes, storage_key) "
        "VALUES (gen_random_uuid(), $1, $2, 'report.pdf', 'pdf', 1024, $3) RETURNING id",
        uuid.UUID(org_id),
        uuid.UUID(execution_id),
        f"org/{org_id}/report.pdf",
    )
    await owner_db.execute(
        "INSERT INTO usage_records (org_id, execution_id, agent_key, provider, model, capability, tokens_in, tokens_out, credits, cost_usd) "
        "VALUES ($1, $2, 'marketing', 'openai', 'gpt-5-mini', 'text', 1200, 300, 4, 0.0009)",
        uuid.UUID(org_id),
        uuid.UUID(execution_id),
    )
    return {"approval_id": str(approval_id), "artifact_id": str(artifact_id)}
