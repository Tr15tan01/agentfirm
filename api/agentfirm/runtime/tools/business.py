"""Tool implementations for the Marketing, Engineer, BI and Assistant agents (Phase 4b).

External effects go through connectors (GitHub, webhook, SMTP, GN7T, OSV, sandbox), which
are fixture-backed in AGENTFIRM_CONNECTOR_MODE=fixture. Internal records (content calendar,
email drafts, report schedules) are written under the execution's organisation (RLS).
Fixture-mode outputs carry `"fixture": True`.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from agentfirm.agents.contracts import ErrorCode
from agentfirm.modules.integrations.models import ContentCalendarEntry, EmailDraft, ReportSchedule

from .. import connectors
from ..connectors import fixtures as fx
from ..connectors import github, sandbox, services
from ..errors import StepError
from ..schedules import CadenceError, next_run
from . import analysis, charts, web
from .impls import CURRENT_CALL, IMPLS, _session, artifact_write, tool

if TYPE_CHECKING:
    from ..context import ExecutionContext

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


async def _external(ctx: ExecutionContext, action: str, args: dict[str, Any], fixture: Any) -> dict[str, Any]:
    """Run an external action through the org's webhook connector, or the fixture world."""
    if connectors.fixture_mode():
        fx.WORLD.calls.append((action, args))
        out = fixture() if callable(fixture) else fixture
        return out | {"fixture": True}
    return await connectors.webhook(ctx, action, args, CURRENT_CALL.get())


# ── Repositories & code ──────────────────────────────────────────────────────


