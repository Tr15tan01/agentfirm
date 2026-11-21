"""Personal Assistant agent program (manifest: agents/manifests/assistant.yaml).

Drafts by default, acts only on request and after approval: an email is sent, an event
created or a purchase made only if the user asked for that action AND an approval showing
the exact recipients/times/item and total was approved. Listings and options are only ever
taken from tool results (never invented); specialist work is routed to the right agent.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agentfirm.agents.contracts import AgentResult, ArtifactRef, Citation, Claim, ErrorCode, HandoffRequest

from ..context import ExecutionContext, untrusted
from ..errors import StepError
from ..gateway import simulated
from .base import approval_state, art_ref, fixture_note, wants

SYSTEM = (
    "You are AgentFirm's Personal Assistant. Be concise and practical. Never invent facts, people, "
    "listings, prices or availability: use only what tools returned, and say when something is unknown."
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SPECIALISTS = {
    "research": "research and fact-finding",
    "marketing": "marketing and campaigns",
    "engineer": "code, bugs and deployments",
    "bi": "business data, KPIs and revenue",
    "creative": "brainstorming and ideas",
}


class Understanding(BaseModel):
    needs_lookup: bool
    query: str = ""


class Answer(BaseModel):
    answer: str


class ProposedEvent(BaseModel):
    title: str
    start: str
    end: str
    attendees: list[str] = Field(default_factory=list)


class Proposal(BaseModel):
    events: list[ProposedEvent]
    notes: str = ""


class Email(BaseModel):
    subject: str
    body: str
    to_hints: list[str] = Field(default_factory=list)


class Compared(BaseModel):
    name: str
    price: str | None = None
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    url: str | None = None


class Comparison(BaseModel):
    items: list[Compared]
    recommendation: str = ""


class Route(BaseModel):
    agent: str
    objective: str
    reason: str


class Routing(BaseModel):
    handoffs: list[Route]


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    try:
        return datetime.fromisoformat(a["start"]) < datetime.fromisoformat(b["end"]) and datetime.fromisoformat(b["start"]) < datetime.fromisoformat(a["end"])
    except (KeyError, ValueError):
        return False


# ── general ──────────────────────────────────────────────────────────────────


async def understand(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    u = await ctx.structured(
        "understand",
        "classify",
        Understanding,
        system=SYSTEM + " Decide whether answering needs a lookup (current facts, places, hours, prices) or is general advice.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"understanding": u.model_dump()}


async def lookup(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    u = d.get("understanding", {})
    if not u.get("needs_lookup"):
        return {"sources": []}
    q = u.get("query") or ctx.objective
    sources = []
    for c in (await ctx.tool("knowledge.retrieve", query=q, top_k=3)).get("chunks", []):
        sources.append({"title": c["title"], "url": c["url"], "text": c["content"][:2000]})
    for r in (await ctx.tool("web.search", query=q, count=4)).get("results", [])[:2]:
        try:
            page = await ctx.tool("web.fetch", url=r["url"])
            sources.append({"title": page.get("title") or r["title"], "url": page["url"], "text": page["text"][:4000]})
        except StepError as exc:
            await ctx.log("warn", f"Skipped {r['url'][:80]}: {exc.message}")
    return {"sources": sources}


async def answer(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    src = d.get("sources", [])
    if d.get("understanding", {}).get("needs_lookup") and not src:
        return {"answer_md": "I couldn't find a reliable source for that, so I won't guess. Could you share a link or more detail?"}
    blocks = "\n\n".join(untrusted(s["url"], s["text"], 3000) for s in src)
    a = await ctx.text(
        "answer",
        "text",
        system=SYSTEM + " Answer directly. If you used sources, rely only on them.",
        user=f"Question: {ctx.objective}\n\nSources:\n{blocks or '(none — general advice)'}",
        sim={"objective": ctx.objective, "sources": src},
    )
    refs = "\n".join(f"- [{s['title']}]({s['url']})" for s in src)
    return {"answer_md": a + (f"\n\n**Sources**\n{refs}" if refs else "")}


# ── scheduling ───────────────────────────────────────────────────────────────


async def availability(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out = await ctx.tool("calendar.read", range=ctx.parameters.get("when") or "next 7 days")
    return {"events": out.get("events", []), "fixture:availability": bool(out.get("fixture"))}


async def propose(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    busy = d.get("events", [])
    p = await ctx.structured(
        "propose",
        "reasoning",
        Proposal,
        system=SYSTEM + " Propose calendar blocks or a meeting that do not overlap existing events. Use ISO 8601 local times.",
        user=f"Request: {ctx.objective}\nPeople: {ctx.parameters.get('people') or []}\nExisting events: {busy}",
        sim={"objective": ctx.objective, "busy": busy},
    )
    kept, dropped = [], []
    for e in p.events:
        (dropped if any(_overlaps(e.model_dump(), b) for b in busy) else kept).append(e.model_dump())
    if dropped:
        await ctx.log("warn", f"Dropped {len(dropped)} proposed slots that overlapped existing events")
    if not kept:
        raise StepError(ErrorCode.MISSING_CONTEXT, "I couldn't find a free slot that fits. Which days or times work for you?")
    return {"proposal": {"events": kept, "notes": p.notes}}


async def create_events(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d) != "approved":
        return {"created": []}
    created = []
    for e in d["proposal"]["events"]:
        created.append(await ctx.tool("calendar.create_event", **e))
    return {"created": created, "fixture:create": any(c.get("fixture") for c in created)}


def _events_md(events: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- **{e['title']}** — {e['start'].replace('T', ' ')[:16]} → {e['end'][11:16]}" + (f" with {', '.join(e['attendees'])}" if e.get("attendees") else "")
        for e in events
    )


# ── drafting ─────────────────────────────────────────────────────────────────


async def drafting_context(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    mem = (await ctx.tool("memory.read", keys=["writing_style", "signature"])).get("memories", {})
    chunks = (await ctx.tool("knowledge.retrieve", query=ctx.objective, top_k=3)).get("chunks", [])
    return {"style": mem, "context": [{"title": c["title"], "content": c["content"][:2000]} for c in chunks]}


async def draft_email(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    ctxt = "\n\n".join(untrusted(c["title"], c["content"], 2000) for c in d.get("context", []))
    e = await ctx.structured(
        "draft",
        "text",
        Email,
        system=SYSTEM
        + f" Draft the email. Style: {d.get('style', {}).get('writing_style') or 'friendly and clear'}. If a fact you need is missing, write a visible placeholder like [add date] rather than inventing it.",
        user=f"Request: {ctx.objective}\nRelevant workspace notes:\n{ctxt or '(none)'}",
        sim={"objective": ctx.objective, "context": d.get("context", [])},
    )
    explicit = EMAIL.findall(ctx.objective) + [p for p in ctx.parameters.get("people") or [] if EMAIL.fullmatch(p)]
    groups = [h for h in ("team", "everyone") if re.search(rf"\b{h}\b", ctx.objective, re.I)]
    out = await ctx.tool(
        "email.draft",
        to=explicit,
        recipient_groups=groups,
        subject=e.subject,
        body=e.body + (f"\n\n{d['style']['signature']}" if d.get("style", {}).get("signature") else ""),
    )
    unresolved = [h for h in e.to_hints if not EMAIL.fullmatch(h) and h.lower() not in ("team", "everyone")]
    return {"email": {"draft_id": out["draft_id"], "to": out["to"], "subject": e.subject, "body": e.body}, "unresolved": unresolved}


async def send_email(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d) != "approved":
        return {"sent": None}
    out = await ctx.tool("email.send", draft_id=d["email"]["draft_id"])
    return {"sent": out, "fixture:send": bool(out.get("fixture"))}


# ── discovery ────────────────────────────────────────────────────────────────


async def search(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    o = ctx.objective
    if wants(o, r"\bjobs?\b", r"\broles?\b", r"\bpositions?\b", r"\bhiring\b"):
        out, tool = await ctx.tool("jobs.search", query=o), "jobs.search"
    elif wants(o, r"\bcoworking\b", r"\btrain\b", r"\bticket\b", r"\bhotel\b", r"\brestaurant\b", r"\bflight\b", r"\bnear\b", r"\bvenue\b"):
        kind = "train" if wants(o, r"\btrain\b", r"\bticket\b") else "coworking" if wants(o, r"\bcoworking\b") else None
        out, tool = await ctx.tool("places.search", query=o, kind=kind), "places.search"
    else:
        out, tool = {"results": (await ctx.tool("web.search", query=o, count=6)).get("results", [])}, "web.search"
    return {"results": out.get("results", []), "search_tool": tool, "fixture:search": bool(out.get("fixture"))}


async def compare(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    results = d.get("results", [])
    if not results:
        return {"comparison": {"items": [], "recommendation": ""}}
    c = await ctx.structured(
        "compare",
        "reasoning",
        Comparison,
        system=SYSTEM + " Compare only the listed results. Use their names exactly.",
        user=f"Request: {ctx.objective}\nResults: {results}",
        sim={"objective": ctx.objective, "results": results},
    )
    names = {str(r.get("name") or r.get("title")).lower() for r in results}
    items = [i.model_dump() for i in c.items if i.name.lower() in names]
    if len(items) < len(c.items):
        await ctx.log("warn", f"Dropped {len(c.items) - len(items)} compared items that weren't in the search results")
    return {"comparison": {"items": items, "recommendation": c.recommendation if items else ""}}


def _comparison_md(d: dict[str, Any]) -> str:
    items = d.get("comparison", {}).get("items", [])
    if not items:
        return "I found no matching results, so there's nothing to compare. I won't make up listings — try a broader search or another location."
    rows = "\n".join(
        f"| [{i['name']}]({i['url']}) | {i.get('price') or '—'} | {'; '.join(i['pros'])} | {'; '.join(i['cons'])} |"
        if i.get("url")
        else f"| {i['name']} | {i.get('price') or '—'} | {'; '.join(i['pros'])} | {'; '.join(i['cons'])} |"
        for i in items
    )
    rec = d["comparison"].get("recommendation")
    return f"| Option | Price | Pros | Cons |\n|---|---|---|---|\n{rows}" + (f"\n\n**Recommendation:** {rec}" if rec else "")


async def deliver_comparison(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    md = f"# {ctx.objective}\n\n{_comparison_md(d)}"
    out = await ctx.tool("artifact.write", name="comparison.md", content=md, deliverable="comparison")
    return {"artifacts": [art_ref(out)]}


def _choice(d: dict[str, Any]) -> dict[str, Any] | None:
    items = d.get("comparison", {}).get("items", [])
    priced = [i for i in items if i.get("price")]
    if not priced:
        return None

    def amount(i: dict[str, Any]) -> float:
        m = re.search(r"(\d+(?:[.,]\d+)?)", i["price"])
        return float(m.group(1).replace(",", ".")) if m else float("inf")

    return min(priced, key=amount)


async def buy(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d, "purchase") != "approved":
        return {"purchase": None}
    c = _choice(d)
    out = await ctx.tool("purchase.execute", item=c["name"], total=c["price"], url=c.get("url"))  # type: ignore[index]
    return {"purchase": out, "fixture:buy": bool(out.get("fixture"))}


# ── delegate ─────────────────────────────────────────────────────────────────


async def route(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    allowed = set(ctx.manifest.collaboration.can_delegate_to)
    r = await ctx.structured(
        "route",
        "reasoning",
        Routing,
        system=SYSTEM + f" Split the request into parts for these specialists: { {k: v for k, v in SPECIALISTS.items() if k in allowed} }.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    routes = [x.model_dump() for x in r.handoffs if x.agent in allowed][:4]
    if not routes:
        raise StepError(ErrorCode.MISSING_CONTEXT, "Which specialist should take this on — research, marketing, engineering, BI or creative?")
    return {"routes": routes}


async def delegate(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    handoffs = []
    for r in d["routes"]:
        h = await ctx.tool("agents.delegate", to_agent=r["agent"], objective=r["objective"], reason=r["reason"], blocking=True)
        handoffs.append(h["handoff"])
    return {"handoffs": handoffs}


async def merge(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    lines = "\n".join(f"{n}. **{h['to_agent'].capitalize()}** — {h['objective']} _(why: {h['reason']})_" for n, h in enumerate(d.get("handoffs", []), 1))
    md = f"# Task summary\n\n{ctx.objective}\n\n## Who does what\n{lines}\n\n_The specialists' results are combined here once they finish (multi-agent runs arrive with the orchestrator)._"
    out = await ctx.tool("artifact.write", name="task_summary.md", content=md, deliverable="task_summary")
    return {"summary_md": md, "artifacts": [art_ref(out)]}


# ── Program ──────────────────────────────────────────────────────────────────


class AssistantProgram:
    key = "assistant"
    handlers = {
        "general": {"understand": understand, "lookup": lookup, "answer": answer},
        "scheduling": {"availability": availability, "propose": propose, "create": create_events},
        "drafting": {"context": drafting_context, "draft": draft_email, "send": send_email},
        "discovery": {"search": search, "compare": compare, "deliver": deliver_comparison, "buy": buy},
        "delegate": {"route": route, "delegate": delegate, "merge": merge},
    }

    def approval_scope(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> list[str] | None:
        o = ctx.objective
        if step == "approval" and "proposal" in data:
            return (
                ["calendar.create_event"]
                if wants(
                    o,
                    r"\bbook\b",
                    r"\bschedule (?:a|the|an)\b",
                    r"\badd (?:it |them )?to my calendar\b",
                    r"\binvite\b",
                    r"\bset up (?:a|the) (?:call|meeting)\b",
                )
                else []
            )
        if step == "approval" and "email" in data:
            return ["email.send"] if wants(o, r"\bsend\b", r"\bemail (?:it|this|them) to\b", r"\breply to\b") and data["email"]["to"] else []
        if step == "purchase":
            return ["purchase.execute"] if wants(o, r"\bbuy\b", r"\bbook\b", r"\bpurchase\b", r"\border\b", r"\breserve\b") and _choice(data) else []
        return None

    def approval_facts(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> dict[str, Any]:
        """Facts a standing approval's conditions can check (ADR 0006)."""
        if "email" in data:
            to = [str(t) for t in (data["email"].get("to") or [])]
            return {"recipient_domains": sorted({t.rsplit("@", 1)[-1].lower() for t in to if "@" in t}), "recipient_count": len(to)}
        return {}

    def approval_preview(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> str | None:
        if step == "approval" and "proposal" in data:
            return "Create these calendar events:\n\n" + _events_md(data["proposal"]["events"])
        if step == "approval" and "email" in data:
            e = data["email"]
            return f"To: {', '.join(e['to'])}\nSubject: {e['subject']}\n\n{e['body']}"
        if step == "purchase" and (c := _choice(data)):
            return f"Buy: {c['name']}\nTotal: {c['price']}\nSource: {c.get('url') or 'search result'}\n\nThis uses the saved payment method of the connected account."
        return None

    def finalize(self, ctx: ExecutionContext, data: dict[str, Any]) -> AgentResult:
        parts: list[str] = []
        claims: list[Claim] = []
        if data.get("answer_md"):
            parts.append(data["answer_md"])
            for s in data.get("sources", []):
                claims.append(
                    Claim(text=f"Used source: {s['title']}", status="verified", citations=[Citation(source_id=s["url"], title=s["title"][:200], url=s["url"])])
                )
        if "proposal" in data:
            state = approval_state(data)
            created = data.get("created") or []
            head = (
                "Added to your calendar:"
                if created
                else (
                    "Proposed (not booked — you didn't ask me to book, so nothing was added):"
                    if state == "not_requested"
                    else f"Not booked — the approver rejected it ({data.get('approval_note:approval') or 'no note'}):"
                    if state == "rejected"
                    else "Proposed:"
                )
            )
            parts.append(f"{head}\n\n{_events_md(data['proposal']['events'])}" + (f"\n\n{data['proposal']['notes']}" if data["proposal"].get("notes") else ""))
        if "email" in data:
            e, state = data["email"], approval_state(data)
            status = (
                "✅ Sent."
                if data.get("sent")
                else (
                    "Saved as a draft (not sent)."
                    if state in ("not_requested", "absent")
                    else f"Not sent — the approver rejected it ({data.get('approval_note:approval') or 'no note'}). The draft is saved."
                    if state == "rejected"
                    else "Draft saved."
                )
            )
            to = ", ".join(e["to"]) or "no recipients yet"
            parts.append(f"**To:** {to}  \n**Subject:** {e['subject']}\n\n{e['body']}\n\n{status}")
            if data.get("unresolved"):
                parts.append(f"I couldn't find email addresses for: {', '.join(data['unresolved'])}. Add them before sending.")
        if "comparison" in data:
            parts.append(_comparison_md(data))
            if data.get("purchase"):
                parts.append(f"✅ Booked: {data['purchase'].get('item')} — {data['purchase'].get('total')} (ref {data['purchase'].get('reference')}).")
            elif approval_state(data, "purchase") == "rejected":
                parts.append(f"Not purchased — the approver rejected it ({data.get('approval_note:purchase') or 'no note'}).")
        if data.get("summary_md"):
            parts.append(data["summary_md"])
        artifacts = [ArtifactRef(id=a["id"], name=a["name"], kind=a["kind"]) for a in data.get("artifacts", [])]
        handoffs = [HandoffRequest(**h) for h in data.get("handoffs", [])]
        return AgentResult(
            execution_id=ctx.execution_id,
            status="completed",
            summary="\n\n".join(parts) + fixture_note(data) or "Nothing produced.",
            claims=claims,
            artifacts=artifacts,
            handoffs=handoffs,
        )


# ── Simulator builders (offline/dev only) ────────────────────────────────────


@simulated.register("assistant.understand")
def _sim_understand(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    return {"needs_lookup": bool(re.search(r"opening hours|open|price|weather|today|this weekend|latest|current", o, re.I)), "query": o}


@simulated.register("assistant.answer")
def _sim_answer(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    if re.search(r"one-on-one|1:1", o, re.I):
        return "A simple weekly one-on-one:\n\n1. **Their agenda first (15 min)** — what's on their mind.\n2. **Progress and blockers (10 min).**\n3. **Growth (5 min)** — one thing to try before next week.\n\nKeep shared notes and end with clear owners."
    if re.search(r"agenda|kickoff", o, re.I):
        return "30-minute kickoff:\n\n1. Goals and success criteria (8 min)\n2. Scope and out-of-scope (7 min)\n3. Roles and owners (5 min)\n4. Risks and open questions (5 min)\n5. Next steps and dates (5 min)"
    return "Three tips:\n\n1. Plan the day's top three tasks before opening email.\n2. Block a 90-minute focus session in the morning.\n3. End the day by writing tomorrow's first task."


@simulated.register("assistant.propose")
def _sim_propose(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    m = re.search(r"with (\w+)", o)
    if re.search(r"\bbook\b|meeting|call", o, re.I):
        return {
            "events": [
                {
                    "title": f"Meeting{' with ' + m.group(1) if m else ''}",
                    "start": "2026-11-24T15:30:00",
                    "end": "2026-11-24T16:00:00",
                    "attendees": [m.group(1)] if m else [],
                }
            ],
            "notes": "Tuesday afternoon, after the Northwind call.",
        }
    return {
        "events": [
            {"title": "Focus block", "start": f"2026-11-{d}T{h}:00:00", "end": f"2026-11-{d}T{int(h) + 2:02d}:00:00", "attendees": []}
            for d, h in (("23", "10"), ("25", "09"), ("27", "13"))
        ],
        "notes": "Three 2-hour focus blocks around your existing meetings.",
    }


@simulated.register("assistant.draft")
def _sim_draft(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    if re.search(r"meeting notes", o, re.I):
        notes = req.sim_context.get("context") or []
        body = notes[0]["content"][:1500] if notes else "[paste the meeting notes here — I couldn't find them in Knowledge & Files]"
        return {"subject": "Meeting notes", "body": f"Hi all,\n\nHere are the notes from today's meeting:\n\n{body}\n\nBest,", "to_hints": ["team"]}
    if re.search(r"supplier|delivery", o, re.I):
        return {
            "subject": "Follow-up on our delivery",
            "body": "Hello,\n\nI'm following up on our order, which hasn't arrived yet. Could you let us know the new delivery date [add order number]?\n\nThank you,",
            "to_hints": ["supplier"],
        }
    return {
        "subject": "Thank you",
        "body": "Hi,\n\nThank you for speaking at our event — the sessions were a highlight for the audience.\n\nWarm regards,",
        "to_hints": ["speakers"],
    }


@simulated.register("assistant.compare")
def _sim_compare(req):  # type: ignore[no-untyped-def]
    items = []
    for r in req.sim_context["results"][:5]:
        name = r.get("name") or r.get("title")
        items.append(
            {
                "name": name,
                "price": r.get("price") or r.get("salary"),
                "pros": [r.get("notes") or r.get("location") or r.get("company") or "listed"],
                "cons": [],
                "url": r.get("url"),
            }
        )
    items.append(
        {"name": "Imaginary Option That Was Not Found", "price": "€1", "pros": ["too good to be true"], "cons": [], "url": None}
    )  # exercised by the listing check
    rec = f"{items[0]['name']} fits best on what's listed." if len(items) > 1 else ""
    return {"items": items, "recommendation": rec}


@simulated.register("assistant.route")
def _sim_route(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"].lower()
    rules = [
        ("research", r"research|competitor|find out|evidence"),
        ("marketing", r"campaign|marketing|post|launch"),
        ("engineer", r"test|bug|code|deploy|fix"),
        ("bi", r"revenue|kpi|metric|churn|quarter|data"),
        ("creative", r"ideas|brainstorm|names"),
    ]
    return {
        "handoffs": [
            {"agent": a, "objective": req.sim_context["objective"], "reason": f"{SPECIALISTS[a]} is this agent's specialty"}
            for a, p in rules
            if re.search(p, o)
        ]
    }
