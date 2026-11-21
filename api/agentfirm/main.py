"""FastAPI application factory."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from agentfirm.core.config import get_settings
from agentfirm.core.db import assert_safe_db_role, dispose_engine, get_engine
from agentfirm.core.errors import NotFound, Unauthorized, install_error_handlers
from agentfirm.core.observability import REGISTRY, HttpMiddleware, configure_logging, refresh_execution_gauges
from agentfirm.core.security import public_jwk
from agentfirm.modules.agents.router import router as agents_router
from agentfirm.modules.audit.router import router as audit_router
from agentfirm.modules.billing.router import billing_router
from agentfirm.modules.billing.router import router as usage_router
from agentfirm.modules.conversations.router import router as conversations_router
from agentfirm.modules.gateway.router import router as admin_router
from agentfirm.modules.governance.platform import router as platform_router
from agentfirm.modules.governance.router import router as standing_router
from agentfirm.modules.ideas.router import router as ideas_router
from agentfirm.modules.identity.router import auth_router, members_router
from agentfirm.modules.integrations.router import router as integrations_router
from agentfirm.modules.knowledge.router import router as knowledge_router
from agentfirm.modules.memory.router import router as memories_router
from agentfirm.modules.projects.router import router as projects_router
from agentfirm.modules.tasks.router import approvals_router, artifacts_router
from agentfirm.modules.tasks.router import router as tasks_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_format, s.log_level)
    # Fail fast if the API role could bypass row-level security.
    await assert_safe_db_role(get_engine())
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AgentFirm API",
        version="0.3.0",
        description="Your AI team. Ready to work. — multi-tenant agent platform API.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",  # security review F-07
    )
    app.add_middleware(HttpMiddleware)  # outermost: request id, security headers, body limits, metrics
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type", "idempotency-key"],
    )

    v1 = APIRouter(prefix="/v1")
    for r in (
        auth_router,
        members_router,
        agents_router,
        projects_router,
        conversations_router,
        tasks_router,
        approvals_router,
        usage_router,
        billing_router,
        standing_router,
        platform_router,
        artifacts_router,
        audit_router,
        admin_router,
        knowledge_router,
        ideas_router,
        memories_router,
        integrations_router,
    ):
        v1.include_router(r)
    app.include_router(v1)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Ready = the database answers and, when configured, Redis does too (wake-ups and SSE)."""
        checks: dict[str, str] = {}
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        if get_settings().redis_url:
            from agentfirm.runtime.events import redis_client

            try:
                r = await redis_client()
                await r.ping()
                checks["redis"] = "ok"
            except Exception as exc:
                checks["redis"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        """Prometheus scrape. Bearer token required; not served at all without one."""
        token = get_settings().metrics_token
        if not token:
            raise NotFound("Not found.")
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
            raise Unauthorized("Metrics token required.")
        await refresh_execution_gauges()
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/.well-known/jwks.json", tags=["health"])
    async def jwks() -> dict[str, list[dict[str, str]]]:
        return {"keys": [public_jwk()]}

    return app


app = create_app()
