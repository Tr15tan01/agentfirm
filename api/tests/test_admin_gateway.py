"""Super-admin model routing: choose provider/model per task type, encrypted credentials, audit."""

from __future__ import annotations

import uuid

import pytest

from .conftest import register


@pytest.fixture
async def admin(client, owner_db):
    acc = await register(client, org="Platform Ops", name="Root")
    await owner_db.execute("UPDATE users SET is_super_admin = true WHERE id = $1", uuid.UUID(acc.user_id))
    return acc


async def _models(client, admin):
    return {m["name"]: m for m in (await client.get("/v1/admin/models", headers=admin.h)).json()}


async def test_platform_routes_seeded_for_every_capability(client, admin):
    routes = {r["capability"]: r for r in (await client.get("/v1/admin/routes", headers=admin.h)).json()}
    assert set(routes) == {"reasoning", "text", "code", "summarize", "classify", "creative", "vision", "long_context", "embeddings"}
    assert routes["reasoning"]["primary"]["name"] == "gemini-2.5-pro"
    assert [m["provider"] for m in routes["text"]["fallbacks"]] == ["gemini", "gn7t"]


async def test_change_reasoning_to_gn7t_primary(client, admin):
    models = await _models(client, admin)
    body = {"primary": models["gn7t-core"]["id"], "fallbacks": [models["gpt-5"]["id"]], "params": {"temperature": 0.1}}
    r = await client.put("/v1/admin/routes/reasoning", headers=admin.h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["primary"]["provider"] == "gn7t"
    resolved = (await client.get("/v1/admin/routes/reasoning/resolve", headers=admin.h)).json()
    assert [m["name"] for m in resolved] == ["gn7t-core", "gpt-5"]


async def test_route_rejects_model_without_capability(client, admin):
    models = await _models(client, admin)
    r = await client.put("/v1/admin/routes/vision", headers=admin.h, json={"primary": models["gn7t-core"]["id"]})
    assert r.status_code == 422 and r.json()["title"] == "capability_mismatch"
    dup = await client.put("/v1/admin/routes/text", headers=admin.h, json={"primary": models["gpt-5-mini"]["id"], "fallbacks": [models["gpt-5-mini"]["id"]]})
    assert dup.status_code == 422


async def test_disabled_provider_skipped_in_resolution(client, admin):
    providers = {p["key"]: p for p in (await client.get("/v1/admin/providers", headers=admin.h)).json()}
    await client.patch(f"/v1/admin/providers/{providers['gemini']['id']}", headers=admin.h, json={"enabled": False})
    resolved = (await client.get("/v1/admin/routes/creative/resolve", headers=admin.h)).json()
    assert all(m["provider"] != "gemini" for m in resolved)
    await client.patch(f"/v1/admin/providers/{providers['gemini']['id']}", headers=admin.h, json={"enabled": True})


async def test_credentials_encrypted_and_never_returned(client, admin, owner_db):
    secret = "sk-test-SUPERSECRET-1234567890-abcd"
    providers = {p["key"]: p for p in (await client.get("/v1/admin/providers", headers=admin.h)).json()}
    r = await client.put(f"/v1/admin/providers/{providers['openai']['id']}/credential", headers=admin.h, json={"api_key": secret})
    assert r.status_code == 200
    assert r.json()["credential_last4"] == "abcd"
    assert secret not in r.text
    assert secret not in (await client.get("/v1/admin/providers", headers=admin.h)).text

    row = await owner_db.fetchrow(
        "SELECT ciphertext FROM provider_credentials WHERE revoked_at IS NULL AND provider_id = $1", uuid.UUID(providers["openai"]["id"])
    )
    assert secret.encode() not in bytes(row["ciphertext"])

    # Round-trip through the gateway-only decrypt path.
    from agentfirm.core.db import DbContext, apply_context, sessionmaker
    from agentfirm.modules.gateway.service import decrypt_credential

    async with sessionmaker()() as s, s.begin():
        await apply_context(s, DbContext(platform_admin=True))
        assert await decrypt_credential(s, "openai") == secret

    audit = await owner_db.fetchrow("SELECT after FROM audit_logs WHERE action = 'gateway.credential_rotated' ORDER BY id DESC LIMIT 1")
    assert secret not in str(audit["after"])


async def test_route_change_audited_as_platform_event(client, admin, owner_db):
    models = await _models(client, admin)
    await client.put(
        "/v1/admin/routes/summarize", headers=admin.h, json={"primary": models["gemini-2.5-flash"]["id"], "fallbacks": [models["gn7t-core"]["id"]]}
    )
    row = await owner_db.fetchrow("SELECT org_id, actor_user_id, before, after FROM audit_logs WHERE action = 'gateway.route_updated' ORDER BY id DESC LIMIT 1")
    assert row["org_id"] is None and str(row["actor_user_id"]) == admin.user_id
    assert '"gemini-2.5-flash"' in row["after"]


async def test_admin_lists_all_orgs_but_tenants_do_not(client, admin):
    other = await register(client, org="Tenant Z", name="Zed")
    orgs = {o["id"] for o in (await client.get("/v1/admin/organizations", headers=admin.h)).json()}
    assert other.org_id in orgs and admin.org_id in orgs