@tool("repo.read")
async def repo_read(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    gh = await github.client(ctx, args.get("repository"))
    ref = str(args.get("ref") or "main")
    if args.get("pull_request"):
        return {"repository": gh.repo, "pull_request": await gh.pull(int(args["pull_request"]))}
    paths = args.get("paths") or ([args["path"]] if args.get("path") else [])
    if not paths:
        return {"repository": gh.repo, "ref": ref, "tree": await gh.tree(ref)}
    files = {}
    for p in paths[:40]:
        files[p] = (await gh.read(str(p), ref))[:60_000]
    return {"repository": gh.repo, "ref": ref, "files": files}


@tool("repo.write_branch")
async def repo_write_branch(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    branch = str(args["branch"])
    github._check_branch(branch)
    files = {str(k): str(v) for k, v in (args.get("files") or {}).items()}
    if not files:
        raise StepError(ErrorCode.INVALID_INPUT, "No files to commit")
    github._check_paths(files)
    gh = await github.client(ctx, args.get("repository"))
    return await gh.write(branch, str(args.get("base") or "main"), files, str(args.get("message") or "AgentFirm change")[:500])


@tool("repo.open_pull_request")
async def repo_open_pr(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    head = str(args["head"])
    github._check_branch(head)
    gh = await github.client(ctx, args.get("repository"))
    return await gh.open_pr(head, str(args.get("base") or "main"), str(args["title"])[:200], str(args.get("body") or "")[:20_000])


@tool("sandbox.exec")
async def sandbox_exec(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    files = args.get("files")
    if files is None:
        gh = await github.client(ctx, args.get("repository"))
        ref = str(args.get("ref") or "main")
        paths = await gh.tree(ref)
        files = {p: await gh.read(p, ref) for p in paths[:400]}
    command = str(args.get("command") or "python -m pytest -q")[:1000]
    return await sandbox.run(files, command, timeout_s=min(int(args.get("timeout", 600)), 840))


@tool("deps.audit")
async def deps_audit(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    files = args.get("files") or {}
    pkgs = services.parse_manifests(files)
    found = await services.osv_audit(pkgs)
    return {"checked": len(pkgs), "vulnerabilities": found, "source": "OSV.dev", "fixture": connectors.fixture_mode()}


@tool("deploy.preview")
async def deploy_preview(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.deployments.append({"environment": "preview", **args})
        return {"environment": "preview", "url": f"https://preview-{len(fx.WORLD.deployments)}.example.dev", "status": "deployed"}

    return await _external(ctx, "deploy.preview", args, fake)


@tool("deploy.production")
async def deploy_production(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.deployments.append({"environment": "production", **args})
        return {"environment": "production", "url": "https://app.example.com", "status": "deployed"}

    return await _external(ctx, "deploy.production", args, fake)


# ── Data & reports ───────────────────────────────────────────────────────────


@tool("gn7t.query")
async def gn7t_query(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    if args.get("list_datasets"):
        return {"datasets": await services.gn7t_datasets(ctx)}
    return await services.gn7t_query(ctx, str(args["query"]), int(args.get("max_rows", 5000)))


@tool("data.analyze")
async def data_analyze(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    return analysis.run(args.get("rows") or [], args.get("operations") or [])


@tool("chart.render")
async def chart_render(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    spec = args["spec"]
    svg = charts.render(spec)
    name = re.sub(r"[^a-z0-9]+", "-", str(spec.get("title", "chart")).lower()).strip("-")[:60] or "chart"
    art = await artifact_write(ctx, {"name": f"{name}.svg", "content": svg, "deliverable": args.get("deliverable")})
    return art | {"table": charts.table_markdown(spec)}


@tool("report.schedule")
async def report_schedule(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    cadence, tz = str(args.get("cadence", "")), str(args.get("timezone") or "UTC")
    try:
        nxt = next_run(cadence, tz)
    except CadenceError as exc:
        raise StepError(ErrorCode.INVALID_INPUT, str(exc)) from exc
    async with _session(ctx) as s:
        sched = ReportSchedule(
            org_id=ctx.org_id,
            title=str(args.get("title") or ctx.objective)[:240],
            agent_key=ctx.manifest.key,
            objective=str(args.get("objective") or ctx.objective)[:4000],
            parameters={k: v for k, v in ctx.parameters.items() if k != "intent"},
            cadence=cadence,
            timezone=tz,
            next_run_at=nxt,
            created_by=ctx.requested_by,
        )
        s.add(sched)
        await s.flush()
        sid = sched.id
    return {"schedule_id": str(sid), "cadence": cadence, "timezone": tz, "next_run_at": nxt.isoformat()}


@tool("automation.run")
async def automation_run(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.automation_runs.append(args)
        return {"status": "done", "affected": len(args.get("targets") or [])}

    return await _external(ctx, "automation.run", args, fake)


@tool("payments.execute")
async def payments_execute(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.payments.append(args)
        return {"status": "submitted", "reference": f"PAY-{len(fx.WORLD.payments):04d}"}

    return await _external(ctx, "payments.execute", args, fake)


# ── Marketing ────────────────────────────────────────────────────────────────


@tool("seo.keywords")
async def seo_keywords(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    kws = [str(k)[:100] for k in (args.get("keywords") or [])][:30]
    locale = str(args.get("locale") or "en")
    if connectors.fixture_mode():
        if not fx.WORLD.keywords_available:
            raise StepError(ErrorCode.TOOL_ERROR, "No keyword data provider is connected.")
        return {"keywords": [fx.keyword_metrics(k, locale) for k in kws], "fixture": True}
    return await connectors.webhook(ctx, "seo.keywords", {"keywords": kws, "locale": locale}, CURRENT_CALL.get())


@tool("content.calendar_write")
async def calendar_write(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    entries = args.get("entries") or []
    ids = []
    async with _session(ctx) as s:
        for e in entries[:60]:
            when = e.get("date")
            row = ContentCalendarEntry(
                org_id=ctx.org_id,
                execution_id=ctx.execution_id,
                channel=str(e.get("channel", "other"))[:40],
                title=str(e.get("title", ""))[:240],
                body=str(e.get("body", ""))[:20_000],
                language=str(e.get("language") or "")[:16] or None,
                scheduled_for=date.fromisoformat(when) if isinstance(when, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", when) else None,
            )
            s.add(row)
            await s.flush()
            ids.append(str(row.id))
    return {"created": ids, "status": "draft"}


@tool("ads.performance_read")
async def ads_performance(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    return await _external(
        ctx, "ads.performance_read", args, lambda: {"campaigns": [dict(c) for c in fx.WORLD.ad_campaigns], "period": args.get("period", "last_30_days")}
    )


@tool("social.publish")
async def social_publish(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.published.append(args)
        return {"status": "published", "url": f"https://social.example/{args.get('channel', 'post')}/{len(fx.WORLD.published)}"}

    return await _external(ctx, "social.publish", args, fake)


@tool("ads.budget_change")
async def ads_budget(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.budget_changes.append(args)
        return {"status": "applied", "campaign": args.get("campaign"), "daily_budget": args.get("daily_budget")}

    return await _external(ctx, "ads.budget_change", args, fake)


# ── Personal assistant ───────────────────────────────────────────────────────


@tool("calendar.read")
async def calendar_read(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    if connectors.fixture_mode() and fx.WORLD.calendar_error:
        code = fx.WORLD.calendar_error
        raise StepError(
            ErrorCode.PERMISSION_DENIED if code in (401, 403) else ErrorCode.TOOL_ERROR,
            f"The calendar connection was rejected ({code}: token expired); reconnect it in Settings → Integrations.",
        )
    return await _external(ctx, "calendar.read", args, lambda: {"events": list(fx.WORLD.calendar_events), "range": args.get("range")})


@tool("calendar.create_event")
async def calendar_create(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.created_events.append(args)
        return {"status": "created", "event_id": f"evt-{len(fx.WORLD.created_events)}"}

    return await _external(ctx, "calendar.create_event", args, fake)


@tool("email.draft")
async def email_draft(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    to = [a for a in (args.get("to") or []) if isinstance(a, str) and EMAIL.match(a)][:50]
    cc = [a for a in (args.get("cc") or []) if isinstance(a, str) and EMAIL.match(a)][:50]
    groups = set(args.get("recipient_groups") or []) & {"team", "everyone"}
    async with _session(ctx) as s:
        if groups:  # "the team" = active members of this organisation (resolved here, under RLS, never guessed)
            from agentfirm.modules.identity.models import Membership, User

            emails = (
                (
                    await s.execute(
                        select(User.email)
                        .join(Membership, Membership.user_id == User.id)
                        .where(Membership.org_id == ctx.org_id, Membership.status == "active")
                        .order_by(User.email)
                    )
                )
                .scalars()
                .all()
            )
            to = list(dict.fromkeys([*to, *emails]))[:50]
        d = EmailDraft(
            org_id=ctx.org_id,
            execution_id=ctx.execution_id,
            to_addresses=to,
            cc_addresses=cc,
            subject=str(args.get("subject", ""))[:300],
            body=str(args.get("body", ""))[:50_000],
            created_by=ctx.requested_by,
        )
        s.add(d)
        await s.flush()
        did = d.id
    return {"draft_id": str(did), "to": to, "cc": cc, "status": "draft"}


@tool("email.send")
async def email_send(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    async with _session(ctx) as s:
        d = (
            await s.execute(select(EmailDraft).where(EmailDraft.id == UUID(str(args["draft_id"])), EmailDraft.org_id == ctx.org_id).with_for_update())
        ).scalar_one_or_none()
        if d is None:
            raise StepError(ErrorCode.INVALID_INPUT, "Draft not found")
        if d.status == "sent":
            return {"sent": True, "to": d.to_addresses, "already_sent": True}
        if not d.to_addresses:
            raise StepError(ErrorCode.MISSING_CONTEXT, "The draft has no recipients.")
        to, cc, subject, body = list(d.to_addresses), list(d.cc_addresses), d.subject, d.body
    result = await services.send_email(ctx, to=to, cc=cc, subject=subject, body=body, idempotency_key=CURRENT_CALL.get())
    async with _session(ctx) as s:
        d = await s.get(EmailDraft, UUID(str(args["draft_id"])))
        from datetime import UTC, datetime

        d.status, d.sent_at = "sent", datetime.now(UTC)  # type: ignore[union-attr]
    return result


def _fixture_search(items: list[dict[str, Any]], query: str, kind: str | None = None) -> list[dict[str, Any]]:
    words = {w for w in re.findall(r"[a-zäöüß]{3,}", query.lower())} - {"find", "the", "and", "with", "near", "jobs", "job", "for"}
    pool = [i for i in items if kind is None or i.get("kind") == kind]
    scored = [(sum(w in " ".join(str(v) for v in i.values()).lower() for w in words), i) for i in pool]
    return [i for s, i in sorted(scored, key=lambda t: -t[0]) if s > 0]


@tool("jobs.search")
async def jobs_search(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query", ""))[:300]
    if connectors.fixture_mode():
        return {"results": _fixture_search(fx.WORLD.jobs, q), "fixture": True}
    hits = await web.search(f"{q} job opening", count=8)
    return {"results": [{"title": h["title"], "url": h["url"], "snippet": h.get("snippet", "")} for h in hits], "source": "web search"}


@tool("places.search")
async def places_search(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query", ""))[:300]
    if connectors.fixture_mode():
        return {"results": _fixture_search(fx.WORLD.places, q, args.get("kind")), "fixture": True}
    hits = await web.search(q, count=8)
    return {"results": [{"name": h["title"], "url": h["url"], "notes": h.get("snippet", "")} for h in hits], "source": "web search"}


@tool("purchase.execute")
async def purchase_execute(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    def fake() -> dict[str, Any]:
        fx.WORLD.purchases.append(args)
        return {"status": "booked", "reference": f"BK-{len(fx.WORLD.purchases):04d}", "item": args.get("item"), "total": args.get("total")}

    return await _external(ctx, "purchase.execute", args, fake)


assert {"repo.read", "sandbox.exec", "gn7t.query", "email.send", "purchase.execute"} <= set(IMPLS)
