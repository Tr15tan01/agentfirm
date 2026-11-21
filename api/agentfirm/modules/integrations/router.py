"""Organisation connections (Settings → Integrations).

Secrets (tokens, passwords, signing keys) are envelope-encrypted with an AAD bound to the
connection id and organisation; the API only ever returns `secret_last4`. Every URL an
organisation supplies must be public HTTPS (same SSRF rules as agent web fetches), checked
when saved and again on every call. Every change is audit-logged.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from agentfirm.core.crypto import seal
from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.errors import NotFound, Unprocessable
from agentfirm.core.permissions import Perm
from agentfirm.modules.audit.service import record
from agentfirm.runtime.tools.web import BlockedURL, WebError, assert_public_url

from .models import Connection

router = APIRouter(prefix="/integrations", tags=["integrations"])
Kind = Literal["github", "webhook", "smtp", "gn7t"]

#: Actions an organisation can route to its own automation endpoint (n8n, Zapier, Make, own service).
WEBHOOK_ACTIONS = (
    "social.publish",
    "ads.performance_read",
    "ads.budget_change",
    "seo.keywords",
    "calendar.read",
    "calendar.create_event",
    "automation.run",
    "payments.execute",
    "purchase.execute",
    "deploy.preview",
    "deploy.production",
    "email.send",
)
REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


def aad(org_id: UUID, connection_id: UUID) -> bytes:
    return f"connection:{org_id}:{connection_id}".encode()


class ConnectionIn(BaseModel):
    kind: Kind
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = Field(default=None, max_length=8000, description="Token / password / signing secret. Write-only.")


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, max_length=8000)
    status: Literal["active", "disabled"] | None = None


class ConnectionOut(BaseModel):
    id: UUID
    kind: Kind
    name: str
    config: dict[str, Any]
    secret_last4: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    #: Returned once, only when the server generated a webhook signing secret for you.
    signing_secret: str | None = None


def _out(c: Connection, signing_secret: str | None = None) -> ConnectionOut:
    return ConnectionOut(
        id=c.id,
        kind=c.kind,
        name=c.name,
        config=c.config,
        secret_last4=c.secret_last4,
        status=c.status,  # type: ignore[arg-type]
        created_at=c.created_at,
        updated_at=c.updated_at,
        signing_secret=signing_secret,
    )


async def _public_https(url: str, field: str) -> str:
    if not isinstance(url, str) or not url.startswith("https://"):
        raise Unprocessable(f"{field} must be an https:// URL.")
    try:
        await assert_public_url(url)
    except BlockedURL as exc:
        raise Unprocessable(f"{field} is not allowed: {exc}") from exc
    except WebError as exc:  # unresolvable host: a validation problem, not a server error
        raise Unprocessable(f"{field}: the host name could not be resolved. Check the URL.") from exc
    return url.rstrip("/")


async def validate_config(kind: str, config: dict[str, Any], secret: str | None, *, creating: bool) -> dict[str, Any]:
    """Return the normalised, non-secret config for a connection kind (raises 422)."""
    out: dict[str, Any] = {}
    if kind == "github":
        repos = config.get("repositories") or []
        if not isinstance(repos, list) or not repos or not all(isinstance(r, str) and REPO.match(r) for r in repos):
            raise Unprocessable("github: `repositories` must list one or more owner/name repositories the agents may use.")
        out["repositories"] = repos[:50]
        out["default_repository"] = config.get("default_repository") or repos[0]
        if out["default_repository"] not in out["repositories"]:
            raise Unprocessable("github: default_repository must be one of `repositories`.")
        out["api_base"] = await _public_https(config["api_base"], "api_base") if config.get("api_base") else "https://api.github.com"
        if creating and not secret:
            raise Unprocessable("github: a token (fine-grained, repository-scoped) is required.")
    elif kind == "webhook":
        out["url"] = await _public_https(config.get("url", ""), "url")
        actions = config.get("actions") or []
        bad = [a for a in actions if a not in WEBHOOK_ACTIONS]
        if not actions or bad:
            raise Unprocessable(f"webhook: `actions` must be a non-empty subset of {list(WEBHOOK_ACTIONS)} (unknown: {bad}).")
        out["actions"] = sorted(set(actions))
    elif kind == "smtp":
        host, port = config.get("host"), config.get("port", 587)
        if not isinstance(host, str) or not re.match(r"^[A-Za-z0-9.-]{1,253}$", host):
            raise Unprocessable("smtp: `host` is required.")
        if port not in (465, 587):
            raise Unprocessable("smtp: only TLS ports 465 (implicit TLS) and 587 (STARTTLS) are allowed.")
        try:
            await assert_public_url(f"https://{host}/")  # never relay through internal hosts
        except (BlockedURL, WebError) as exc:
            raise Unprocessable(f"smtp: host {host} is not allowed or could not be resolved.") from exc
        frm = config.get("from_address", "")
        if not EMAIL.match(frm):
            raise Unprocessable("smtp: `from_address` must be an email address.")
        out |= {"host": host, "port": port, "username": str(config.get("username") or frm)[:254], "from_address": frm}
        if creating and not secret:
            raise Unprocessable("smtp: a password or app password is required.")
    elif kind == "gn7t":
        out["base_url"] = await _public_https(config.get("base_url", ""), "base_url")
        if creating and not secret:
            raise Unprocessable("gn7t: an API key is required.")
    return out


def _seal_into(c: Connection, secret: str) -> None:
    s = seal(secret, aad=aad(c.org_id, c.id))
    c.ciphertext, c.nonce, c.wrapped_key, c.key_nonce, c.key_id, c.secret_last4 = s.ciphertext, s.nonce, s.wrapped_key, s.key_nonce, s.key_id, s.last4


async def _get(session: DbSession, principal: Principal, connection_id: UUID) -> Connection:
    c = (await session.execute(select(Connection).where(Connection.id == connection_id, Connection.org_id == principal.org_id))).scalar_one_or_none()
    if c is None:
        raise NotFound("Connection not found.")
    return c


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)) -> list[ConnectionOut]:
    rows = (await session.execute(select(Connection).where(Connection.org_id == principal.org_id).order_by(Connection.created_at))).scalars()
    return [_out(c) for c in rows]


@router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionIn, session: DbSession, principal: Principal = require(Perm.WORKSPACE_MANAGE)) -> ConnectionOut:
    config = await validate_config(body.kind, body.config, body.secret, creating=True)
    generated = None
    secret = body.secret
    if body.kind == "webhook" and not secret:
        secret = generated = f"whsec_{secrets.token_urlsafe(32)}"
    c = Connection(id=uuid4(), org_id=principal.org_id, kind=body.kind, name=body.name, config=config, created_by=principal.user_id)
    if secret:
        _seal_into(c, secret)
    session.add(c)
    await session.flush()
    await record(
        session,
        action="integration.connected",
        target_type="connection",
        target_id=c.id,
        actor=principal,
        after={"kind": c.kind, "name": c.name, "config": config},
    )
    await session.refresh(c)
    return _out(c, generated)


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: UUID, body: ConnectionPatch, session: DbSession, principal: Principal = require(Perm.WORKSPACE_MANAGE)
) -> ConnectionOut:
    c = await _get(session, principal, connection_id)
    before = {"name": c.name, "config": c.config, "status": c.status}
    if body.config is not None:
        c.config = await validate_config(c.kind, body.config, body.secret, creating=False)
    if body.secret:
        _seal_into(c, body.secret)
    if body.name:
        c.name = body.name
    if body.status:
        c.status = body.status
    c.updated_at = datetime.now(UTC)
    await session.flush()
    await record(
        session,
        action="integration.updated",
        target_type="connection",
        target_id=c.id,
        actor=principal,
        before=before,
        after={"name": c.name, "config": c.config, "status": c.status, "secret_rotated": bool(body.secret)},
    )
    return _out(c)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: UUID, session: DbSession, principal: Principal = require(Perm.WORKSPACE_MANAGE)) -> Response:
    c = await _get(session, principal, connection_id)
    await record(session, action="integration.disconnected", target_type="connection", target_id=c.id, actor=principal, before={"kind": c.kind, "name": c.name})
    await session.delete(c)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
