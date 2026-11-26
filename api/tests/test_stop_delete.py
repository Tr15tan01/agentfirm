"""Stop / terminate / delete: per task, per agent, per workspace and platform-wide."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from .conftest import register


async def _task(client, acct, agent="research", objective="Look into the market"):
    r = await client.post("/v1/tasks", headers=acct.h, json={"objective": objective, "agents": [agent]})
    assert r.status_code == 201, r.text
    return r.json()


async def _status(client, acct, task_id):
    return (await client.get(f"/v1/tasks/{task_id}", headers=acct.h)).json()["status"]


@pytest.fixture
async def admin(client, owner_db):
    acc = await register(client, org="Platform Ops", name="Root")
    await owner_db.execute("UPDATE users SET is_super_admin = true WHERE id = $1", uuid.UUID(acc.user_id))
    return acc


# ── delete ───────────────────────────────────────────────────────────────────


async def test_delete_task_stops_it_and_removes_it(client):
    a = await register(client, org="Del Co")
    t = await _task(client, a)
    r = await client.delete(f"/v1/tasks/{t['id']}", headers=a.h)
    assert r.status_code == 204
    assert (await client.get(f"/v1/tasks/{t['id']}", headers=a.h)).status_code == 404
    assert t["id"] not in [x["id"] for x in (await client.get("/v1/tasks", headers=a.h)).json()]


async def test_delete_is_workspace_scoped(client):
    a = await register(client, org="Owner Co")
    b = await register(client, org="Intruder Co")
    t = await _task(client, a)
    assert (await client.delete(f"/v1/tasks/{t['id']}", headers=b.h)).status_code == 404
    assert (await client.get(f"/v1/tasks/{t['id']}", headers=a.h)).status_code == 200


# ── stop all / one agent (workspace) ─────────────────────────────────────────


async def test_stop_one_agent_leaves_others_running(client):
    a = await register(client, org="Stop Co")
    r1 = await _task(client, a, "research")
    r2 = await _task(client, a, "research", "Second research job")
    m = await _task(client, a, "marketing", "Draft a campaign")
    out = (await client.post("/v1/tasks/stop", headers=a.h, json={"agent": "research"})).json()
    assert out == {"executions_stopped": 2, "tasks_affected": 2}
    assert await _status(client, a, r1["id"]) == "cancelled" and await _status(client, a, r2["id"]) == "cancelled"
    assert await _status(client, a, m["id"]) == "queued"


async def test_stop_all_in_workspace_does_not_touch_other_workspaces(client):
    a = await register(client, org="Mine Co")
    b = await register(client, org="Theirs Co")
    ta, tb = await _task(client, a), await _task(client, b)
    out = (await client.post("/v1/tasks/stop", headers=a.h, json={})).json()
    assert out["executions_stopped"] == 1
    assert await _status(client, a, ta["id"]) == "cancelled"
    assert await _status(client, b, tb["id"]) == "queued"
    # a body may not smuggle in another workspace
    await client.post("/v1/tasks/stop", headers=a.h, json={"org_id": str(uuid.uuid4())})
    assert await _status(client, b, tb["id"]) == "queued"


async def test_stop_unknown_agent_is_404_and_finished_tasks_are_left_alone(client):
    a = await register(client, org="Edge Co")
    assert (await client.post("/v1/tasks/stop", headers=a.h, json={"agent": "no_such_agent"})).status_code == 404
    t = await _task(client, a)
    await client.post(f"/v1/tasks/{t['id']}/cancel", headers=a.h)
    assert (await client.post("/v1/tasks/stop", headers=a.h, json={})).json()["executions_stopped"] == 0


# ── platform-wide (super-admin) ──────────────────────────────────────────────


async def test_super_admin_stops_one_agent_across_workspaces(client, admin):
    a, b = await register(client, org="WS One"), await register(client, org="WS Two")
    ra, rb = await _task(client, a, "research"), await _task(client, b, "research")
    mk = await _task(client, b, "marketing", "Draft a campaign")
    out = (await client.post("/v1/admin/agents/stop", headers=admin.h, json={"agent": "research"})).json()
    assert out["executions_stopped"] >= 2
    assert await _status(client, a, ra["id"]) == "cancelled" and await _status(client, b, rb["id"]) == "cancelled"
    assert await _status(client, b, mk["id"]) == "queued"
    # events were written in each workspace, so the task timelines show who stopped it
    ev = (await client.get(f"/v1/tasks/{ra['id']}/events", headers=a.h)).json()
    assert ev[-1]["payload"]["status"] == "cancelled" and ev[-1]["payload"]["action"] == "stop"


async def test_super_admin_stop_everything_and_restrict_to_one_workspace(client, admin):
    a, b = await register(client, org="Only A"), await register(client, org="Only B")
    ta, tb = await _task(client, a), await _task(client, b, "marketing", "Draft a campaign")
    out = (await client.post("/v1/admin/agents/stop", headers=admin.h, json={"org_id": a.org_id})).json()
    assert out["tasks_affected"] == 1
    assert await _status(client, a, ta["id"]) == "cancelled" and await _status(client, b, tb["id"]) == "queued"
    (await client.post("/v1/admin/agents/stop", headers=admin.h, json={})).json()
    assert await _status(client, b, tb["id"]) == "cancelled"


async def test_platform_stop_is_super_admin_only(client):
    a = await register(client, org="Plain Co")
    t = await _task(client, a)
    r = await client.post("/v1/admin/agents/stop", headers=a.h, json={})
    assert r.status_code in (401, 403, 404)
    assert await _status(client, a, t["id"]) == "queued"


async def _clear_queue(owner_db):
    await owner_db.execute("UPDATE task_executions SET status = 'cancelled', finished_at = now() WHERE status IN ('queued','running')")


# ── worker: a cancelled run is interrupted mid-call ──────────────────────────


async def test_worker_interrupts_a_cancelled_run_in_the_middle_of_a_slow_call(client, monkeypatch, owner_db):
    from agentfirm.worker import Worker

    a = await register(client, org="Hang Co")
    await _clear_queue(owner_db)  # the database is shared: make sure the worker claims *this* task
    t = await _task(client, a)

    async def hang(self, ex_id, org_id):  # stands in for a model call that never returns
        await asyncio.sleep(60)
        return "agent", "completed"

    monkeypatch.setattr(Worker, "_execute", hang)
    async with Worker(worker_id="hang-test", concurrency=1) as w:
        w.halt_poll = 0.2
        claimed = await w.claim(1)
        assert len(claimed) == 1
        run = asyncio.create_task(w.run_one(*claimed[0]))
        await asyncio.sleep(0.5)
        assert not run.done(), "the run is genuinely stuck"
        await client.post(f"/v1/tasks/{t['id']}/cancel", headers=a.h)
        started = time.monotonic()
        assert await asyncio.wait_for(run, timeout=10) == "halted"
        assert time.monotonic() - started < 5
    assert await _status(client, a, t["id"]) == "cancelled"


async def test_worker_interrupts_a_run_whose_task_was_deleted(client, monkeypatch, owner_db):
    from agentfirm.worker import Worker

    a = await register(client, org="Gone Co")
    await _clear_queue(owner_db)  # the database is shared: make sure the worker claims *this* task
    t = await _task(client, a)

    async def hang(self, ex_id, org_id):
        await asyncio.sleep(60)
        return "agent", "completed"

    monkeypatch.setattr(Worker, "_execute", hang)
    async with Worker(worker_id="gone-test", concurrency=1) as w:
        w.halt_poll = 0.2
        claimed = await w.claim(1)
        run = asyncio.create_task(w.run_one(*claimed[0]))
        await asyncio.sleep(0.5)
        assert (await client.delete(f"/v1/tasks/{t['id']}", headers=a.h)).status_code == 204
        assert await asyncio.wait_for(run, timeout=10) == "halted"
