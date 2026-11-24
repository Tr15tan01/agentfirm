"""Super-admin model import and review (POST import-models, PATCH models)."""

from __future__ import annotations

import uuid

import pytest
import respx

from .conftest import register

GN7T_BASE = "https://gn7t.example.com/api/v1/openai/v1"


@pytest.fixture
async def admin(client, owner_db):
    acc = await register(client, org="Platform Ops", name="Root")
    await owner_db.execute("UPDATE users SET is_super_admin = true WHERE id = $1", uuid.UUID(acc.user_id))
    return acc


async def _provider_id(client, admin, key):
    rows = (await client.get("/v1/admin/providers", headers=admin.h)).json()
    return next(p["id"] for p in rows if p["key"] == key)


async def _enable_gn7t(client, admin):
    pid = await _provider_id(client, admin, "gn7t")
    r = await client.patch(f"/v1/admin/providers/{pid}", headers=admin.h, json={"enabled": True, "base_url": GN7T_BASE})
    assert r.status_code == 200, r.text
    return pid


@respx.mock
async def test_import_adds_new_models_disabled_and_is_idempotent(client, admin):
    pid = await _enable_gn7t(client, admin)
    respx.get(f"{GN7T_BASE}/models").respond(200, json={"data": [{"id": "gn7t-fresh-70b"}, {"id": "gn7t-core"}]})

    r = await client.post(f"/v1/admin/providers/{pid}/import-models", headers=admin.h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] == 2 and body["added"] == ["gn7t-fresh-70b"] and body["already_present"] == 1

    models = {m["name"]: m for m in (await client.get("/v1/admin/models", headers=admin.h)).json()}
    assert models["gn7t-fresh-70b"]["enabled"] is False, "imported models must wait for admin review"

    again = (await client.post(f"/v1/admin/providers/{pid}/import-models", headers=admin.h)).json()
    assert again["added"] == [] and again["already_present"] == 2


@respx.mock
async def test_import_reports_upstream_errors(client, admin):
    pid = await _enable_gn7t(client, admin)
    respx.get(f"{GN7T_BASE}/models").respond(401, json={"error": {"message": "bad key"}})
    r = await client.post(f"/v1/admin/providers/{pid}/import-models", headers=admin.h)
    assert r.status_code == 422
    assert "gn7t" in r.text


async def test_import_refuses_disabled_provider(client, admin):
    pid = await _provider_id(client, admin, "gn7t")
    await client.patch(f"/v1/admin/providers/{pid}", headers=admin.h, json={"enabled": False})
    try:
        r = await client.post(f"/v1/admin/providers/{pid}/import-models", headers=admin.h)
        assert r.status_code == 422 and "Enable the provider" in r.text
    finally:
        # The test database is shared across the session: leave gn7t enabled for later tests.
        await client.patch(f"/v1/admin/providers/{pid}", headers=admin.h, json={"enabled": True})


async def test_import_requires_super_admin(client, admin):
    tenant = await register(client, org="Other", name="Tenant")
    pid = await _provider_id(client, admin, "gn7t")
    r = await client.post(f"/v1/admin/providers/{pid}/import-models", headers=tenant.h)
    assert r.status_code in (401, 403, 404)


async def test_patch_model_enables_and_reprices(client, admin):
    models = {m["name"]: m for m in (await client.get("/v1/admin/models", headers=admin.h)).json()}
    mid = models["gemini-3.6-flash"]["id"]
    r = await client.patch(f"/v1/admin/models/{mid}", headers=admin.h, json={"enabled": True, "price_in_per_1m": "1.25"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["enabled"] is True and str(out["price_in_per_1m"]).startswith("1.25")


async def test_migration_removed_gemini2_and_tea800(client, admin):
    models = {m["name"] for m in (await client.get("/v1/admin/models", headers=admin.h)).json()}
    assert not any(name.startswith("gemini-2.") for name in models)
    assert {"gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"} <= models
    providers = {p["key"] for p in (await client.get("/v1/admin/providers", headers=admin.h)).json()}
    assert "tea800" not in providers
