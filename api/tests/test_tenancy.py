"""Cross-tenant isolation at the API level.

`test_every_parameterised_route_is_classified` makes this suite self-maintaining:
any new route with a path parameter fails CI until someone states how it must
behave for a user from another organisation.
"""

from __future__ import annotations

import pytest

from .conftest import register, seed_execution_children


@pytest.fixture(scope="module")
async def world(client, owner_db):
    a = await register(client, org="Org A", name="Alice")
    b = await register(client, org="Org B", name="Bob")
    project = (await client.post("/v1/projects", headers=a.h, json={"name": "Secret project"})).json()
    conv = (await client.post("/v1/conversations", headers=a.h, json={"agent": "research", "title": "Secret chat", "project_id": project["id"]})).json()
    await client.post(f"/v1/conversations/{conv['id']}/messages", headers=a.h, json={"content": "confidential"})
    task = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Secret task", "agents": ["marketing"], "project_id": project["id"]})).json()
    seeded = await seed_execution_children(owner_db, org_id=a.org_id, execution_id=task["executions"][0]["id"])
    members = (await client.get("/v1/members", headers=a.h)).json()
    sessions = (await client.get("/v1/auth/sessions", headers=a.h)).json()
    doc = (await client.post("/v1/knowledge/documents", headers=a.h, json={"title": "Secret doc", "content": "Secret pricing notes."})).json()
    conn = (await client.post("/v1/integrations/connections", headers=a.h, json={"kind": "webhook", "name": "n8n", "config": {"url": "https://hooks.example.com/af", "actions": ["social.publish"]}})).json()
    idea_id = await owner_db.fetchval(
        "INSERT INTO ideas (id, org_id, title, summary, approach) VALUES (gen_random_uuid(), $1, 'Secret idea', 'x', 'divergent') RETURNING id::text", a.org_id
    )
    return {
        "a": a,
        "b": b,
        "project_id": project["id"],
        "conversation_id": conv["id"],
        "task_id": task["id"],
        "membership_id": members[0]["id"],
        "session_id": sessions[0]["id"],
        "document_id": doc["id"],
        "idea_id": idea_id,
        "connection_id": conn["id"],
        **seeded,
    }


# (method, path) → (url template using world keys, json body or None, expected status for the OTHER org)
CROSS_TENANT = {
    ("GET", "/v1/projects/{project_id}"): ("/v1/projects/{project_id}", None, 404),
    ("GET", "/v1/conversations/{conversation_id}/messages"): ("/v1/conversations/{conversation_id}/messages", None, 404),
    ("POST", "/v1/conversations/{conversation_id}/messages"): ("/v1/conversations/{conversation_id}/messages", {"content": "hi"}, 404),
    ("GET", "/v1/tasks/{task_id}"): ("/v1/tasks/{task_id}", None, 404),
    ("GET", "/v1/tasks/{task_id}/events"): ("/v1/tasks/{task_id}/events", None, 404),
    ("GET", "/v1/tasks/{task_id}/stream"): ("/v1/tasks/{task_id}/stream", None, 404),
    ("DELETE", "/v1/knowledge/documents/{document_id}"): ("/v1/knowledge/documents/{document_id}", None, 404),
    ("PATCH", "/v1/ideas/{idea_id}"): ("/v1/ideas/{idea_id}", {"column": "rejected"}, 404),
    ("PATCH", "/v1/integrations/connections/{connection_id}"): ("/v1/integrations/connections/{connection_id}", {"name": "x"}, 404),
    ("DELETE", "/v1/integrations/connections/{connection_id}"): ("/v1/integrations/connections/{connection_id}", None, 404),
    ("POST", "/v1/tasks/{task_id}/{action}"): ("/v1/tasks/{task_id}/cancel", None, 404),
    ("POST", "/v1/tasks/{task_id}/reply"): ("/v1/tasks/{task_id}/reply", {"message": "hi"}, 404),
    ("POST", "/v1/approvals/{approval_id}/decision"): ("/v1/approvals/{approval_id}/decision", {"decision": "approved"}, 404),
    ("PATCH", "/v1/members/{membership_id}"): ("/v1/members/{membership_id}", {"role": "viewer"}, 404),
    ("DELETE", "/v1/members/{membership_id}"): ("/v1/members/{membership_id}", None, 404),
    ("DELETE", "/v1/auth/sessions/{session_id}"): ("/v1/auth/sessions/{session_id}", None, 404),
}

