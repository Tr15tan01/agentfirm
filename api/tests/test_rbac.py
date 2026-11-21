"""Role-based authorization is enforced by the API, not the UI."""

from __future__ import annotations

from .conftest import join_as, register


async def test_viewer_cannot_create_or_control(client):
    owner = await register(client)
    viewer = await join_as(client, owner, "viewer", "Vic")
    assert (await client.get("/v1/tasks", headers=viewer.h)).status_code == 200
    r = await client.post("/v1/tasks", headers=viewer.h, json={"objective": "Do something useful", "agents": ["research"]})
    assert r.status_code == 403 and r.json()["title"] == "missing_permission"
    task = (await client.post("/v1/tasks", headers=owner.h, json={"objective": "Owner task", "agents": ["research"]})).json()
    assert (await client.post(f"/v1/tasks/{task['id']}/cancel", headers=viewer.h)).status_code == 403


async def test_member_cannot_manage_members_or_read_audit(client):
    owner = await register(client)
    member = await join_as(client, owner, "member", "Mia")
    assert (await client.post("/v1/members/invitations", headers=member.h, json={"email": "x@example.com", "role": "viewer"})).status_code == 403
    assert (await client.get("/v1/audit-logs", headers=member.h)).status_code == 403


async def test_admin_cannot_grant_or_touch_owner(client):
    owner = await register(client)
    admin = await join_as(client, owner, "admin", "Adi")
    members = (await client.get("/v1/members", headers=admin.h)).json()
    owner_m = next(m for m in members if m["role"] == "owner")
    admin_m = next(m for m in members if m["user_id"] == admin.user_id)
    assert (await client.patch(f"/v1/members/{admin_m['id']}", headers=admin.h, json={"role": "owner"})).status_code == 403
    assert (await client.patch(f"/v1/members/{owner_m['id']}", headers=admin.h, json={"role": "viewer"})).status_code == 403
    assert (await client.delete(f"/v1/members/{owner_m['id']}", headers=admin.h)).status_code == 403
    assert (await client.post("/v1/members/invitations", headers=admin.h, json={"email": "boss@example.com", "role": "owner"})).status_code == 403


async def test_last_owner_cannot_be_demoted(client):
    owner = await register(client)
    me = next(m for m in (await client.get("/v1/members", headers=owner.h)).json() if m["user_id"] == owner.user_id)
    r = await client.patch(f"/v1/members/{me['id']}", headers=owner.h, json={"role": "admin"})
    assert r.status_code == 409 and r.json()["title"] == "last_owner"


async def test_role_change_takes_effect_immediately(client):
    owner = await register(client)
    member = await join_as(client, owner, "member", "Max")
    assert (await client.post("/v1/tasks", headers=member.h, json={"objective": "Allowed now", "agents": ["assistant"]})).status_code == 201
    m = next(x for x in (await client.get("/v1/members", headers=owner.h)).json() if x["user_id"] == member.user_id)
    assert (await client.patch(f"/v1/members/{m['id']}", headers=owner.h, json={"role": "viewer"})).status_code == 200
    # Same (still valid) access token — permissions are re-read from the database per request.
    assert (await client.post("/v1/tasks", headers=member.h, json={"objective": "Not anymore", "agents": ["assistant"]})).status_code == 403


async def test_removed_member_loses_access(client):
    owner = await register(client)
    member = await join_as(client, owner, "member", "Rem")
    m = next(x for x in (await client.get("/v1/members", headers=owner.h)).json() if x["user_id"] == member.user_id)
    assert (await client.delete(f"/v1/members/{m['id']}", headers=owner.h)).status_code == 204
    assert (await client.get("/v1/tasks", headers=member.h)).status_code in (401, 403)


async def test_non_super_admin_blocked_from_admin_api(client):
    owner = await register(client)
    for path in ("/v1/admin/providers", "/v1/admin/routes", "/v1/admin/organizations"):
        r = await client.get(path, headers=owner.h)
        assert r.status_code == 403 and r.json()["title"] == "not_super_admin"


async def test_invitation_bound_to_email(client):
    owner = await register(client)
    stranger = await register(client, org="Stranger Org", name="Sam")
    inv = (await client.post("/v1/members/invitations", headers=owner.h, json={"email": "intended@example.com", "role": "member"})).json()
    r = await client.post("/v1/auth/invitations/accept", headers=stranger.h, json={"token": inv["token"]})
    assert r.status_code == 403 and r.json()["title"] == "invite_email_mismatch"
