"""Pure units: crypto, passwords, permission seed parity."""

from __future__ import annotations

import itertools

import pytest
from cryptography.exceptions import InvalidTag

from agentfirm.core.crypto import open_sealed, seal
from agentfirm.core.errors import Unprocessable
from agentfirm.core.permissions import ROLE_PERMISSIONS, Perm, Role
from agentfirm.core.security import hash_password, validate_password_policy, verify_password


def test_seal_roundtrip_and_aad_binding():
    s = seal("sk-live-abcdef123456", aad=b"provider:1")
    assert open_sealed(s, aad=b"provider:1") == "sk-live-abcdef123456"
    with pytest.raises(InvalidTag):
        open_sealed(s, aad=b"provider:2")


def test_password_hashing():
    h = hash_password("a-long-enough-password-1")
    assert h.startswith("$argon2id$")
    assert verify_password("a-long-enough-password-1", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


@pytest.mark.parametrize("pw", ["short", "aaaaaaaaaaaaaaa", "alice-is-great-123"])
def test_password_policy(pw):
    with pytest.raises(Unprocessable):
        validate_password_policy(pw, "alice@example.com")


def test_role_hierarchy_is_monotonic():
    order = [Role.VIEWER, Role.MEMBER, Role.ADMIN, Role.OWNER]
    for lower, higher in itertools.pairwise(order):
        assert ROLE_PERMISSIONS[lower] < ROLE_PERMISSIONS[higher]
    assert Perm.MEMBERS_MANAGE_OWNERS in ROLE_PERMISSIONS[Role.OWNER]
    assert Perm.MEMBERS_MANAGE_OWNERS not in ROLE_PERMISSIONS[Role.ADMIN]


async def test_db_permission_seed_matches_code(owner_db):
    rows = await owner_db.fetch("SELECT role, permission FROM role_permissions")
    db = {(r["role"], r["permission"]) for r in rows}
    code = {(r.value, p.value) for r, ps in ROLE_PERMISSIONS.items() for p in ps}
    assert db == code
