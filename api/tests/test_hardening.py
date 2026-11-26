"""Phase 7 hardening: security headers, request ids, body limits, metrics, readiness, safe artifact
downloads and the security-review fixes."""

from __future__ import annotations

import uuid

import pytest

from .conftest import register


async def test_security_headers_and_request_ids(client):
    r = await client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert len(r.headers["x-request-id"]) == 32
    r = await client.get("/healthz", headers={"X-Request-ID": "caddy-1234abcd"})
    assert r.headers["x-request-id"] == "caddy-1234abcd"  # kept for end-to-end correlation
    r = await client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.headers["x-request-id"] != "bad id\nwith newline" and len(r.headers["x-request-id"]) == 32


async def test_body_limits(client):
    a = await register(client, org="Big Body Co")
    big = b'{"objective": "' + b"x" * 1_100_000 + b'", "agents": ["creative"]}'
    r = await client.post("/v1/tasks", headers={**a.h, "content-type": "application/json"}, content=big)
    assert r.status_code == 413 and r.json()["title"] == "payload_too_large"

    async def chunks():  # no Content-Length: counted while streaming
        for _ in range(12):
            yield b"x" * 100_000

    r = await client.post("/v1/tasks", headers={**a.h, "content-type": "application/json"}, content=chunks())
    assert r.status_code == 413


async def test_metrics_need_a_token(client, monkeypatch):
    from agentfirm.core.config import get_settings

    assert (await client.get("/metrics")).status_code == 404  # not served without a configured token
    monkeypatch.setattr(get_settings(), "metrics_token", "s3cret-token")
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer nope"})).status_code == 401
    r = await client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 200
    body = r.text
    assert "agentfirm_http_requests_total" in body and 'agentfirm_executions{status="queued"}' in body
    assert 'route="/healthz"' in body  # route templates, never raw paths with ids


async def test_readiness_reports_dependencies(client):
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"


@pytest.mark.parametrize(
    ("name", "ok"),
    [("revenue_monthly", True), ("sales.orders", True), ("x; DROP TABLE y", False), ("a UNION SELECT 1", False), ('a"b', False), ("", False)],
)
def test_dataset_names_cannot_carry_sql(name, ok):
    from agentfirm.runtime.errors import StepError
    from agentfirm.runtime.programs.bi import select_all

    if ok:
        assert select_all(name).startswith('SELECT * FROM "')
    else:
        with pytest.raises(StepError):
            select_all(name)


async def test_artifact_download_is_org_scoped_and_sandboxed(client, owner_db):
    from agentfirm.runtime.artifacts import get_store, object_key

    a = await register(client, org="Artifact Co")
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Ideas", "agents": ["creative"]})).json()
    ex_id = uuid.UUID(t["executions"][0]["id"])
    ids = {}
    for name, kind, data in (
        ("chart.svg", "svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
        ("report.md", "md", b"# Report"),
    ):
        key = object_key(uuid.UUID(a.org_id), ex_id, name)
        await get_store().put(key, data, "application/octet-stream")
        aid = uuid.uuid4()
        await owner_db.execute(
            "INSERT INTO artifacts (id, org_id, execution_id, name, kind, size_bytes, storage_key) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            aid,
            uuid.UUID(a.org_id),
            ex_id,
            name,
            kind,
            len(data),
            key,
        )
        ids[kind] = str(aid)
    svg = await client.get(f"/v1/artifacts/{ids['svg']}", headers=a.h)
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in svg.headers["content-security-policy"] and "default-src 'none'" in svg.headers["content-security-policy"]
    assert svg.headers["content-disposition"].startswith("inline")
    md = await client.get(f"/v1/artifacts/{ids['md']}", headers=a.h)
    assert md.headers["content-disposition"] == 'attachment; filename="report.md"' and md.text == "# Report"
    other = await register(client, org="Other Artifact Co")
    assert (await client.get(f"/v1/artifacts/{ids['md']}", headers=other.h)).status_code == 404


async def test_concurrent_signups_with_the_same_workspace_name(client):
    """Regression (Phase 7 load test): same-name workspaces registering at once got a 500."""
    import asyncio

    async def signup(i: int):  # type: ignore[no-untyped-def]
        return await client.post(
            "/v1/auth/register",
            json={
                "email": f"race{i}.{uuid.uuid4().hex[:6]}@example.com",
                "name": "Race",
                "password": "Correct-Horse-9-battery",
                "organization_name": "Same Name Co",
            },
            headers={"X-Forwarded-For": f"10.9.0.{i}"},
        )

    results = await asyncio.gather(*(signup(i) for i in range(8)))
    assert [r.status_code for r in results] == [201] * 8, [r.text for r in results if r.status_code >= 400]
    assert len({r.json()["organization"]["slug"] for r in results}) == 8
