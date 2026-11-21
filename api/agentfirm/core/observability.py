"""Observability and HTTP hardening (Phase 7, ADR 0007).

* **Request IDs:** every request gets an `X-Request-ID` (a well-formed incoming one is kept, so
  Caddy/clients can correlate). It is put on every log line and returned on the response.
* **Structured logs:** one JSON object per line (`AGENTFIRM_LOG_FORMAT=json`, the production
  default), never containing secrets, tokens or request bodies.
* **Metrics:** Prometheus counters and histograms. The API serves `/metrics` (bearer token); the
  worker serves its own on a private port.
* **Hardening:** security headers on every API response, and request body limits (uploads 25 MB,
  everything else 1 MB) that apply to chunked bodies too.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

REGISTRY = CollectorRegistry(auto_describe=True)
HTTP_REQUESTS = Counter("agentfirm_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram(
    "agentfirm_http_request_duration_seconds",
    "HTTP request latency (time to response headers for streams)",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 2, 5, 10),
    registry=REGISTRY,
)
MODEL_CALLS = Counter("agentfirm_model_calls_total", "Model calls", ["provider", "capability", "outcome"], registry=REGISTRY)
CREDITS = Counter("agentfirm_credits_charged_total", "Credits charged for model usage", registry=REGISTRY)
TOOL_CALLS = Counter("agentfirm_tool_calls_total", "Tool calls", ["tool", "status"], registry=REGISTRY)
RUNS = Counter("agentfirm_worker_runs_total", "Execution turns finished by workers", ["kind", "outcome"], registry=REGISTRY)
WORKER_HEARTBEAT = Gauge("agentfirm_worker_heartbeat_timestamp_seconds", "Last worker loop iteration (unix time)", registry=REGISTRY)
WEBHOOKS = Counter("agentfirm_billing_webhooks_total", "Paddle webhooks by result", ["result"], registry=REGISTRY)
EXECUTIONS = Gauge("agentfirm_executions", "Executions by status (all organisations, counts only)", ["status"], registry=REGISTRY)
QUEUE_AGE = Gauge("agentfirm_queue_oldest_seconds", "Age of the oldest queued execution", registry=REGISTRY)

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
UPLOAD_PATHS = ("/v1/knowledge/documents",)
MAX_BODY = 1_000_000
MAX_UPLOAD = 25_000_000


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": REQUEST_ID.get(),
        }
        for k in ("method", "route", "status", "duration_ms", "execution_id", "org_id", "event"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(fmt: str = "json", level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    if fmt != "json":
        handler.addFilter(lambda r: setattr(r, "request_id", REQUEST_ID.get()) or True)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


access_log = logging.getLogger("agentfirm.access")

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class HttpMiddleware:
    """Pure ASGI (no response buffering, so SSE streams pass straight through)."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _RID.match(incoming) else uuid.uuid4().hex
        token = REQUEST_ID.set(rid)
        path: str = scope.get("path", "")
        limit = MAX_UPLOAD if path.startswith(UPLOAD_PATHS) else MAX_BODY
        start = time.perf_counter()
        status = 500

        async def reply(code: int, detail: str) -> None:
            body = json.dumps({"type": "about:blank", "title": "payload_too_large", "status": code, "detail": detail}).encode()
            await send({"type": "http.response.start", "status": code, "headers": [(b"content-type", b"application/problem+json"), (b"x-request-id", rid.encode()), *SECURITY_HEADERS]})
            await send({"type": "http.response.body", "body": body})

        try:
            declared = headers.get(b"content-length")
            if declared is not None and declared.isdigit() and int(declared) > limit:
                status = 413
                await reply(413, f"Request body is larger than {limit // 1_000_000} MB.")
                return
            app_receive = receive
            if declared is None and scope.get("method") in ("POST", "PUT", "PATCH"):
                # No Content-Length (chunked): read up to the limit first, then replay. Raising from
                # inside the app's body read would be swallowed into a 400 by the JSON parser.
                chunks: list[bytes] = []
                seen = 0
                while True:
                    msg = await receive()
                    if msg["type"] != "http.request":
                        break
                    seen += len(msg.get("body", b""))
                    if seen > limit:
                        status = 413
                        await reply(413, f"Request body is larger than {limit // 1_000_000} MB.")
                        return
                    chunks.append(msg.get("body", b""))
                    if not msg.get("more_body"):
                        break
                replay = [{"type": "http.request", "body": b"".join(chunks), "more_body": False}]

                async def replay_receive() -> dict[str, Any]:
                    return replay.pop() if replay else await receive()

                app_receive = replay_receive

            async def wrapped_send(msg: dict[str, Any]) -> None:
                nonlocal status
                if msg["type"] == "http.response.start":
                    status = msg["status"]
                    hs = list(msg.get("headers") or [])
                    names = {k.lower() for k, _ in hs}
                    hs.append((b"x-request-id", rid.encode()))
                    hs += [h for h in SECURITY_HEADERS if h[0] not in names]
                    if b"cache-control" not in names:
                        hs.append((b"cache-control", b"no-store"))
                    msg = {**msg, "headers": hs}
                await send(msg)

            await self.app(scope, app_receive, wrapped_send)
        finally:
            route = getattr(scope.get("route"), "path", None) or ("unmatched" if status == 404 else "other")
            elapsed = time.perf_counter() - start
            method = scope.get("method", "?")
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_LATENCY.labels(method, route).observe(elapsed)
            if route not in ("/healthz", "/metrics"):
                access_log.info(
                    "request",
                    extra={"method": method, "route": route, "status": status, "duration_ms": round(elapsed * 1000, 1)},
                )
            REQUEST_ID.reset(token)


ACTIVE_STATUSES = ("queued", "running", "waiting_approval", "paused", "blocked", "waiting_subtasks")


async def refresh_execution_gauges() -> None:
    """Counts only, via ops_execution_counts() (migration 0009)."""
    from sqlalchemy import text

    from agentfirm.core.db import sessionmaker

    async with sessionmaker()() as s:
        rows = (await s.execute(text("SELECT status, n, oldest_seconds FROM ops_execution_counts()"))).all()
    seen = {r[0]: r for r in rows}
    for st in ACTIVE_STATUSES:
        EXECUTIONS.labels(st).set(int(seen[st][1]) if st in seen else 0)
    QUEUE_AGE.set(float(seen["queued"][2] or 0) if "queued" in seen else 0.0)
