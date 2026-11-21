"""Passwords (argon2id), access tokens (EdDSA JWT) and opaque refresh tokens."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import get_settings
from .errors import Unauthorized, Unprocessable

_hasher = PasswordHasher()  # argon2id, library defaults (RFC 9106 recommended params)

# A real hash of a random password: verifying against it keeps timing uniform for unknown emails.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


async def hash_password_async(password: str) -> str:
    """Argon2 takes ~50-100 ms of CPU by design; off the event loop so one sign-up doesn't stall
    every other request (found by the Phase 7 load test). argon2-cffi releases the GIL."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, stored: str | None) -> bool:
    return await asyncio.to_thread(verify_password, password, stored)


def verify_password(password: str, stored: str | None) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


def validate_password_policy(password: str, email: str) -> None:
    if len(password) < 12:
        raise Unprocessable("Password must be at least 12 characters.", code="weak_password")
    if len(password) > 256:
        raise Unprocessable("Password is too long.", code="weak_password")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        raise Unprocessable("Password must not contain your email name.", code="weak_password")
    if len(set(password)) < 6:
        raise Unprocessable("Password is too repetitive.", code="weak_password")


@lru_cache
def _keys() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private = serialization.load_pem_private_key(get_settings().resolved_private_key().encode(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise RuntimeError("JWT key must be Ed25519")
    return private, private.public_key()


def public_jwk() -> dict[str, str]:
    """Public key for other internal services (workers) to verify access tokens."""
    raw = _keys()[1].public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    import base64

    return {"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "kid": "af-1", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    org_id: UUID | None
    session_id: UUID
    expires_at: datetime


def issue_access_token(*, user_id: UUID, org_id: UUID | None, session_id: UUID) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=s.access_token_ttl_seconds)
    payload = {
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "sid": str(session_id),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid4().hex,
    }
    token = jwt.encode(payload, _keys()[0], algorithm="EdDSA", headers={"kid": "af-1"})
    return token, exp


def decode_access_token(token: str) -> AccessClaims:
    s = get_settings()
    try:
        p = jwt.decode(
            token,
            _keys()[1],
            algorithms=["EdDSA"],  # pinned: never accept "none" or HS* confusion
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "sid", "aud", "iss"]},
            leeway=5,
        )
        return AccessClaims(
            user_id=UUID(p["sub"]),
            org_id=UUID(p["org"]) if p.get("org") else None,
            session_id=UUID(p["sid"]),
            expires_at=datetime.fromtimestamp(p["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Invalid or expired access token.", code="invalid_token") from exc


def new_refresh_secret() -> str:
    return secrets.token_urlsafe(48)


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
