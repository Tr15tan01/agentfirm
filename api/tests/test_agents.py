"""Marketing, Engineer, BI and Assistant agents end-to-end (simulated models, fixture world).

These pin down the rules that matter most: who authorises consequential actions, that
approved actions use exactly what the approver saw, that numbers are computed (not
generated), and that recurring reports can't multiply themselves.
"""

from __future__ import annotations

import uuid

from agentfirm.runtime.connectors import fixtures as fx

from .conftest import join_as, register
from .test_runtime import create, detail, drain, events, executable_agents  # noqa: F401


async def _approve(client, approver, approval_id: str, decision: str = "approved", note: str | None = None):  # type: ignore[no-untyped-def]
    return await client.post(f"/v1/approvals/{approval_id}/decision", headers=approver.h, json={"decision": decision, "note": note})


async def test_member_requests_production_deploy_admin_authorises(client, executable_agents):  # noqa: F811
    owner = await register(client, org="Deploy Co")
    member = await join_as(client, owner, "member", name="Mia")
    admin = await join_as(client, owner, "admin", name="Abe")
    task = await create(client, member, "Ship the release to production.", "engineer")
    await drain()
    t = await detail(client, owner, task["id"])
    approval = t["approvals"][0]
    assert (approval["tool_key"], approval["side_effect"]) == ("deploy.production", "destructive")
    assert "PRODUCTION" in approval["preview"] and "FIXTURE" in approval["preview"]
    assert fx.WORLD.deployments == []

    r = await _approve(client, member, approval["id"])
    assert r.status_code == 403 and "agents:configure" in r.text, "a member can't authorise a destructive action"
    assert (await _approve(client, admin, approval["id"])).status_code == 200
    await drain()
    ex = (await detail(client, owner, task["id"]))["executions"][0]
    assert ex["status"] == "completed", ex
    assert [d["environment"] for d in fx.WORLD.deployments] == ["production"], "runs under the approver's authority"


async def test_admin_requests_budget_change_only_owner_can_approve(client, executable_agents):  # noqa: F811
    owner = await register(client, org="Spend Co")
    admin = await join_as(client, owner, "admin", name="Ari")
    task = await create(client, admin, "Increase the Meta campaign budget to €80 per day.", "marketing")
    await drain()
    approval = (await detail(client, owner, task["id"]))["approvals"][0]
    assert approval["side_effect"] == "financial" and "80.00" in approval["preview"]
    assert (await _approve(client, admin, approval["id"])).status_code == 403
    assert (await _approve(client, owner, approval["id"])).status_code == 200
    await drain()
    assert fx.WORLD.budget_changes == [{"campaign": "Autumn intake — Meta", "daily_budget": 80.0, "currency": "EUR"}], "exactly what the approver saw"


async def test_bi_numbers_are_computed_not_generated(client, executable_agents):  # noqa: F811
    a = await register(client, org="Numbers Co")
    task = await create(client, a, "What was average revenue per customer in Q3?", "bi")
    await drain()
    t = await detail(client, a, task["id"])
    result = t["executions"][0]["result"]
    rows = fx.default_datasets()["payments_q3"]
    arpc = sum(r["amount"] for r in rows) / len({r["customer_id"] for r in rows})
    assert f"{arpc:,.2f}" in result["summary"]
    verified = [c for c in result["claims"] if c["status"] == "verified"]
    assert verified and all(c["citations"][0]["source_id"] == "gn7t:payments_q3" for c in verified)
    downgraded = [c for c in result["claims"] if "12%" in c["text"]]
    assert downgraded and downgraded[0]["status"] == "assumption", "an uncomputed figure is never presented as computed"
    assert {"business_report.md", "data_tables.csv"} <= {x["name"] for x in t["artifacts"]}


async def test_bi_refuses_bad_data(client, executable_agents):  # noqa: F811
    for row in fx.WORLD.datasets["customers"][:90]:
        row["signup_date"] = None
    a = await register(client, org="Dirty Data Co")
    task = await create(client, a, "Analyse retention by cohort.", "bi")
    await drain()
    result = (await detail(client, a, task["id"]))["executions"][0]["result"]
    assert result["status"] == "needs_input" and "signup_date is 45% empty" in result["summary"]


async def test_weekly_report_schedule_runs_once_and_never_multiplies(client, executable_agents, owner_db):  # noqa: F811
    from agentfirm.worker import Worker

    a = await register(client, org="Schedule Co")
    task = await create(client, a, "Create a weekly activation and retention report and schedule it for Monday mornings.", "bi")
    await drain()
    sched = await owner_db.fetchrow("SELECT id, cadence, next_run_at FROM report_schedules WHERE org_id = $1", uuid.UUID(a.org_id))
    assert sched["cadence"] == "weekly:mon@08:00"
    await owner_db.execute("UPDATE report_schedules SET next_run_at = now() - interval '1 minute' WHERE id = $1", sched["id"])
    async with Worker(worker_id="sched-test") as w:
        assert await w.run_due_schedules() == 1
        assert await w.run_due_schedules() == 0, "a due run is created once"
        await w.run_until_idle()
    tasks = (await client.get("/v1/tasks", headers=a.h)).json()
    scheduled = [t for t in tasks if t["title"].endswith("(scheduled)")]
    assert len(scheduled) == 1 and scheduled[0]["id"] != task["id"]
    assert scheduled[0]["executions"][0]["status"] == "completed"
    assert await owner_db.fetchval("SELECT count(*) FROM report_schedules WHERE org_id = $1", uuid.UUID(a.org_id)) == 1, "the scheduled run didn't schedule itself"
    nxt = await owner_db.fetchval("SELECT next_run_at FROM report_schedules WHERE id = $1", sched["id"])
    assert nxt.weekday() == 0 and nxt.hour == 8