# Routes whose parameter is not tenant data, with the reason.
EXEMPT = {
    ("GET", "/v1/agents/{key}"): "platform agent catalog (same for every org)",
    ("PUT", "/v1/memories/{key}"): "key is a name, not a row id; always writes the caller's org (test_runtime_api)",
    ("PATCH", "/v1/admin/providers/{provider_id}"): "super-admin only — covered in test_rbac",
    ("PUT", "/v1/admin/providers/{provider_id}/credential"): "super-admin only",
    ("PUT", "/v1/admin/routes/{capability}"): "super-admin only",
    ("GET", "/v1/admin/routes/{capability}/resolve"): "super-admin only",
    ("GET", "/v1/billing/invoices/{invoice_id}/pdf"): "cross-tenant 404 covered in test_billing (needs a Paddle-created invoice)",
    ("POST", "/v1/standing-approvals/{standing_id}/revoke"): "cross-tenant 404 covered in test_billing",
    ("GET", "/v1/artifacts/{artifact_id}"): "cross-tenant 404 covered in test_hardening (needs a stored artifact)",
    ("PUT", "/v1/admin/plans/{key}"): "super-admin only — test_billing",
    ("PUT", "/v1/admin/credit-packs/{key}"): "super-admin only — test_billing",
    ("POST", "/v1/admin/accounts/{org_id}/credits"): "super-admin only — test_billing",
    ("PUT", "/v1/admin/accounts/{org_id}/plan"): "super-admin only — test_billing",
    ("PUT", "/v1/admin/tools/{key}"): "super-admin only — test_billing",
    ("PATCH", "/v1/admin/agents/{key}"): "super-admin only — test_billing",
    ("POST", "/v1/admin/agents/{key}/rollback"): "super-admin only — test_billing",
}


def test_every_parameterised_route_is_classified():
    from agentfirm.main import create_app

    spec = create_app().openapi()
    missing = [
        (m.upper(), p) for p, ops in spec["paths"].items() if "{" in p for m in ops if (m.upper(), p) not in CROSS_TENANT and (m.upper(), p) not in EXEMPT
    ]
    assert not missing, f"Classify these routes in test_tenancy.py: {missing}"


@pytest.mark.parametrize("route", sorted(CROSS_TENANT), ids=lambda r: f"{r[0]} {r[1]}")
async def test_other_org_gets_404(client, world, route):
    template, body, expected = CROSS_TENANT[route]
    url = template.format(**world)
    r = await client.request(route[0], url, headers=world["b"].h, json=body)
    assert r.status_code == expected, (route, r.status_code, r.text)


async def test_lists_never_include_other_org_data(client, world):
    b = world["b"]
    for path in ("/v1/projects", "/v1/conversations", "/v1/tasks", "/v1/approvals", "/v1/members", "/v1/audit-logs", "/v1/knowledge/documents", "/v1/ideas", "/v1/memories", "/v1/integrations/connections"):
        r = await client.get(path, headers=b.h)
        assert r.status_code == 200, path
        text = r.text
        for key in ("project_id", "conversation_id", "task_id", "approval_id", "document_id", "idea_id", "connection_id"):
            assert world[key] not in text, (path, key)
        assert "Secret" not in text and "confidential" not in text
    usage = (await client.get("/v1/usage", headers=b.h)).json()
    assert usage["totals"]["requests"] == 0


async def test_cannot_attach_other_org_project(client, world):
    b = world["b"]
    r = await client.post("/v1/tasks", headers=b.h, json={"objective": "Sneaky", "agents": ["research"], "project_id": world["project_id"]})
    assert r.status_code == 404
    r = await client.post("/v1/conversations", headers=b.h, json={"agent": "research", "title": "x", "project_id": world["project_id"]})
    assert r.status_code == 404


async def test_owner_still_sees_own_data(client, world):
    a = world["a"]
    detail = (await client.get(f"/v1/tasks/{world['task_id']}", headers=a.h)).json()
    assert detail["approvals"][0]["id"] == world["approval_id"]
    assert detail["artifacts"][0]["id"] == world["artifact_id"]
    assert (await client.get("/v1/usage", headers=a.h)).json()["totals"]["requests"] == 1
