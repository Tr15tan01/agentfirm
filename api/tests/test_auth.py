"""Python-only sign-in: registration, login, refresh rotation, reuse detection, lockout, logout."""

from __future__ import annotations

import jwt
import pytest

from .conftest import PASSWORD, register


async def test_register_returns_tokens_and_owner_role(client):
    a = await register(client)
    me = await client.get("/v1/auth/me", headers=a.h)
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "owner"
    assert "members:manage_owners" in body["permissions"]
    assert body["organization"]["id"] == a.org_id


async def test_weak_password_rejected(client):
    r = await client.post("/v1/auth/register", json={"email": "weak@example.com", "name": "W", "password": "short", "organization_name": "W Org"})
    assert r.status_code == 422
    assert r.json()["title"] == "weak_password"


async def test_duplicate_email_case_insensitive(client):
    a = await register(client)
    r = await client.post("/v1/auth/register", json={"email": a.email.upper(), "name": "X", "password": PASSWORD, "organization_name": "Other"})
    assert r.status_code == 409


async def test_login_success_and_generic_failure(client):
    a = await register(client)
    ok = await client.post("/v1/auth/login", json={"email": a.email, "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["organization"]["id"] == a.org_id
    bad = await client.post("/v1/auth/login", json={"email": a.email, "password": "wrong-password-123"})
    unknown = await client.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-123"})
    # Same status and message whether or not the account exists.
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]


async def test_lockout_after_repeated_failures(client, monkeypatch):
    from agentfirm.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_max_failures", 3)
    a = await register(client)
    for _ in range(3):
        r = await client.post("/v1/auth/login", json={"email": a.email, "password": "nope-nope-nope-1"})
        assert r.status_code == 401
    # Correct password is refused while locked — the counter survived the failed requests' rollbacks.
    locked = await client.post("/v1/auth/login", json={"email": a.email, "password": PASSWORD})
    assert locked.status_code == 401 and locked.json()["title"] == "account_locked"


async def test_rate_limit(client, monkeypatch):
    from agentfirm.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_rate_per_minute", 2)
    codes = [(await client.post("/v1/auth/login", json={"email": "rl@example.com", "password": "x" * 12})).status_code for _ in range(4)]
    assert codes[-1] == 429


async def test_refresh_rotates_and_reuse_revokes_session(client):
    a = await register(client)
    r1 = await client.post("/v1/auth/refresh", json={"refresh_token": a.refresh})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    assert new_refresh != a.refresh

    # Replaying the OLD refresh token = theft signal → session revoked.
    replay = await client.post("/v1/auth/refresh", json={"refresh_token": a.refresh})
    assert replay.status_code == 401
    # …which also kills the legitimate newer token and the access token.
    after = await client.post("/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after.status_code == 401
    me = await client.get("/v1/auth/me", headers={"authorization": f"Bearer {r1.json()['access_token']}"})
    assert me.status_code == 401


async def test_logout_revokes_access_immediately(client):
    a = await register(client)
    assert (await client.get("/v1/auth/me", headers=a.h)).status_code == 200
    assert (await client.post("/v1/auth/logout", headers=a.h)).status_code == 204
    assert (await client.get("/v1/auth/me", headers=a.h)).status_code == 401
    assert (await client.post("/v1/auth/refresh", json={"refresh_token": a.refresh})).status_code == 401


async def test_sessions_list_and_revoke_other_session(client):
    a = await register(client)
    second = (await client.post("/v1/auth/login", json={"email": a.email, "password": PASSWORD})).json()
    sessions = (await client.get("/v1/auth/sessions", headers=a.h)).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert (await client.delete(f"/v1/auth/sessions/{other['id']}", headers=a.h)).status_code == 204
    assert (await client.get("/v1/auth/me", headers={"authorization": f"Bearer {second['access_token']}"})).status_code == 401


@pytest.mark.parametrize(
    "tamper",
    ["alg_none", "wrong_key", "expired", "wrong_audience"],
)
async def test_forged_tokens_rejected(client, tamper):
    from datetime import UTC, datetime, timedelta

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    a = await register(client)
    claims = jwt.decode(a.access, options={"verify_signature": False})
    if tamper == "alg_none":
        token = jwt.encode(claims, key="", algorithm="none")
    elif tamper == "wrong_key":
        token = jwt.encode(claims, Ed25519PrivateKey.generate(), algorithm="EdDSA")
    else:
        from agentfirm.core.security import _keys

        if tamper == "expired":
            claims["exp"] = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())
        else:
            claims["aud"] = "someone-else"
        token = jwt.encode(claims, _keys()[0], algorithm="EdDSA")
    r = await client.get("/v1/auth/me", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_switch_org_requires_membership(client):
    a = await register(client)
    b = await register(client, org="Other Co", name="Bea")
    r = await client.post("/v1/auth/switch-organization", headers=a.h, json={"organization_id": b.org_id})
    assert r.status_code == 404