async def test_assistant_sends_to_the_team_only_after_approval(client, executable_agents):  # noqa: F811
    a = await register(client, org="Notes Co")
    await join_as(client, a, "member", name="Nia")
    await client.post("/v1/knowledge/documents", headers=a.h, json={"title": "Meeting notes 17 Nov", "content": "Meeting notes: we agreed to ship the beta on 1 December. Owners: Ada (launch), Nia (support)."})
    task = await create(client, a, "Send the meeting notes to the team.", "assistant")
    await drain()
    t = await detail(client, a, task["id"])
    approval = t["approvals"][0]
    members = sorted(m["email"] for m in (await client.get("/v1/members", headers=a.h)).json())
    assert approval["tool_key"] == "email.send" and all(m in approval["preview"] for m in members)
    assert "ship the beta on 1 December" in approval["preview"]
    assert fx.WORLD.sent_emails == []
    await _approve(client, a, approval["id"])
    await drain()
    assert len(fx.WORLD.sent_emails) == 1 and sorted(fx.WORLD.sent_emails[0]["to"]) == members
    assert "Sent" in (await detail(client, a, task["id"]))["executions"][0]["result"]["summary"]


async def test_assistant_buys_exactly_the_approved_item(client, executable_agents):  # noqa: F811
    a = await register(client, org="Travel Co")
    task = await create(client, a, "Buy the cheapest train ticket to Munich on Friday.", "assistant")
    await drain()
    approval = (await detail(client, a, task["id"]))["approvals"][0]
    assert approval["side_effect"] == "financial" and "€59.90" in approval["preview"]
    await _approve(client, a, approval["id"])
    await drain()
    assert fx.WORLD.purchases == [{"item": "ICE 597 Berlin → München, Fri 07:29", "total": "€59.90", "url": "https://places.example.com/ice597"}]
    result = (await detail(client, a, task["id"]))["executions"][0]["result"]
    assert "Imaginary Option" not in result["summary"], "options not in the search results are dropped"


async def test_engineer_branch_pr_and_honest_test_report(client, executable_agents):  # noqa: F811
    a = await register(client, org="Code Co")
    main_before = dict(fx.WORLD.branches["main"])
    task = await create(client, a, "Add pagination to the tasks endpoint with tests and open a pull request.", "engineer")
    await drain()
    t = await detail(client, a, task["id"])
    branch = next(b for b in fx.WORLD.branches if b.startswith("agent/"))
    assert fx.WORLD.branches["main"] == main_before, "never writes to the default branch"
    assert "limit = max(1, min(limit, 200))" in fx.WORLD.branches[branch]["app/tasks.py"]
    approval = t["approvals"][0]
    assert approval["tool_key"] == "repo.open_pull_request" and "+    limit = max(1, min(limit, 200))" in approval["preview"]
    await _approve(client, a, approval["id"])
    await drain()
    t = await detail(client, a, task["id"])
    assert fx.WORLD.pull_requests and fx.WORLD.pull_requests[0]["head"] == branch
    summary = t["executions"][0]["result"]["summary"]
    assert "not a real test run" in summary and "Pull request opened" in summary
    assert {"implementation_plan.md", "code_change.diff", "test_report.md"} <= {x["name"] for x in t["artifacts"]}
    tool_calls = [e["payload"]["tool"] for e in await events(client, a, task["id"]) if e["type"] == "tool.called"]
    assert "deploy.preview" not in tool_calls and "deploy.production" not in tool_calls


async def test_marketing_brand_check_and_drafts_only(client, executable_agents, owner_db):  # noqa: F811
    a = await register(client, org="Brand Co")
    await client.put("/v1/memories/banned_claims", headers=a.h, json={"value": "guaranteed results"})
    task = await create(client, a, "Write three LinkedIn posts announcing the beta.", "marketing")
    await drain()
    result = (await detail(client, a, task["id"]))["executions"][0]["result"]
    assert "40%" not in result["summary"], "unsourced figures are removed before anything is saved"
    rows = await owner_db.fetch("SELECT status, body FROM content_calendar_entries WHERE org_id = $1", uuid.UUID(a.org_id))
    assert len(rows) == 3 and {r["status"] for r in rows} == {"draft"} and not any("40%" in r["body"] for r in rows)
    assert fx.WORLD.published == []
    logs = [e["payload"]["message"] for e in await events(client, a, task["id"]) if e["type"] == "log"]
    assert any("unsourced figure" in m for m in logs)


async def test_agent_profile_reports_real_workspace_data(client, executable_agents):  # noqa: F811
    a = await register(client, org="Profile Co")
    await create(client, a, "Brainstorm ideas for online language learning", "creative")
    await drain()
    p = (await client.get("/v1/agents/marketing", headers=a.h)).json()
    tools = {t["key"]: t for t in p["tools"]}
    assert tools["social.publish"]["side_effect"] == "external" and tools["social.publish"]["approval"] == "require_approval"
    assert tools["ads.budget_change"]["side_effect"] == "financial"
    assert {m["capability"] for m in p["models"]} == set(p["manifest"]["models"]["capabilities"])
    assert p["usage"]["runs_30d"] == 0, "usage is per agent and per workspace"
    c = (await client.get("/v1/agents/creative", headers=a.h)).json()
    assert c["usage"]["runs_30d"] == 1 and c["usage"]["success_rate"] == 1.0 and c["usage"]["credits_30d"] > 0
    assert c["recent"][0]["status"] == "completed"
    assert "tools" not in (await client.get("/v1/agents", headers=a.h)).json()[0] or (await client.get("/v1/agents", headers=a.h)).json()[0]["tools"] is None
