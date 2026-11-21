from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Query, Request

from agentfirm.core.config import get_settings
from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.errors import Unauthorized, Unprocessable
from agentfirm.core.observability import WEBHOOKS
from agentfirm.core.permissions import Perm

from . import paddle, service, subscriptions
from .service import Range, UsageReport

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=UsageReport)
async def usage(session: DbSession, range_: Range = Query(default="30d", alias="range"), principal: Principal = require(Perm.USAGE_READ)) -> UsageReport:
    return await service.report(session, principal, range_)


# ── Phase 6: plans, credits and Paddle billing ──────────────────────────────

billing_router = APIRouter(prefix="/billing", tags=["billing"])


@billing_router.get("/catalog", response_model=subscriptions.Catalog)
async def catalog(session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)) -> subscriptions.Catalog:
    return await subscriptions.catalog(session)


@billing_router.get("/account", response_model=subscriptions.AccountOut)
async def account(session: DbSession, principal: Principal = require(Perm.USAGE_READ)) -> subscriptions.AccountOut:
    return await subscriptions.account(session, principal)


@billing_router.get("/invoices", response_model=list[subscriptions.InvoiceOut])
async def invoices(session: DbSession, principal: Principal = require(Perm.BILLING_MANAGE)) -> list[subscriptions.InvoiceOut]:
    return await subscriptions.invoices(session, principal)


@billing_router.get("/invoices/{invoice_id}/pdf", response_model=subscriptions.UrlOut)
async def invoice_pdf(invoice_id: UUID, session: DbSession, principal: Principal = require(Perm.BILLING_MANAGE)) -> subscriptions.UrlOut:
    return await subscriptions.invoice_pdf(session, principal, invoice_id)


@billing_router.get("/ledger", response_model=list[subscriptions.LedgerOut])
async def ledger(session: DbSession, principal: Principal = require(Perm.USAGE_READ)) -> list[subscriptions.LedgerOut]:
    return await subscriptions.ledger(session, principal)


@billing_router.post("/checkout", response_model=subscriptions.CheckoutOut)
async def checkout(body: subscriptions.CheckoutIn, session: DbSession, principal: Principal = require(Perm.BILLING_MANAGE)) -> subscriptions.CheckoutOut:
    return await subscriptions.checkout(session, principal, body)


@billing_router.post("/portal", response_model=subscriptions.UrlOut)
async def portal(session: DbSession, principal: Principal = require(Perm.BILLING_MANAGE)) -> subscriptions.UrlOut:
    return await subscriptions.portal(session, principal)


@billing_router.post("/cancel", response_model=subscriptions.AccountOut)
async def cancel(session: DbSession, principal: Principal = require(Perm.BILLING_MANAGE)) -> subscriptions.AccountOut:
    return await subscriptions.cancel(session, principal)


@billing_router.post("/fixture/checkout/{transaction_id}/complete", include_in_schema=False)
async def fixture_complete(transaction_id: str, session: DbSession, principal: Principal = require(Perm.BILLING_MANAGE)) -> dict[str, list[str]]:
    return {"events": await subscriptions.fixture_complete(session, principal, transaction_id)}


@billing_router.post("/paddle/webhook", include_in_schema=False)
async def paddle_webhook(request: Request, session: DbSession) -> dict[str, str]:
    """Public endpoint: authenticated only by the Paddle signature over the raw body."""
    raw = await request.body()
    s = get_settings()
    if s.paddle_mode == "disabled" or not paddle.verify(raw, request.headers.get("paddle-signature"), paddle.webhook_secret(), tolerance_s=s.paddle_webhook_tolerance_seconds):
        WEBHOOKS.labels("bad_signature").inc()
        raise Unauthorized("Invalid signature.", code="bad_signature")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise Unprocessable("Body is not JSON.") from exc
    result = await subscriptions.apply_event(session, event)
    WEBHOOKS.labels(result).inc()
    return {"result": result}
