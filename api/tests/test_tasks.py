"""Task Manager: idempotent creation, state machine, append-only events, approvals."""

from __future__ import annotations

from .conftest import register, seed_execution_children


async def test_idempotent_create(client):
    a = await register(client)
    h = {**a.h, "idempotency-key": "same-key-123"}
    r1 = await client.post("/v1/tasks", headers=h, json={"objective": "Research market", "agents": ["research", "bi"]})
    r2 = await client.post("/v1/tasks", headers=h, json={"objective": "Research market", "agents": ["research", "bi"]})
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert len((await client.get("/v1/tasks", headers=a.h)).json()) == 1


async def test_single_agent_task_pins_the_agent_version(client):
    a = await register(client)
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Launch plan", "agents": ["research"]})).json()
    assert [(e["kind"], e["agent"], e["agent_version"]) for e in t["executions"]] == [("agent", "research", "1.4.0")]
    assert t["executions"][0]["progress"] is None  # unknown until a plan exists — never invented


async def test_multi_agent_task_starts_with_an_orchestrator(client):
    a = await register(client)
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Launch plan", "agents": ["research", "marketing"]})).json()
    # Subtasks (with pinned versions) are created by the orchestrator when it plans, not by the API.
    assert [(e["kind"], e["agent"]) for e in t["executions"]] == [("orchestrator", "orchestrator")]
    assert t["executions"][0]["progress"] is None
    # Agent parameters belong to single-agent tasks; a multi-agent task takes only a budget.
    bad = await client.post("/v1/tasks", headers=a.h, json={"objective": "Launch plan", "agents": ["research", "bi"], "parameters": {"depth": "deep"}})
    assert bad.status_code == 422
    ok = await client.post("/v1/tasks", headers=a.h, json={"objective": "Launch plan", "agents": [], "parameters": {"max_credits": 400}})
    assert ok.status_code == 201


async def test_state_machine_and_events(client):
    a = await register(client)
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Write report", "agents": ["bi"]})).json()
    assert (await client.post(f"/v1/tasks/{t['id']}/pause", headers=a.h)).json()["status"] == "paused"
    assert (await client.post(f"/v1/tasks/{t['id']}/pause", headers=a.h)).status_code == 409
    assert (await client.post(f"/v1/tasks/{t['id']}/resume", headers=a.h)).json()["status"] == "queued"
    assert (await client.post(f"/v1/tasks/{t['id']}/cancel", headers=a.h)).json()["status"] == "cancelled"
    retried = (await client.post(f"/v1/tasks/{t['id']}/retry", headers=a.h)).json()
    assert retried["status"] == "queued" and len(retried["executions"]) == 2  # history preserved

    events = (await client.get(f"/v1/tasks/{t['id']}/events", headers=a.h)).json()
    assert [e["payload"]["status"] for e in events] == ["queued", "paused", "queued", "cancelled", "queued"]
    first_exec = [e for e in events if e["execution_id"] == t["executions"][0]["id"]]
    assert [e["seq"] for e in first_exec] == [1, 2, 3, 4]
    tail = (await client.get(f"/v1/tasks/{t['id']}/events?after=3", headers=a.h)).json()
    assert all(e["seq"] > 3 for e in tail)


async def test_approval_decision_once(client, owner_db):
    a = await register(client)
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Post launch", "agents": ["marketing"]})).json()
    seeded = await seed_execution_children(owner_db, org_id=a.org_id, execution_id=t["executions"][0]["id"])
    pending = (await client.get("/v1/approvals?status=pending", headers=a.h)).json()
    assert [p["id"] for p in pending] == [seeded["approval_id"]]
    r = await client.post(f"/v1/approvals/{seeded['approval_id']}/decision", headers=a.h, json={"decision": "approved", "note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    again = await client.post(f"/v1/approvals/{seeded['approval_id']}/decision", headers=a.h, json={"decision": "rejected"})
    assert again.status_code == 409


async def test_unknown_agent_rejected(client):
    a = await register(client)
    r = await client.post("/v1/tasks", headers=a.h, json={"objective": "x" * 10, "agents": ["hacker"]})
    assert r.status_code == 404
