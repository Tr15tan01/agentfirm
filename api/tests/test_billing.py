"""Phase 6: plans, credits and limits (server-side), Paddle billing (signed webhooks, fixture checkout),
super-admin administration, tool kill-switch, standing approvals and replying to resume a task."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest

from .conftest import join_as, register
from .test_runtime import corpus, detail, drain, events, executable_agents  # noqa: F401

pytestmark = pytest.mark.usefixtures("executable_agents")


@pytest.fixture
async def root(client, owner_db):
    acc = await register(client, org="Platform Ops", name="Root")
    await owner_db.execute("UPDATE users SET is_super_admin = true WHERE id = $1", uuid.UUID(acc.user_id))
    return acc


@pytest.fixture
async def plans(client, root, owner_db):
    """Pro and a credit pack for sale (as a super-admin would set them up), small test limits."""
    pro = {"name": "Pro", "monthly_credits": 5000, "max_seats": 5, "max_concurrent_tasks": 5, "price_cents": 4900, "paddle_price_id": "pri_test_pro", "sort": 1}
    biz = {"name": "Business", "monthly_credits": 20000, "max_seats": 20, "max_concurrent_tasks": 10, "price_cents": 19900, "paddle_price_id": "pri_test_business", "sort": 2}
    assert (await client.put("/v1/admin/plans/pro", headers=root.h, json=pro)).status_code == 200
    assert (await client.put("/v1/admin/plans/business", headers=root.h, json=biz)).status_code == 200
    pack = {"name": "Top-up 1k", "credits": 1000, "price_cents": 900, "paddle_price_id": "pri_test_pack"}
    assert (await client.put("/v1/admin/credit-packs/k1", headers=root.h, json=pack)).status_code == 200
    yield
    await owner_db.execute("UPDATE plans SET paddle_price_id = NULL, price_cents = NULL WHERE key IN ('pro', 'business')")
    await owner_db.execute("UPDATE credit_packs SET is_active = false")


async def balance(owner_db, acc) -> tuple[int, int]:
    r = await owner_db.fetchrow("SELECT plan_remaining, purchased_remaining FROM credit_balances WHERE org_id = $1", uuid.UUID(acc.org_id))
    return r["plan_remaining"], r["purchased_remaining"]


async def set_plan_limits(owner_db, acc, **limits: Any) -> None:
    """Give one org its own plan with the given limits (tests only)."""
    key = f"t{uuid.uuid4().hex[:10]}"
    cols = {"monthly_credits": 1000, "max_seats": 10, "max_concurrent_tasks": 10, **limits}
    await owner_db.execute(
        "INSERT INTO plans (key, name, monthly_credits, max_seats, max_concurrent_tasks, agents, is_public) VALUES ($1, 'Test', $2, $3, $4, $5::jsonb, false)",
        key,
        cols["monthly_credits"],
        cols["max_seats"],
        cols["max_concurrent_tasks"],
        json.dumps(cols.get("agents")) if cols.get("agents") is not None else None,
    )
    await owner_db.execute("UPDATE subscriptions SET plan_key = $1, provider = 'manual' WHERE org_id = $2", key, uuid.UUID(acc.org_id))


# ── Paddle signatures ────────────────────────────────────────────────────────


def test_paddle_signature_verification():
    from agentfirm.modules.billing.paddle import sign, verify

    raw = b'{"event_id":"evt_1"}'
    header = sign(raw, "secret")
    assert verify(raw, header, "secret", tolerance_s=300)
    assert not verify(raw + b" ", header, "secret", tolerance_s=300)  # body tampered (raw bytes, not re-serialised JSON)
    assert not verify(raw, header, "other", tolerance_s=300)
    old = sign(raw, "secret", ts=int(time.time()) - 3600)
    assert not verify(raw, old, "secret", tolerance_s=300)  # replay outside the window
    rotated = f"{sign(raw, 'secret')};h1={'0' * 64}"
    assert verify(raw, rotated, "secret", tolerance_s=300)  # any h1 may match during secret rotation
    assert not verify(raw, None, "secret", tolerance_s=300) and not verify(raw, "garbage", "secret", tolerance_s=300)


async def test_webhook_rejects_bad_signatures(client):
    r = await client.post("/v1/billing/paddle/webhook", content=b'{"event_id":"e","event_type":"x","data":{}}', headers={"Paddle-Signature": "ts=1;h1=00"})
    assert r.status_code == 401


# ── plans, credits and limits ────────────────────────────────────────────────


async def test_new_workspace_starts_on_free_plan_with_credits(client, owner_db):
    a = await register(client, org="Fresh Co")
    acc = (await client.get("/v1/billing/account", headers=a.h)).json()
    assert acc["plan"]["key"] == "free" and acc["status"] == "active" and acc["provider"] == "none"
    assert acc["credits_available"] == acc["credits_plan_monthly"] == acc["credits_plan_remaining"] > 0
    assert acc["seats_used"] == 1 and acc["can_manage"] is True
    member = await join_as(client, a, "member", name="Meg")
    m = (await client.get("/v1/billing/account", headers=member.h)).json()
    assert m["can_manage"] is False
    assert (await client.post("/v1/billing/checkout", headers=member.h, json={"plan": "pro"})).status_code == 403


async def test_usage_draws_plan_credits_first_and_stops_at_zero(client, owner_db, corpus):  # noqa: F811
    a = await register(client, org="Meter Co")
    await owner_db.execute("UPDATE credit_balances SET plan_remaining = 3, purchased_remaining = 100 WHERE org_id = $1", uuid.UUID(a.org_id))
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Brainstorm names for a tutoring app", "agents": ["creative"]})).json()
    await drain()
    used = (await detail(client, a, t["id"]))["executions"][0]["credits_used"]
    plan_left, bought = await balance(owner_db, a)
    assert used > 3 and plan_left == 0 and bought == 100 - (used - 3)

    await owner_db.execute("UPDATE credit_balances SET plan_remaining = 0, purchased_remaining = 0 WHERE org_id = $1", uuid.UUID(a.org_id))
    r = await client.post("/v1/tasks", headers=a.h, json={"objective": "Brainstorm more names", "agents": ["creative"]})
    assert r.status_code == 402 and r.json()["title"] == "out_of_credits"


async def test_running_task_stops_when_credits_run_out(client, owner_db):
    a = await register(client, org="Drained Co")
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Brainstorm names for a tutoring app", "agents": ["creative"]})).json()
    await owner_db.execute("UPDATE credit_balances SET plan_remaining = 0, purchased_remaining = 0 WHERE org_id = $1", uuid.UUID(a.org_id))
    await drain()
    ex = (await detail(client, a, t["id"]))["executions"][0]
    assert ex["credits_used"] == 0  # no model call was made
    assert ex["status"] in ("failed", "completed") and "out of credits" in json.dumps(ex["result"])


async def test_plan_limits_concurrency_seats_and_agents(client, owner_db):
    a = await register(client, org="Limits Co")
    await set_plan_limits(owner_db, a, max_concurrent_tasks=1, max_seats=1, agents=["creative"])
    assert (await client.post("/v1/tasks", headers=a.h, json={"objective": "Ideas", "agents": ["creative"]})).status_code == 201
    r = await client.post("/v1/tasks", headers=a.h, json={"objective": "More ideas", "agents": ["creative"]})
    assert r.status_code == 429 and r.json()["title"] == "plan_concurrency"
    await drain()
    r = await client.post("/v1/tasks", headers=a.h, json={"objective": "Research X", "agents": ["research"]})
    assert r.status_code == 402 and r.json()["title"] == "plan_agent"
    r = await client.post("/v1/members/invitations", headers=a.h, json={"email": "x@example.com", "role": "member"})
    assert r.status_code == 402 and r.json()["title"] == "plan_seats"


async def test_free_allowance_rolls_over_monthly(client, owner_db):
    a = await register(client, org="Roll Co")
    await owner_db.execute(
        "UPDATE credit_balances SET plan_remaining = 7, period_start = now() - interval '40 days', period_end = now() - interval '10 days' WHERE org_id = $1", uuid.UUID(a.org_id)
    )
    from agentfirm.worker import Worker

    async with Worker(worker_id="roll", concurrency=1) as w:
        assert await w.roll_credit_periods() >= 1
    acc = (await client.get("/v1/billing/account", headers=a.h)).json()
    assert acc["credits_plan_remaining"] == acc["credits_plan_monthly"]
    ledger = (await client.get("/v1/billing/ledger", headers=a.h)).json()
    assert ledger[0]["reason"] == "period_grant"


# ── Paddle checkout (fixture mode) ───────────────────────────────────────────


async def test_subscribe_upgrade_topup_and_cancel(client, owner_db, root, plans):
    from agentfirm.modules.billing import paddle

    a = await register(client, org="Paying Co")
    cat = (await client.get("/v1/billing/catalog", headers=a.h)).json()
    assert {p["key"]: p["purchasable"] for p in cat["plans"]} == {"free": False, "pro": True, "business": True}

    co = (await client.post("/v1/billing/checkout", headers=a.h, json={"plan": "pro"})).json()
    assert "_ptxn=txn_fixture" in co["checkout_url"]
    txn = paddle.FIXTURE.transactions[co["transaction_id"]]
    assert txn["custom_data"] == {"org_id": a.org_id, "kind": "subscription", "key": "pro"}  # set by the server, not the browser
    other = await register(client, org="Other Co")
    assert (await client.post(f"/v1/billing/fixture/checkout/{co['transaction_id']}/complete", headers=other.h)).status_code == 404
    done = (await client.post(f"/v1/billing/fixture/checkout/{co['transaction_id']}/complete", headers=a.h)).json()
    assert done["events"] == ["processed", "processed"]

    acc = (await client.get("/v1/billing/account", headers=a.h)).json()
    assert (acc["plan"]["key"], acc["provider"], acc["status"], acc["credits_plan_remaining"]) == ("pro", "paddle", "active", 5000)
    inv = (await client.get("/v1/billing/invoices", headers=a.h)).json()
    assert len(inv) == 1 and inv[0]["total_cents"] == 4900 and inv[0]["description"] == "Pro plan"
    assert (await client.get(f"/v1/billing/invoices/{inv[0]['id']}/pdf", headers=other.h)).status_code == 404  # cross-tenant

    # Replaying a webhook changes nothing.
    ev = await owner_db.fetchval("SELECT payload FROM billing_events WHERE type = 'subscription.created' AND subject_org_id = $1", uuid.UUID(a.org_id))
    raw = paddle.encode(json.loads(ev) if isinstance(ev, str) else ev)
    r = await client.post("/v1/billing/paddle/webhook", content=raw, headers={"Paddle-Signature": paddle.sign(raw, paddle.FIXTURE_SECRET)})
    assert r.json() == {"result": "duplicate"}

    # Upgrade: Paddle's API is asked to switch the price; its webhook then applies it mid-period.
    await owner_db.execute("UPDATE credit_balances SET plan_remaining = 4000 WHERE org_id = $1", uuid.UUID(a.org_id))
    assert (await client.post("/v1/billing/checkout", headers=a.h, json={"plan": "business"})).json()["changed"] is True
    sub_id = await owner_db.fetchval("SELECT provider_subscription_id FROM subscriptions WHERE org_id = $1", uuid.UUID(a.org_id))
    assert paddle.FIXTURE.changes[-1] == (sub_id, "pri_test_business")
    sub = {**paddle.FIXTURE.subscriptions[sub_id], "items": [{"price": {"id": "pri_test_business"}, "quantity": 1}]}
    upd = {"event_id": f"evt_{uuid.uuid4().hex}", "event_type": "subscription.updated", "occurred_at": "2026-11-17T10:00:00Z", "data": sub}
    raw = paddle.encode(upd)
    assert (await client.post("/v1/billing/paddle/webhook", content=raw, headers={"Paddle-Signature": paddle.sign(raw, paddle.FIXTURE_SECRET)})).json() == {"result": "processed"}
    acc = (await client.get("/v1/billing/account", headers=a.h)).json()
    assert acc["plan"]["key"] == "business" and acc["credits_plan_remaining"] == 4000 + (20000 - 5000)

    # Top-up: purchased credits arrive with transaction.completed, once.
    co = (await client.post("/v1/billing/checkout", headers=a.h, json={"credit_pack": "k1"})).json()
    await client.post(f"/v1/billing/fixture/checkout/{co['transaction_id']}/complete", headers=a.h)
    assert (await balance(owner_db, a))[1] == 1000

    # Cancel at period end; Paddle's canceled event moves the workspace to free and keeps purchased credits.
    assert (await client.post("/v1/billing/cancel", headers=a.h)).json()["cancel_at_period_end"] is True
    assert paddle.FIXTURE.cancels[-1] == sub_id
    gone = {"event_id": f"evt_{uuid.uuid4().hex}", "event_type": "subscription.canceled", "occurred_at": "2026-12-17T10:00:00Z", "data": {**sub, "status": "canceled"}}
    raw = paddle.encode(gone)
    await client.post("/v1/billing/paddle/webhook", content=raw, headers={"Paddle-Signature": paddle.sign(raw, paddle.FIXTURE_SECRET)})
    acc = (await client.get("/v1/billing/account", headers=a.h)).json()
    assert (acc["plan"]["key"], acc["provider"], acc["credits_purchased"]) == ("free", "none", 1000)


async def test_webhook_for_unknown_price_is_recorded_not_applied(client, owner_db, root):
    from agentfirm.modules.billing import paddle

    a = await register(client, org="Odd Co")
    ev = {"event_id": f"evt_{uuid.uuid4().hex}", "event_type": "subscription.created", "data": {"id": "sub_x", "status": "active", "custom_data": {"org_id": a.org_id}, "items": [{"price": {"id": "pri_nope"}}]}}
    raw = paddle.encode(ev)
    r = await client.post("/v1/billing/paddle/webhook", content=raw, headers={"Paddle-Signature": paddle.sign(raw, paddle.FIXTURE_SECRET)})
    assert r.json() == {"result": "error"}
    assert (await client.get("/v1/billing/account", headers=a.h)).json()["plan"]["key"] == "free"
    rows = (await client.get("/v1/admin/billing-events", headers=root.h)).json()
    assert any(e["id"] == ev["event_id"] and "pri_nope" in (e["error"] or "") for e in rows)


# ── super-admin ──────────────────────────────────────────────────────────────


async def test_super_admin_controls_are_audited_and_guarded(client, owner_db, root):
    a = await register(client, org="Customer Co")
    for method, path, body in (
        ("put", "/v1/admin/plans/pro", {"name": "Pro", "monthly_credits": 1, "max_seats": 1, "max_concurrent_tasks": 1}),
        ("post", f"/v1/admin/accounts/{a.org_id}/credits", {"credits": 5, "note": "goodwill"}),
        ("put", "/v1/admin/tools/web.search", {"disabled": True, "reason": "provider outage"}),
        ("patch", "/v1/admin/agents/creative", {"enabled": False, "reason": "maintenance"}),
    ):
        assert (await getattr(client, method)(path, headers=a.h, json=body)).status_code == 403
    assert (await client.put("/v1/admin/plans/free", headers=root.h, json={"name": "Free", "monthly_credits": 1, "max_seats": 1, "max_concurrent_tasks": 1, "price_cents": 100})).status_code == 422

    rows = (await client.post(f"/v1/admin/accounts/{a.org_id}/credits", headers=root.h, json={"credits": 250, "note": "goodwill"})).json()
    assert next(r for r in rows if r["id"] == a.org_id)["credits_available"] >= 250
    assert (await balance(owner_db, a))[1] == 250
    assert (await client.post(f"/v1/admin/accounts/{a.org_id}/credits", headers=root.h, json={"credits": -999, "note": "oops"})).status_code == 422
    await client.put(f"/v1/admin/accounts/{a.org_id}/plan", headers=root.h, json={"plan": "business", "note": "invoiced annually"})
    acc = (await client.get("/v1/billing/account", headers=a.h)).json()
    assert (acc["plan"]["key"], acc["provider"]) == ("business", "manual")
    actions = {r["action"] for r in await owner_db.fetch("SELECT action FROM audit_logs WHERE actor_user_id = $1", uuid.UUID(root.user_id))}
    assert {"credits.granted", "plan.assigned"} <= actions


async def test_tool_kill_switch_and_disabled_agents(client, root, corpus):  # noqa: F811
    from agentfirm.runtime.tools.runtime import reset_override_cache

    a = await register(client, org="Switch Co")
    await client.put("/v1/admin/tools/web.search", headers=root.h, json={"disabled": True, "reason": "provider outage"})
    try:
        t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Research the European language learning market", "agents": ["research"]})).json()
        await drain()
        evs = await events(client, a, t["id"])
        assert any(e["type"] == "log" and "web.search is turned off by the platform administrator" in e["payload"]["message"] for e in evs)
        assert not any(e["type"] == "tool.called" and e["payload"].get("tool") == "web.search" for e in evs)
    finally:
        await client.put("/v1/admin/tools/web.search", headers=root.h, json={"disabled": False, "reason": "provider back"})
        reset_override_cache()

    queued = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Brainstorm names", "agents": ["creative"]})).json()
    await client.patch("/v1/admin/agents/creative", headers=root.h, json={"enabled": False, "reason": "maintenance"})
    try:
        assert (await client.post("/v1/tasks", headers=a.h, json={"objective": "More names", "agents": ["creative"]})).status_code == 404
        await drain()
        ex = (await detail(client, a, queued["id"]))["executions"][0]
        assert ex["status"] == "failed" and "turned off" in ex["result"]["error"]["message"]
    finally:
        await client.patch("/v1/admin/agents/creative", headers=root.h, json={"enabled": True, "reason": "done"})


# ── standing approvals ───────────────────────────────────────────────────────

POST = "Write a LinkedIn post about our tutoring beta and publish it."


async def test_standing_approval_covers_matching_actions_within_limits(client, owner_db):
    a = await register(client, org="Standing Co")
    member = await join_as(client, a, "member", name="Mo")
    body = {"tool": "social.publish", "agent": "marketing", "conditions": [{"fact": "channel", "op": "in", "value": ["linkedin"]}], "note": "Weekly LinkedIn posts", "max_uses": 1, "expires_in_days": 30}
    # Guard rails: destructive tools never; financial needs a cap and billing authority.
    assert (await client.post("/v1/standing-approvals", headers=a.h, json={**body, "tool": "deploy.production", "agent": "engineer", "conditions": []})).status_code == 422
    fin = {"tool": "ads.budget_change", "agent": "marketing", "conditions": [], "note": "Budgets", "max_uses": 5, "expires_in_days": 7}
    assert (await client.post("/v1/standing-approvals", headers=a.h, json=fin)).status_code == 422  # no amount cap
    fin["conditions"] = [{"fact": "amount", "op": "lte", "value": 50}]
    assert (await client.post("/v1/standing-approvals", headers=member.h, json=fin)).status_code == 403  # member can't approve spend
    assert (await client.post("/v1/standing-approvals", headers=a.h, json={**body, "expires_in_days": 400})).status_code == 422

    sa = (await client.post("/v1/standing-approvals", headers=member.h, json=body)).json()
    assert sa["active"] and sa["uses"] == 0

    t1 = (await client.post("/v1/tasks", headers=a.h, json={"objective": POST, "agents": ["marketing"]})).json()
    await drain()
    d1 = await detail(client, a, t1["id"])
    assert d1["status"] == "completed", d1["executions"][0]["stage"]
    appr = d1["approvals"][0]
    assert appr["status"] == "approved" and appr["decided_by"] == member.user_id
    evs = await events(client, a, t1["id"])
    assert any(e["type"] == "approval.resolved" and e["payload"].get("standing_approval_id") == sa["id"] for e in evs)
    assert any(e["type"] == "tool.called" and e["payload"].get("tool") == "social.publish" for e in evs)

    # Used up: the next post waits for a person again.
    t2 = (await client.post("/v1/tasks", headers=a.h, json={"objective": POST, "agents": ["marketing"]})).json()
    await drain()
    assert (await detail(client, a, t2["id"]))["status"] == "waiting_approval"

    # Another workspace can't touch it.
    other = await register(client, org="Elsewhere Co")
    assert (await client.post(f"/v1/standing-approvals/{sa['id']}/revoke", headers=other.h)).status_code == 404


async def test_standing_approval_stops_when_creator_loses_authority(client, owner_db):
    a = await register(client, org="Demoted Co")
    member = await join_as(client, a, "member", name="Mo")
    body = {"tool": "social.publish", "conditions": [], "note": "Posts", "max_uses": 5, "expires_in_days": 30}
    await client.post("/v1/standing-approvals", headers=member.h, json=body)
    await owner_db.execute("UPDATE memberships SET role = 'viewer' WHERE user_id = $1 AND org_id = $2", uuid.UUID(member.user_id), uuid.UUID(a.org_id))
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": POST, "agents": ["marketing"]})).json()
    await drain()
    assert (await detail(client, a, t["id"]))["status"] == "waiting_approval"


async def test_standing_approval_conditions_fail_closed():
    from agentfirm.modules.governance.standing import matches

    assert matches([{"fact": "channel", "op": "in", "value": ["linkedin"]}], {"channel": "LinkedIn"})
    assert not matches([{"fact": "channel", "op": "in", "value": ["linkedin"]}], {"channel": "x"})
    assert not matches([{"fact": "amount", "op": "lte", "value": 50}], {})
    assert not matches([{"fact": "amount", "op": "lte", "value": 50}], {"amount": "lots"})
    assert matches([{"fact": "recipient_domains", "op": "all_in", "value": ["northwind.com"]}], {"recipient_domains": ["northwind.com"]})
    assert not matches([{"fact": "recipient_domains", "op": "all_in", "value": ["northwind.com"]}], {"recipient_domains": ["northwind.com", "gmail.com"]})
    assert not matches([{"fact": "recipient_domains", "op": "all_in", "value": ["northwind.com"]}], {"recipient_domains": []})


# ── reply to resume ──────────────────────────────────────────────────────────


def _break(monkeypatch, agent: str) -> None:
    from agentfirm.agents.contracts import ErrorCode
    from agentfirm.runtime.errors import StepError
    from agentfirm.runtime.programs import PROGRAMS

    real = PROGRAMS[agent]

    async def ask(ctx, data):  # type: ignore[no-untyped-def]
        raise StepError(ErrorCode.POLICY_VIOLATION, "Which market do you mean?")

    class Broken:
        key = agent
        handlers = {w: dict.fromkeys(steps, ask) for w, steps in real.handlers.items()}
        finalize = staticmethod(real.finalize)
        approval_preview = staticmethod(real.approval_preview)

    monkeypatch.setitem(PROGRAMS, agent, Broken())


async def test_reply_resumes_a_single_agent_task(client, monkeypatch, corpus):  # noqa: F811
    a = await register(client, org="Reply Co")
    _break(monkeypatch, "research")
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Research the market", "agents": ["research"]})).json()
    await drain()
    assert (await detail(client, a, t["id"]))["executions"][0]["result"]["status"] == "needs_input"
    monkeypatch.undo()
    r = await client.post(f"/v1/tasks/{t['id']}/reply", headers=a.h, json={"message": "The European language learning market"})
    assert r.status_code == 200
    await drain()
    d = await detail(client, a, t["id"])
    roots = [e for e in d["executions"] if e["parent_execution_id"] is None]
    assert len(roots) == 2 and d["status"] == "completed"
    assert any("The user answered:\nThe European language learning market" in (r["objective"] or "") for r in roots)
    assert (await client.post(f"/v1/tasks/{t['id']}/reply", headers=a.h, json={"message": "again"})).status_code == 409


async def test_reply_resumes_orchestrated_task_reusing_finished_subtasks(client, monkeypatch, corpus):  # noqa: F811
    from agentfirm.runtime.gateway import simulated

    plan = [
        {"key": "facts", "agent": "research", "objective": "Research the language learning market"},
        {"key": "post", "agent": "marketing", "objective": "Write a LinkedIn post using the research", "depends_on": ["facts"]},
        {"key": "ideas", "agent": "creative", "objective": "Brainstorm ideas for online language learning"},
    ]
    monkeypatch.setitem(simulated._BUILDERS, "orchestrator.plan", lambda req: {"subtasks": plan, "rationale": "fixed"})
    _break(monkeypatch, "research")
    a = await register(client, org="Resume Co")
    t = (await client.post("/v1/tasks", headers=a.h, json={"objective": "Research, post and ideas", "agents": []})).json()
    await drain()
    d = await detail(client, a, t["id"])
    first_ideas = next(e for e in d["executions"] if e["subtask_key"] == "ideas")
    assert first_ideas["status"] == "completed"
    monkeypatch.undo()  # research works again (the fixed plan stays below)
    monkeypatch.setitem(simulated._BUILDERS, "orchestrator.plan", lambda req: {"subtasks": plan, "rationale": "fixed"})
    assert (await client.post(f"/v1/tasks/{t['id']}/reply", headers=a.h, json={"message": "Europe, adult learners"})).status_code == 200
    await drain()
    d = await detail(client, a, t["id"])
    roots = sorted((e for e in d["executions"] if e["parent_execution_id"] is None), key=lambda e: e["queued_at"])
    new_root = roots[-1]
    subs = {e["subtask_key"]: e for e in d["executions"] if e["parent_execution_id"] == new_root["id"]}
    assert subs["ideas"]["stage"] == "Reused from the previous attempt" and subs["ideas"]["result"] == first_ideas["result"]
    evs = await events(client, a, t["id"])
    assert not any(e["execution_id"] == subs["ideas"]["id"] and e["type"] == "step.started" for e in evs)  # not re-run
    assert "Europe, adult learners" in subs["facts"]["objective"]
    assert subs["facts"]["result"]["status"] == "completed" and subs["post"]["status"] in ("completed", "waiting_approval")
