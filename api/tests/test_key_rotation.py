"""Master-key rotation (scripts/rotate_master_key.py): re-wraps every stored secret's data key,
dry run changes nothing, a wrong old key aborts with nothing changed, and the app reads the
secrets with the new key afterwards."""

from __future__ import annotations

import base64
import os
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from agentfirm.core.config import get_settings
from agentfirm.core.crypto import Sealed, open_sealed
from agentfirm.modules.integrations.router import aad
from scripts.rotate_master_key import rotate

from .conftest import register

DSN = os.environ["AGENTFIRM_MIGRATIONS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def secrets_stored(client, owner_db):
    admin = await register(client, org="Key Ops", name="Root")
    await owner_db.execute("UPDATE users SET is_super_admin = true WHERE id = $1", uuid.UUID(admin.user_id))
    providers = {p["key"]: p for p in (await client.get("/v1/admin/providers", headers=admin.h)).json()}
    r = await client.put(f"/v1/admin/providers/{providers['gemini']['id']}/credential", headers=admin.h, json={"api_key": "AIza-rotation-test-key-9876"})
    assert r.status_code == 200
    r = await client.post(
        "/v1/integrations/connections",
        headers=admin.h,
        json={"kind": "github", "name": "GH", "config": {"repositories": ["acme/app"]}, "secret": "ghp_rotationtoken5555"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _wrapped(owner_db):
    return {
        bytes(r["wrapped_key"])
        for r in await owner_db.fetch(
            "SELECT wrapped_key FROM provider_credentials UNION ALL SELECT wrapped_key FROM connections WHERE wrapped_key IS NOT NULL"
        )
    }


async def _read_connection(owner_db, cid) -> str:
    c = await owner_db.fetchrow("SELECT * FROM connections WHERE id = $1", uuid.UUID(cid))
    return open_sealed(Sealed(c["ciphertext"], c["nonce"], c["wrapped_key"], c["key_nonce"], c["key_id"], c["secret_last4"]), aad=aad(c["org_id"], c["id"]))


async def test_rotation_rewraps_and_app_reads_with_new_key(secrets_stored, owner_db, monkeypatch):
    settings = get_settings()
    old = settings.resolved_master_key()
    new = os.urandom(32)
    before = await _wrapped(owner_db)

    counts = await rotate(DSN, old, new, commit=False)  # dry run
    assert counts["provider_credentials"] >= 1 and counts["connections"] >= 1
    assert await _wrapped(owner_db) == before, "dry run must not change anything"

    with pytest.raises(InvalidTag):  # wrong old key: aborts, nothing written
        await rotate(DSN, os.urandom(32), new, commit=True)
    assert await _wrapped(owner_db) == before

    await rotate(DSN, old, new, commit=True)
    try:
        assert not (await _wrapped(owner_db)) & before, "every data key re-wrapped"
        monkeypatch.setattr(settings, "master_key", base64.b64encode(new).decode())
        assert await _read_connection(owner_db, secrets_stored) == "ghp_rotationtoken5555"

        from agentfirm.core.db import DbContext, apply_context, sessionmaker
        from agentfirm.modules.gateway.service import decrypt_credential

        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(platform_admin=True))
            assert await decrypt_credential(s, "gemini") == "AIza-rotation-test-key-9876"
        audit = await owner_db.fetchrow("SELECT after FROM audit_logs WHERE action = 'platform.master_key_rotated' ORDER BY id DESC LIMIT 1")
        assert audit is not None
    finally:
        await rotate(DSN, new, old, commit=True)  # leave the shared test database as other tests expect
