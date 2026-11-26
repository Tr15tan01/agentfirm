"""Connections API and live connector adapters (GitHub, webhook, GN7T, OSV, SMTP, sandbox).

Live adapters run against respx-mocked upstreams with AGENTFIRM_CONNECTOR_MODE switched to
"live" for the test; nothing here touches the network.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import socket
import uuid
from types import SimpleNamespace

import pytest
import respx

from agentfirm.agents.contracts import ErrorCode
from agentfirm.runtime.errors import StepError

from .conftest import join_as, register


@contextlib.contextmanager
def live_connectors():
    from agentfirm.core.config import get_settings

    s = get_settings()
    saved = s.connector_mode
    s.connector_mode = "live"
    try:
        yield
    finally:
        s.connector_mode = saved


def ctx_for(org_id: str):  # type: ignore[no-untyped-def]
    return SimpleNamespace(org_id=uuid.UUID(org_id), execution_id=uuid.uuid4())


# ── Connections API ──────────────────────────────────────────────────────────


async def test_connection_secrets_are_write_only_and_audited(client, owner_db):
    a = await register(client, org="Conn Co")
    r = await client.post(
        "/v1/integrations/connections",
        headers=a.h,
        json={"kind": "github", "name": "GitHub", "config": {"repositories": ["acme/app"]}, "secret": "ghp_supersecrettoken1234"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["secret_last4"] == "1234" and "supersecret" not in r.text
    assert body["config"] == {"repositories": ["acme/app"], "default_repository": "acme/app", "api_base": "https://api.github.com"}
    listed = (await client.get("/v1/integrations/connections", headers=a.h)).text
    assert "supersecret" not in listed
    stored = await owner_db.fetchrow("SELECT ciphertext, config FROM connections WHERE id = $1", uuid.UUID(body["id"]))
    assert b"supersecret" not in stored["ciphertext"], "secret is encrypted at rest"
    actions = [r["action"] for r in await owner_db.fetch("SELECT action FROM audit_logs WHERE target_id = $1", body["id"])]
    assert "integration.connected" in actions


async def test_webhook_signing_secret_generated_once(client):
    a = await register(client, org="Hook Co")
    r = await client.post(
        "/v1/integrations/connections",
        headers=a.h,
        json={"kind": "webhook", "name": "n8n", "config": {"url": "https://hooks.example.com/af", "actions": ["social.publish"]}},
    )
    assert r.status_code == 201
    assert r.json()["signing_secret"].startswith("whsec_")
    assert all(c.get("signing_secret") is None for c in (await client.get("/v1/integrations/connections", headers=a.h)).json())


@pytest.mark.parametrize(
    ("kind", "config", "secret", "message"),
    [
        ("webhook", {"url": "http://hooks.example.com/x", "actions": ["social.publish"]}, None, "https"),
        ("webhook", {"url": "https://hooks.example.com/x", "actions": ["rm.rf"]}, None, "subset"),
        ("github", {"repositories": ["not a repo"]}, "t", "owner/name"),
        ("github", {"repositories": ["a/b"]}, None, "token"),
        ("smtp", {"host": "smtp.example.com", "port": 25, "from_address": "a@example.com"}, "p", "TLS ports"),
        ("gn7t", {"base_url": "https://gn7t.example.com"}, None, "API key"),
    ],
)
async def test_connection_validation(client, kind, config, secret, message):
    a = await register(client, org=f"Val {kind}")
    r = await client.post("/v1/integrations/connections", headers=a.h, json={"kind": kind, "name": "x", "config": config, "secret": secret})
    assert r.status_code == 422 and message in r.text


async def test_connection_urls_must_be_public(client):
    from agentfirm.runtime.tools import web

    a = await register(client, org="SSRF Conn")
    saved = web.RESOLVER
    web.RESOLVER = lambda h: [(socket.AF_INET, 0, 0, "", ("10.0.0.5", 0))]
    try:
        r = await client.post(
            "/v1/integrations/connections",
            headers=a.h,
            json={"kind": "webhook", "name": "x", "config": {"url": "https://internal.example.com/x", "actions": ["social.publish"]}},
        )
    finally:
        web.RESOLVER = saved
    assert r.status_code == 422 and "not allowed" in r.text


async def test_only_admins_manage_connections(client):
    a = await register(client, org="Perm Conn")
    m = await join_as(client, a, "member", name="Mo")
    r = await client.post(
        "/v1/integrations/connections",
        headers=m.h,
        json={"kind": "webhook", "name": "x", "config": {"url": "https://hooks.example.com/x", "actions": ["social.publish"]}},
    )
    assert r.status_code == 403
    assert (await client.get("/v1/integrations/connections", headers=m.h)).status_code == 200


# ── Webhook connector ────────────────────────────────────────────────────────


@respx.mock
async def test_webhook_is_signed_idempotent_and_never_follows_redirects(client):
    from agentfirm.runtime import connectors

    a = await register(client, org="Sign Co")
    secret = (
        await client.post(
            "/v1/integrations/connections",
            headers=a.h,
            json={"kind": "webhook", "name": "n8n", "config": {"url": "https://hooks.example.com/af", "actions": ["social.publish"]}},
        )
    ).json()["signing_secret"]
    route = respx.post("https://hooks.example.com/af").respond(200, json={"status": "published", "url": "https://x/1"})
    with live_connectors():
        out = await connectors.webhook(ctx_for(a.org_id), "social.publish", {"text": "Hi"}, "exec:step:social.publish:0")
    assert out["status"] == "published" and out["via"] == "n8n"
    req = route.calls[0].request
    t, v1 = (kv.split("=", 1)[1] for kv in req.headers["x-agentfirm-signature"].split(","))
    expected = hmac.new(secret.encode(), f"{t}.".encode() + req.content, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(v1, expected), "receivers can verify the HMAC signature"
    assert req.headers["idempotency-key"] == "exec:step:social.publish:0"
    assert json.loads(req.content)["args"] == {"text": "Hi"}

    respx.post("https://hooks.example.com/af").respond(302, headers={"location": "http://169.254.169.254/"})
    with live_connectors(), pytest.raises(StepError) as e:
        await connectors.webhook(ctx_for(a.org_id), "social.publish", {}, "k2")
    assert e.value.code == ErrorCode.TOOL_ERROR


async def test_missing_connection_asks_the_user(client):
    from agentfirm.runtime import connectors

    a = await register(client, org="No Conn")
    with live_connectors(), pytest.raises(StepError) as e:
        await connectors.webhook(ctx_for(a.org_id), "payments.execute", {}, "k")
    assert e.value.code == ErrorCode.MISSING_CONTEXT and "Settings → Integrations" in e.value.message


@respx.mock
@pytest.mark.parametrize(
    ("status", "code", "retriable"), [(401, ErrorCode.PERMISSION_DENIED, False), (503, ErrorCode.TOOL_ERROR, True), (422, ErrorCode.TOOL_ERROR, False)]
)
async def test_webhook_errors_are_classified(client, status, code, retriable):
    from agentfirm.runtime import connectors

    a = await register(client, org=f"Err {status}")
    await client.post(
        "/v1/integrations/connections",
        headers=a.h,
        json={"kind": "webhook", "name": "n8n", "config": {"url": "https://hooks.example.com/af", "actions": ["calendar.read"]}},
    )
    respx.post("https://hooks.example.com/af").respond(status, text="nope")
    with live_connectors(), pytest.raises(StepError) as e:
        await connectors.webhook(ctx_for(a.org_id), "calendar.read", {}, "k")
    assert (e.value.code, e.value.retriable) == (code, retriable)


# ── GitHub connector ─────────────────────────────────────────────────────────


@respx.mock
async def test_github_writes_only_agent_branches_of_allowed_repos(client):
    from agentfirm.runtime.connectors import github

    a = await register(client, org="Git Co")
    await client.post(
        "/v1/integrations/connections",
        headers=a.h,
        json={"kind": "github", "name": "GitHub", "config": {"repositories": ["acme/app"]}, "secret": "ghp_token_abcd"},
    )
    base = "https://api.github.com/repos/acme/app"
    respx.get(base).respond(200, json={"default_branch": "main"})
    respx.get(f"{base}/branches/agent/fix-1").respond(404, json={"message": "Branch not found"})
    respx.get(f"{base}/git/ref/heads/main").respond(200, json={"object": {"sha": "basesha"}})
    respx.get(f"{base}/git/commits/basesha").respond(200, json={"tree": {"sha": "treesha"}})
    tree = respx.post(f"{base}/git/trees").respond(201, json={"sha": "newtree"})
    respx.post(f"{base}/git/commits").respond(201, json={"sha": "newcommit"})
    ref = respx.post(f"{base}/git/refs").respond(201, json={})
    respx.get(f"{base}/contents/app/x.py").respond(200, json={"encoding": "base64", "content": base64.b64encode(b"print(1)\n").decode()})

    with live_connectors():
        gh = await github.client(ctx_for(a.org_id), "acme/app")
        assert await gh.read("app/x.py", "main") == "print(1)\n"
        out = await gh.write("agent/fix-1", "main", {"app/x.py": "print(2)\n"}, "fix")
        assert out == {"branch": "agent/fix-1", "commit": "newcommit", "files": ["app/x.py"]}
        assert json.loads(tree.calls[0].request.content)["base_tree"] == "treesha"
        assert json.loads(ref.calls[0].request.content) == {"ref": "refs/heads/agent/fix-1", "sha": "newcommit"}
        assert tree.calls[0].request.headers["authorization"] == "Bearer ghp_token_abcd"
        with pytest.raises(StepError, match="not one of the repositories"):
            await github.client(ctx_for(a.org_id), "acme/other")

    for bad in ("main", "feature/x", "agent/../main"):
        with pytest.raises(StepError, match="agent/"):
            github._check_branch(bad)
    for path in ("/etc/passwd", "../x", ".git/config", ".github/workflows/deploy.yml"):
        with pytest.raises(StepError):
            github._check_paths({path: "x"})


# ── GN7T, OSV, SMTP, sandbox, schedules ──────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM payments",
        "SELECT 1; DROP TABLE x",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "UPDATE t SET a=1",
        "select * from t; select 2",
        "COPY t TO '/tmp/x'",
    ],
)
def test_gn7t_queries_must_be_read_only(query):
    from agentfirm.runtime.connectors.services import assert_read_only

    with pytest.raises(StepError) as e:
        assert_read_only(query)
    assert e.value.code == ErrorCode.POLICY_VIOLATION


def test_gn7t_allows_selects_with_comments_and_literals():
    from agentfirm.runtime.connectors.services import assert_read_only

    assert assert_read_only("-- monthly\nSELECT month, sum(amount) FROM payments WHERE note = 'drop it' GROUP BY 1;").startswith("SELECT")


@respx.mock
async def test_gn7t_live_queries_fail_clearly_without_calling_missing_routes(client):
    from agentfirm.runtime.connectors import services

    a = await register(client, org="Data Co")
    await client.post(
        "/v1/integrations/connections",
        headers=a.h,
        json={"kind": "gn7t", "name": "GN7T", "config": {"base_url": "https://gn7t.example.com"}, "secret": "gk_123456"},
    )
    query_route = respx.post("https://gn7t.example.com/v1/query").respond(200, json={})
    datasets_route = respx.get("https://gn7t.example.com/v1/datasets").respond(200, json={})
    with live_connectors():
        with pytest.raises(StepError) as q:
            await services.gn7t_query(ctx_for(a.org_id), "SELECT month, revenue FROM revenue_monthly", 100)
        with pytest.raises(StepError) as d:
            await services.gn7t_datasets(ctx_for(a.org_id))
    assert q.value.code == ErrorCode.TOOL_ERROR and d.value.code == ErrorCode.TOOL_ERROR
    assert "not available" in str(q.value)
    assert not query_route.called and not datasets_route.called


@respx.mock
async def test_osv_audit_parses_pins_and_maps_results():
    from agentfirm.runtime.connectors import services

    pkgs = services.parse_manifests(
        {
            "requirements.txt": "requests==2.19.0\nflask>=2\n# c\nhttpx==0.27.0  # pinned",
            "web/package.json": json.dumps({"dependencies": {"lodash": "4.17.15", "react": "^18"}}),
        }
    )
    assert pkgs == [("PyPI", "requests", "2.19.0"), ("PyPI", "httpx", "0.27.0"), ("npm", "lodash", "4.17.15")]
    respx.post("https://api.osv.dev/v1/querybatch").respond(200, json={"results": [{"vulns": [{"id": "GHSA-1"}]}, {}, {"vulns": [{"id": "GHSA-2"}]}]})
    with live_connectors():
        found = await services.osv_audit(pkgs)
    assert [(f["package"], f["id"]) for f in found] == [("requests", "GHSA-1"), ("lodash", "GHSA-2")]


async def test_smtp_requires_tls_and_sends_once(client, monkeypatch):
    import smtplib

    from agentfirm.runtime.connectors import services

    sent: list[dict] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):  # type: ignore[no-untyped-def]
            self.tls = False

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *a):  # type: ignore[no-untyped-def]
            return False

        def starttls(self, context):  # type: ignore[no-untyped-def]
            self.tls = True

        def login(self, u, p):  # type: ignore[no-untyped-def]
            assert self.tls, "credentials are never sent before STARTTLS"
            assert (u, p) == ("mailer@example.com", "app-password-9")

        def send_message(self, msg):  # type: ignore[no-untyped-def]
            sent.append({"to": msg["To"], "subject": msg["Subject"], "id": msg["Message-ID"]})

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    a = await register(client, org="Mail Co")
    await client.post(
        "/v1/integrations/connections",
        headers=a.h,
        json={
            "kind": "smtp",
            "name": "Mail",
            "config": {"host": "smtp.example.com", "port": 587, "from_address": "mailer@example.com"},
            "secret": "app-password-9",
        },
    )
    with live_connectors():
        out = await services.send_email(ctx_for(a.org_id), to=["x@example.com"], cc=[], subject="Notes", body="Hi", idempotency_key="e:s:email.send:0")
    assert out["sent"] and sent == [{"to": "x@example.com", "subject": "Notes", "id": "<e.s.email.send.0@agentfirm>"}]


async def test_sandbox_backends():
    from agentfirm.core.config import get_settings
    from agentfirm.runtime.connectors import fixtures as fx
    from agentfirm.runtime.connectors import sandbox

    cmd = sandbox.docker_command("/tmp/w", "pytest -q")
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "no-new-privileges", "--pids-limit", "--user", "10001:10001"):
        assert flag in cmd
    out = await sandbox.run({"tests/test_a.py": "def test_one():\n    pass\ndef test_two():\n    pass\n"}, "pytest -q", timeout_s=10)
    assert out["fixture"] and out["passed"] == 2 and "no code was executed" in out["output"]
    fx.WORLD.sandbox.unavailable = True
    with pytest.raises(StepError, match="unavailable"):
        await sandbox.run({}, "pytest", timeout_s=10)
    s = get_settings()
    s.sandbox_backend = "disabled"
    try:
        with pytest.raises(StepError, match="disabled"):
            await sandbox.run({}, "pytest", timeout_s=10)
    finally:
        s.sandbox_backend = "fixture"


def test_production_refuses_fixture_modes():
    from agentfirm.core.config import Settings

    with pytest.raises(RuntimeError, match="CONNECTOR_MODE"):
        Settings(
            env="production", gateway_mode="live", web_mode="live", connector_mode="fixture", sandbox_backend="docker", jwt_private_key="x", master_key="x"
        )
    with pytest.raises(RuntimeError, match="SANDBOX_BACKEND"):
        Settings(env="production", gateway_mode="live", web_mode="live", connector_mode="live", sandbox_backend="fixture", jwt_private_key="x", master_key="x")


def test_cadences():
    from datetime import UTC, datetime

    from agentfirm.runtime.schedules import CadenceError, next_run

    t = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)  # a Tuesday
    assert next_run("weekly:mon@08:00", "Europe/Berlin", t) == datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
    assert next_run("daily@08:00", "UTC", t) == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    assert next_run("monthly:1@09:30", "America/New_York", t) == datetime(2026, 12, 1, 14, 30, tzinfo=UTC)
    assert next_run("daily@07:00", "Europe/Berlin", datetime(2026, 3, 28, 12, 0, tzinfo=UTC)) == datetime(2026, 3, 29, 5, 0, tzinfo=UTC), (
        "DST: 07:00 local after the spring change"
    )
    for bad in ("0 8 * * 1", "weekly:funday@08:00", "monthly:31@08:00", "daily@25:00"):
        with pytest.raises(CadenceError):
            next_run(bad, "UTC", t)
    with pytest.raises(CadenceError):
        next_run("daily@08:00", "Mars/Olympus", t)


async def test_unresolvable_connection_host_is_a_validation_error(client):
    from agentfirm.runtime.tools import web

    a = await register(client, org="DNS Co")
    saved = web.RESOLVER

    def fail(h):  # type: ignore[no-untyped-def]
        raise socket.gaierror(-2, "Name or service not known")

    web.RESOLVER = fail
    try:
        r = await client.post(
            "/v1/integrations/connections",
            headers=a.h,
            json={"kind": "webhook", "name": "x", "config": {"url": "https://nowhere.invalid/x", "actions": ["social.publish"]}},
        )
    finally:
        web.RESOLVER = saved
    assert r.status_code == 422 and "could not be resolved" in r.text
