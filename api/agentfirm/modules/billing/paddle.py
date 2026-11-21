"""Paddle Billing integration (Phase 6, ADR 0006).

* **Checkout:** the server creates a Paddle *transaction* for a plan or credit-pack price, with
  `custom_data = {org_id, kind, key}`, and returns its `checkout.url` (the approved default payment
  link + `?_ptxn=…`). Our `/billing/checkout` page loads Paddle.js, which opens the checkout.
  The browser never chooses the organisation or the price id.
* **Webhooks** (`Paddle-Signature: ts=…;h1=…`, HMAC-SHA256 of `"{ts}:{raw body}"` with the
  notification secret) are the only source of truth for subscriptions, invoices and purchased
  credits. They are verified, stored once (idempotent by event id) and applied in one transaction.
* **Plan changes** go through the subscriptions API (the customer portal can't change plans);
  payment methods, cancellation and invoices through the customer portal.
* `AGENTFIRM_PADDLE_MODE=fixture` simulates Paddle in-process for dev, CI and demos (refused in
  production): checkout completes through the same signed-webhook path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import httpx

from agentfirm.core.config import get_settings

API_BASE = {"sandbox": "https://sandbox-api.paddle.com", "production": "https://api.paddle.com"}
#: Secret used to sign fixture webhooks (fixture mode only; never a real secret).
FIXTURE_SECRET = "pdl_ntfset_fixture_only"  # nosec B105 - fixture mode only; production refuses fixture mode


class PaddleError(Exception):
    """A Paddle API call failed (message is safe to show)."""


# ── signatures ───────────────────────────────────────────────────────────────


def sign(raw: bytes, secret: str, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    h1 = hmac.new(secret.encode(), f"{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def verify(raw: bytes, header: str | None, secret: str, *, tolerance_s: int, now: float | None = None) -> bool:
    """Constant-time check of every h1 (several during secret rotation) and the timestamp window."""
    if not header or not secret:
        return False
    ts: str | None = None
    sigs: list[str] = []
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == "ts":
            ts = v
        elif k == "h1":
            sigs.append(v)
    if not ts or not ts.isdigit() or not sigs:
        return False
    if abs((now or time.time()) - int(ts)) > tolerance_s:
        return False  # replayed or badly delayed
    expected = hmac.new(secret.encode(), f"{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


# ── client ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Checkout:
    transaction_id: str
    url: str


class PaddleClient(Protocol):
    async def create_customer(self, email: str, name: str) -> str: ...
    async def create_transaction(self, price_id: str, customer_id: str, custom_data: dict[str, Any]) -> Checkout: ...
    async def change_subscription_price(self, subscription_id: str, price_id: str) -> None: ...
    async def cancel_subscription(self, subscription_id: str) -> None: ...
    async def portal_url(self, customer_id: str, subscription_ids: list[str]) -> str: ...
    async def invoice_url(self, transaction_id: str) -> str: ...


class LivePaddle:
    def __init__(self) -> None:
        s = get_settings()
        self.base = API_BASE[s.paddle_environment]
        self.key = s.paddle_api_key or ""
        self.checkout_url = s.paddle_checkout_url

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            r = await http.request(method, self.base + path, json=body, headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            err = (data or {}).get("error") or {}
            raise PaddleError(f"Paddle: {err.get('detail') or err.get('code') or r.status_code}")
        return data.get("data") or {}

    async def create_customer(self, email: str, name: str) -> str:
        return str((await self._call("POST", "/customers", {"email": email, "name": name}))["id"])

    async def create_transaction(self, price_id: str, customer_id: str, custom_data: dict[str, Any]) -> Checkout:
        body: dict[str, Any] = {"items": [{"price_id": price_id, "quantity": 1}], "customer_id": customer_id, "custom_data": custom_data, "collection_mode": "automatic"}
        if self.checkout_url:
            body["checkout"] = {"url": self.checkout_url}
        d = await self._call("POST", "/transactions", body)
        url = (d.get("checkout") or {}).get("url")
        if not url:
            raise PaddleError("Paddle returned no checkout link. Set the default payment link in Paddle > Checkout settings.")
        return Checkout(str(d["id"]), str(url))

    async def change_subscription_price(self, subscription_id: str, price_id: str) -> None:
        await self._call("PATCH", f"/subscriptions/{subscription_id}", {"items": [{"price_id": price_id, "quantity": 1}], "proration_billing_mode": "prorated_immediately"})

    async def cancel_subscription(self, subscription_id: str) -> None:
        await self._call("POST", f"/subscriptions/{subscription_id}/cancel", {"effective_from": "next_billing_period"})

    async def portal_url(self, customer_id: str, subscription_ids: list[str]) -> str:
        d = await self._call("POST", f"/customers/{customer_id}/portal-sessions", {"subscription_ids": subscription_ids[:25]})
        return str(d["urls"]["general"]["overview"])

    async def invoice_url(self, transaction_id: str) -> str:
        return str((await self._call("GET", f"/transactions/{transaction_id}/invoice"))["url"])


@dataclass
class FixturePaddle:
    """In-process stand-in. Records what a real Paddle would hold so the fixture checkout can
    complete it with realistic, signed webhooks."""

    customers: dict[str, dict[str, str]] = field(default_factory=dict)
    transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    subscriptions: dict[str, dict[str, Any]] = field(default_factory=dict)
    changes: list[tuple[str, str]] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)

    async def create_customer(self, email: str, name: str) -> str:
        cid = f"ctm_fixture{secrets.token_hex(8)}"
        self.customers[cid] = {"email": email, "name": name}
        return cid

    async def create_transaction(self, price_id: str, customer_id: str, custom_data: dict[str, Any]) -> Checkout:
        tid = f"txn_fixture{secrets.token_hex(8)}"
        self.transactions[tid] = {"price_id": price_id, "customer_id": customer_id, "custom_data": custom_data}
        base = get_settings().paddle_checkout_url or "/billing/checkout"
        return Checkout(tid, f"{base}?_ptxn={tid}")

    async def change_subscription_price(self, subscription_id: str, price_id: str) -> None:
        self.changes.append((subscription_id, price_id))

    async def cancel_subscription(self, subscription_id: str) -> None:
        self.cancels.append(subscription_id)

    async def portal_url(self, customer_id: str, subscription_ids: list[str]) -> str:
        return f"/billing?fixture_portal={customer_id}"

    async def invoice_url(self, transaction_id: str) -> str:
        raise PaddleError("Fixture invoices have no PDF.")


FIXTURE = FixturePaddle()


def client() -> PaddleClient:
    mode = get_settings().paddle_mode
    if mode == "live":
        return LivePaddle()
    if mode == "fixture":
        return FIXTURE
    raise PaddleError("Billing is turned off on this server (AGENTFIRM_PADDLE_MODE=disabled).")


def webhook_secret() -> str:
    s = get_settings()
    return FIXTURE_SECRET if s.paddle_mode == "fixture" else (s.paddle_webhook_secret or "")


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def fixture_events(transaction_id: str, *, price_cents: int, currency: str, recurring: bool, now: datetime | None = None) -> list[dict[str, Any]]:
    """The webhooks Paddle would send when a checkout completes (shapes follow Paddle Billing)."""
    from dateutil.relativedelta import relativedelta

    t = FIXTURE.transactions[transaction_id]
    now = now or datetime.now(UTC)
    events: list[dict[str, Any]] = []
    sub_id = None
    if recurring:
        sub_id = f"sub_fixture{secrets.token_hex(8)}"
        period = {"starts_at": _iso(now), "ends_at": _iso(now + relativedelta(months=1))}
        sub = {
            "id": sub_id,
            "status": "active",
            "customer_id": t["customer_id"],
            "custom_data": t["custom_data"],
            "items": [{"price": {"id": t["price_id"]}, "quantity": 1}],
            "current_billing_period": period,
            "scheduled_change": None,
        }
        FIXTURE.subscriptions[sub_id] = sub
        events.append({"event_id": f"evt_fixture{secrets.token_hex(8)}", "event_type": "subscription.created", "occurred_at": _iso(now), "data": sub})
    events.append(
        {
            "event_id": f"evt_fixture{secrets.token_hex(8)}",
            "event_type": "transaction.completed",
            "occurred_at": _iso(now),
            "data": {
                "id": transaction_id,
                "status": "completed",
                "customer_id": t["customer_id"],
                "subscription_id": sub_id,
                "custom_data": t["custom_data"],
                "items": [{"price": {"id": t["price_id"]}, "quantity": 1}],
                "currency_code": currency,
                "invoice_number": f"FIX-{transaction_id[-6:].upper()}",
                "billed_at": _iso(now),
                "details": {"totals": {"grand_total": str(price_cents)}},
            },
        }
    )
    return events


def encode(event: dict[str, Any]) -> bytes:
    return json.dumps(event, separators=(",", ":")).encode()


def org_from(data: dict[str, Any]) -> UUID | None:
    try:
        return UUID(str((data.get("custom_data") or {}).get("org_id")))
    except (TypeError, ValueError):
        return None
