"""Connectors: how agent tools reach an organisation's external systems.

* `github`  — repositories (read, agent/* branches, pull requests) via the GitHub REST API.
* `webhook` — any action an organisation routes to its own automation endpoint (n8n, Zapier,
              Make or an internal service): social posts, ad budgets, calendar, payments,
              purchases, deploys… Requests are HMAC-signed and carry an Idempotency-Key.
* `smtp`    — sending approved emails over TLS.
* `gn7t`    — read-only queries against the GN7T Database Service (assumed contract, ADR 0004).

Secrets are decrypted in memory for one call and never logged or returned. Every URL is
re-checked against the SSRF rules at call time (DNS can change after it was saved).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from sqlalchemy import select

from agentfirm.agents.contracts import ErrorCode
from agentfirm.core.config import get_settings
from agentfirm.core.crypto import Sealed, open_sealed
from agentfirm.core.db import DbContext, apply_context, sessionmaker
from agentfirm.modules.integrations.models import Connection

from ..errors import StepError
from ..tools.web import BlockedURL, assert_public_url

if TYPE_CHECKING:
    from ..context import ExecutionContext

LABEL = {"github": "GitHub", "webhook": "an automation webhook", "smtp": "an email (SMTP) account", "gn7t": "GN7T"}
MAX_RESPONSE = 1_000_000


def fixture_mode() -> bool:
    return get_settings().connector_mode == "fixture"


@dataclass(frozen=True)
class Conn:
    id: UUID
    kind: str
    name: str
    config: dict[str, Any]
    secret: str | None


async def load(ctx: ExecutionContext, kind: str, *, action: str | None = None) -> Conn:
    """The organisation's active connection of `kind` (for webhooks: one that handles `action`)."""
    from agentfirm.modules.integrations.router import aad

    async with sessionmaker()() as s, s.begin():
        await apply_context(s, DbContext(org_id=ctx.org_id))
        rows = (
            (
                await s.execute(
                    select(Connection)
                    .where(Connection.org_id == ctx.org_id, Connection.kind == kind, Connection.status == "active")
                    .order_by(Connection.created_at)
                )
            )
            .scalars()
            .all()
        )
    if action is not None:
        rows = [r for r in rows if action in (r.config.get("actions") or [])]
    if not rows:
        what = f"{LABEL[kind]} that handles {action}" if action else LABEL[kind]
        raise StepError(ErrorCode.MISSING_CONTEXT, f"No connection for this: connect {what} in Settings → Integrations.")
    c = rows[0]
    secret = None
    if c.ciphertext is not None:
        secret = open_sealed(Sealed(c.ciphertext, c.nonce, c.wrapped_key, c.key_nonce, c.key_id or "", c.secret_last4 or ""), aad=aad(c.org_id, c.id))  # type: ignore[arg-type]
    return Conn(c.id, c.kind, c.name, dict(c.config), secret)


def http_error(name: str, resp: httpx.Response) -> StepError:
    """Map an upstream HTTP failure to an agent error (no response body in the message beyond 200 chars)."""
    code = resp.status_code
    detail = resp.text[:200].replace("\n", " ")
    if code in (401, 403):
        return StepError(ErrorCode.PERMISSION_DENIED, f"{name} rejected the request ({code}); reconnect it in Settings → Integrations. {detail}")
    if code == 404:
        return StepError(ErrorCode.TOOL_ERROR, f"{name}: not found (404). {detail}")
    if code == 429 or code >= 500:
        return StepError(ErrorCode.TOOL_ERROR, f"{name} is unavailable ({code}).", retriable=True)
    return StepError(ErrorCode.TOOL_ERROR, f"{name} refused the request ({code}). {detail}")


async def request(method: str, url: str, *, name: str, timeout_s: float = 30, **kw: Any) -> httpx.Response:
    """SSRF-checked HTTP call without redirects; transport errors become retriable tool errors."""
    try:
        await assert_public_url(url)
    except BlockedURL as exc:
        raise StepError(ErrorCode.POLICY_VIOLATION, f"{name}: {exc}") from exc
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            resp = await client.request(method, url, **kw)
    except httpx.HTTPError as exc:
        raise StepError(ErrorCode.TOOL_ERROR, f"{name} could not be reached: {exc.__class__.__name__}", retriable=True) from exc
    if len(resp.content) > MAX_RESPONSE:
        raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, f"{name} returned more than 1 MB")
    return resp


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


async def webhook(ctx: ExecutionContext, action: str, args: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    """POST a signed action to the organisation's automation endpoint and return its JSON.

    Body: {"action", "organization_id", "execution_id", "idempotency_key", "args"}.
    Header: X-AgentFirm-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>.
    Receivers should reject signatures older than 5 minutes and de-duplicate on the key.
    """
    conn = await load(ctx, "webhook", action=action)
    body = json.dumps(
        {"action": action, "organization_id": str(ctx.org_id), "execution_id": str(ctx.execution_id), "idempotency_key": idempotency_key, "args": args},
        default=str,
    ).encode()
    ts = int(time.time())
    headers = {
        "content-type": "application/json",
        "user-agent": "AgentFirm-Webhook/1",
        "idempotency-key": idempotency_key,
        "x-agentfirm-action": action,
        "x-agentfirm-signature": f"t={ts},v1={sign(conn.secret or '', ts, body)}",
    }
    resp = await request("POST", conn.config["url"], name=conn.name, content=body, headers=headers)
    if resp.status_code >= 300:
        raise http_error(conn.name, resp)
    try:
        data = resp.json() if resp.content else {}
    except ValueError as exc:
        raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, f"{conn.name} returned non-JSON for {action}") from exc
    if not isinstance(data, dict):
        data = {"result": data}
    return data | {"via": conn.name}
