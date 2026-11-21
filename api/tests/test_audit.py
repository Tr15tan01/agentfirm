"""Audit log: written in the same transaction as the change; append-only for the app role."""

from __future__ import annotations

import asyncpg
import pytest

from .conftest import join_as, register


async def test_role_change_is_audited(client):
    owner = await register(client)
    member = await join_as(client, owner, "member", "Aud")
    m = next(x for x in (await client.get("/v1/members", headers=owner.h)).json() if x["user_id"] == member.user_id)
    await client.patch(f"/v1/members/{m['id']}", headers=owner.h, json={"role": "admin"})
    logs = (await client.get("/v1/audit-logs", headers=owner.h)).json()
    entry = next(e for e in logs if e["action"] == "member.role_changed")
    assert entry["before"] == {"role": "member"} and entry["after"] == {"role": "admin"}
    assert entry["actor_user_id"] == owner.user_id
    assert {"member.invited", "member.joined", "organization.created"} <= {e["action"] for e in logs}


async def test_failed_change_leaves_no_audit_entry(client):
    owner = await register(client)
    me = next(m for m in (await client.get("/v1/members", headers=owner.h)).json() if m["user_id"] == owner.user_id)
    assert (await client.patch(f"/v1/members/{me['id']}", headers=owner.h, json={"role": "viewer"})).status_code == 409
    logs = (await client.get("/v1/audit-logs", headers=owner.h)).json()
    assert not any(e["action"] == "member.role_changed" for e in logs)


@pytest.mark.parametrize("stmt", ["UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"])
async def test_app_role_cannot_modify_audit_log(client, app_db, stmt):
    owner = await register(client)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_db.transaction():
            await app_db.execute("SELECT set_config('app.org_id', $1, true)", owner.org_id)
            await app_db.execute(stmt)


async def test_trigger_blocks_even_the_owner(owner_db):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await owner_db.execute("UPDATE audit_logs SET action = 'tampered' WHERE id = (SELECT min(id) FROM audit_logs)")
