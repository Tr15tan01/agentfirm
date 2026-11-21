"""AI Marketing agent program (manifest: agents/manifests/marketing.yaml).

Brand safety is enforced in code: every draft passes `brand_flags` (banned claims from
memory, guarantees, superlatives, and any figure the user didn't supply). Flagged drafts
are revised once; what remains flagged is reported, never silently published. Nothing is
posted or spent without an approved approval for that exact text/amount.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agentfirm.agents.contracts import AgentResult, ArtifactRef, Citation, Claim, HandoffRequest

from ..context import ExecutionContext, untrusted
from ..gateway import simulated
from .base import NUMBER, approval_state, art_ref, fixture_note, wants, word_count

SYSTEM = (
    "You are AgentFirm's Marketing agent. Write in the organisation's brand voice. Never invent "
    "results, statistics, customer quotes or guarantees: if a claim needs evidence you don't have, "
    "leave it out or mark it as an assumption."
)
RISKY = [
    r"\bguarantee[sd]?\b",
    r"\b(?:#1|number one|no\.\s*1)\b",
    r"\bbest(?:-in-class| in (?:the )?(?:world|market|class))\b",
    r"\b100%\b",
    r"\brisk[- ]free\b",
]


class Brief(BaseModel):
    product: str = ""
    audience: str = ""
    goal: str = ""
    market: str = ""
    channels: list[str] = Field(default_factory=list)
    budget_eur: float | None = None
    keywords: list[str] = Field(default_factory=list)


class Analysis(BaseModel):
    segments: list[str]
    positioning_options: list[str]
    recommended: str
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class Angles(BaseModel):
    angles: list[str]


class Piece(BaseModel):
    channel: str
    title: str = Field(max_length=240)
    body: str
    language: str = "en"
    date: str | None = None


class Pieces(BaseModel):
    pieces: list[Piece]


class Allocation(BaseModel):
    channel: str
    share: float = Field(ge=0, le=1)
    rationale: str = ""


class CampaignPlan(BaseModel):
    concept: str
    phases: list[str]
    allocation: list[Allocation]


class Kpi(BaseModel):
    name: str
    target: str
    how_measured: str


class Measurement(BaseModel):
    kpis: list[Kpi]


class PublishAction(BaseModel):
    action: str = Field(pattern="^(social.publish|ads.budget_change)$")
    channel: str = "linkedin"
    text: str = ""
    campaign: str = ""
    daily_budget: float | None = None
    currency: str = "EUR"


def brand_flags(text: str, banned: list[str], user_text: str) -> list[str]:
    """Deterministic brand/claims check. Figures are allowed only if the user supplied them."""
    flags = []
    low = text.lower()
    for b in banned:
        if b and b.lower() in low:
            flags.append(f"banned claim “{b}”")
    for pat in RISKY:
        if m := re.search(pat, text, re.I):
            flags.append(f"unsupported absolute claim “{m.group(0)}”")
    supplied = {n.strip().rstrip("%").replace(",", "") for n in NUMBER.findall(user_text)}
    for n in NUMBER.findall(text):
        core = n.strip().rstrip("%").replace(",", "")
        if "%" in n and core not in supplied:
            flags.append(f"unsourced figure “{n.strip()}”")
    return flags


async def _brand(ctx: ExecutionContext) -> dict[str, Any]:
    mem = (await ctx.tool("memory.read", keys=["brand_voice", "banned_claims", "product", "audience"])).get("memories", {})
    banned = [b.strip(" '\"“”") for b in re.split(r"[\n,;]", mem.get("banned_claims", "")) if b.strip()]
    return {"brand_voice": mem.get("brand_voice", ""), "banned": banned, "product_memory": mem.get("product", ""), "audience_memory": mem.get("audience", "")}


def _voice(d: dict[str, Any]) -> str:
    return f"Brand voice: {d.get('brand_voice') or 'not set — use clear, warm, plain language'}. Never use: {d.get('banned') or 'n/a'}."


async def _checked(ctx: ExecutionContext, d: dict[str, Any], pieces: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Check every piece; revise flagged ones once; return (pieces, remaining flags)."""
    out, remaining = [], []
    for p in pieces:
        flags = brand_flags(f"{p['title']} {p['body']}", d.get("banned", []), ctx.objective)
        if flags:
            await ctx.log("warn", f"Brand check flagged “{p['title'][:60]}”: {'; '.join(flags)} — revising")
            fixed = await ctx.structured(
                "revise",
                "text",
                Piece,
                system=SYSTEM + " Rewrite the piece to remove the flagged claims. Keep the message; drop numbers you can't source.",
                user=f"Flags: {flags}\n\nPiece: {p}",
                sim={"piece": p, "flags": flags},
            )
            p = fixed.model_dump()
            still = brand_flags(f"{p['title']} {p['body']}", d.get("banned", []), ctx.objective)
            remaining += [f"{p['title'][:60]}: {f}" for f in still]
        out.append(p)
    return out, remaining


# ── strategy ─────────────────────────────────────────────────────────────────


async def brief(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    b = await ctx.structured(
        "brief",
        "classify",
        Brief,
        system=SYSTEM + " Extract the marketing brief. Leave unknown fields empty.",
        user=f"Request: {ctx.objective}\nParameters: {ctx.parameters}",
        sim={"objective": ctx.objective, "params": ctx.parameters},
    )
    if ctx.parameters.get("budget") is not None:
        b.budget_eur = float(ctx.parameters["budget"])
    return {"brief": b.model_dump()}


async def brand(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out = await _brand(ctx)
    if "knowledge.retrieve" in (ctx.step_tools or ()):
        chunks = (await ctx.tool("knowledge.retrieve", query=ctx.objective, top_k=4)).get("chunks", [])
        out["knowledge"] = [{"title": c["title"], "url": c["url"], "content": c["content"][:1500]} for c in chunks]
    return out


async def evidence(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if not wants(ctx.objective, r"\bcompetit", r"\bevidence\b", r"\bmarket (?:size|research|data)\b", r"\bbacked\b", r"\bagainst\b"):
        return {"handoffs": []}
    h = await ctx.tool(
        "agents.delegate",
        to_agent="research",
        objective=f"Collect cited competitor and market evidence for: {ctx.objective[:300]}",
        reason="Strategy claims need verified sources",
        blocking=False,
    )
    return {"handoffs": [h["handoff"]]}


async def analyse(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    kb = "\n".join(untrusted(k["url"], k["content"], 1500) for k in d.get("knowledge", []))
    a = await ctx.structured(
        "analyse",
        "reasoning",
        Analysis,
        system=SYSTEM + " Analyse segments and positioning options. List assumptions explicitly.",
        user=f"Brief: {d.get('brief')}\nWorkspace knowledge:\n{kb or '(none)'}",
        sim={"objective": ctx.objective, "brief": d.get("brief")},
    )
    return {"analysis": a.model_dump()}


async def strategy(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    doc = await ctx.text(
        "strategy",
        "text",
        system=SYSTEM + " Write a one-page go-to-market strategy in Markdown: positioning, audience, channels, messages, risks, assumptions. " + _voice(d),
        user=f"Brief: {d.get('brief')}\nAnalysis: {d.get('analysis')}",
        sim={"objective": ctx.objective, "analysis": d.get("analysis")},
    )
    return {"strategy_md": doc}


async def brand_check_strategy(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    pieces, remaining = await _checked(ctx, d, [{"channel": "doc", "title": "Strategy", "body": d.get("strategy_md", "")}])
    return {"strategy_md": pieces[0]["body"], "brand_flags": remaining}


async def deliver_strategy(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out = await ctx.tool("artifact.write", name="strategy.md", content=d.get("strategy_md", ""), deliverable="strategy_doc")
    return {"artifacts": [art_ref(out)]}


# ── content ──────────────────────────────────────────────────────────────────


async def angles(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    a = await ctx.structured(
        "angles", "creative", Angles, system=SYSTEM + " Propose distinct message angles. " + _voice(d), user=ctx.objective, sim={"objective": ctx.objective}
    )
    return {"angles": a.angles[:6]}


async def draft(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    n = word_count(ctx.objective) or 3
    channels = (
        ctx.parameters.get("channels")
        or [c for c in ("linkedin", "instagram", "x", "facebook", "email", "newsletter", "blog") if c in ctx.objective.lower()]
        or ["linkedin"]
    )
    p = await ctx.structured(
        "draft",
        "text",
        Pieces,
        system=SYSTEM + f" Write {n} pieces for {channels}. " + _voice(d),
        user=f"Request: {ctx.objective}\nAngles: {d.get('angles')}\nLanguages: {ctx.parameters.get('languages') or ['en']}",
        sim={"objective": ctx.objective, "n": n, "channels": channels, "angles": d.get("angles", [])},
    )
    return {"pieces": [x.model_dump() for x in p.pieces[: max(n, len(channels))]]}


async def brand_check_content(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    pieces, remaining = await _checked(ctx, d, d.get("pieces", []))
    return {"pieces": pieces, "brand_flags": remaining}


def _pieces_md(pieces: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"### {p['title']} · {p['channel']}\n\n{p['body']}" for p in pieces)


async def save_content(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    pieces = d.get("pieces", [])
    cal = await ctx.tool("content.calendar_write", entries=pieces)
    out = await ctx.tool("artifact.write", name="posts.md", content=_pieces_md(pieces), deliverable="social_posts")
    return {"calendar_ids": cal.get("created", []), "artifacts": [art_ref(out)]}


# ── campaign ─────────────────────────────────────────────────────────────────


async def keywords(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    kws = d.get("brief", {}).get("keywords") or []
    if not kws:
        return {"keywords": []}
    out = await ctx.tool("seo.keywords", keywords=kws, locale=(ctx.parameters.get("languages") or ["en"])[0])
    return {"keywords": out.get("keywords", []), "fixture:keywords": bool(out.get("fixture"))}


async def concepts(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    h = await ctx.tool(
        "agents.delegate",
        to_agent="creative",
        objective=f"Campaign concepts for: {ctx.objective[:300]}",
        reason="Concept ideation is the Creative agent's job",
        blocking=False,
    )
    return {"handoffs": [h["handoff"]]}


async def plan(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    b = d.get("brief", {})
    p = await ctx.structured(
        "plan",
        "reasoning",
        CampaignPlan,
        system=SYSTEM + " Plan the campaign: one concept, phases, and the budget share per channel (shares sum to 1).",
        user=f"Brief: {b}\nKeyword data: {d.get('keywords')}",
        sim={"objective": ctx.objective, "brief": b},
    )
    total = sum(a.share for a in p.allocation) or 1.0
    budget = b.get("budget_eur")
    rows = [
        {"channel": a.channel, "share": round(a.share / total, 4), "eur": round(budget * a.share / total, 2) if budget else None, "rationale": a.rationale}
        for a in p.allocation
    ]
    return {"campaign": p.model_dump() | {"allocation": rows}}


async def measure(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    m = await ctx.structured(
        "measure",
        "reasoning",
        Measurement,
        system=SYSTEM + " Define KPIs with targets and how each is measured. Targets are goals, not forecasts.",
        user=f"Campaign: {d.get('campaign')}",
        sim={"objective": ctx.objective},
    )
    return {"kpis": [k.model_dump() for k in m.kpis]}


async def deliver_campaign(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    c = d.get("campaign", {})
    alloc = "\n".join(
        f"| {a['channel']} | {a['share']:.0%} | {'€{:,.2f}'.format(a['eur']) if a['eur'] is not None else '—'} | {a['rationale']} |"
        for a in c.get("allocation", [])
    )
    kpis = "\n".join(f"- **{k['name']}** — target {k['target']} ({k['how_measured']})" for k in d.get("kpis", []))
    kw = "\n".join(f"- {k['keyword']}: ~{k['monthly_volume']}/month, difficulty {k['difficulty']}" for k in d.get("keywords", []))
    md = (
        f"# Campaign brief\n\n**Concept.** {c.get('concept', '')}\n\n## Phases\n"
        + "\n".join(f"{n}. {p}" for n, p in enumerate(c.get("phases", []), 1))
        + "\n\n## Budget allocation\n| Channel | Share | Amount | Why |\n|---|---|---|---|\n"
        + alloc
        + f"\n\n## KPIs\n{kpis}"
        + (f"\n\n## Keyword data\n{kw}" if kw else "")
    )
    out = await ctx.tool("artifact.write", name="campaign_brief.md", content=md, deliverable="campaign_brief")
    return {"campaign_md": md, "artifacts": [art_ref(out)]}


# ── publish ──────────────────────────────────────────────────────────────────


async def prepare(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    a = await ctx.structured(
        "prepare",
        "text",
        PublishAction,
        system=SYSTEM
        + " Prepare exactly one action: a social post (action social.publish, final text) or an ad budget change (action ads.budget_change, campaign + new daily budget). Use the user's own text if they gave it.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    if a.action == "social.publish":
        flags = brand_flags(a.text, [], ctx.objective)  # banned claims are checked when drafts are written
        return {"action": a.model_dump(), "brand_flags": flags}
    return {"action": a.model_dump()}


async def execute(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d) != "approved":
        return {"executed": None}
    a = d["action"]
    if a["action"] == "social.publish":
        out = await ctx.tool("social.publish", channel=a["channel"], text=a["text"])
    else:
        out = await ctx.tool("ads.budget_change", campaign=a["campaign"], daily_budget=a["daily_budget"], currency=a["currency"])
    return {"executed": out, "fixture:execute": bool(out.get("fixture"))}


async def confirm(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    state = approval_state(d)
    if state == "rejected":
        note = d.get("approval_note:approval", "")
        a = d["action"]
        if a["action"] == "social.publish":
            revised = await ctx.structured(
                "revise",
                "text",
                Piece,
                system=SYSTEM + " Revise the post to address the reviewer's feedback.",
                user=f"Feedback: {note}\nPost: {a['text']}",
                sim={"piece": {"channel": a["channel"], "title": "Revised post", "body": a["text"]}, "flags": [note]},
            )
            return {"revised": revised.model_dump()}
        return {"revised": None}
    if state == "approved":
        ok = bool(d.get("executed")) and d["executed"].get("status") in ("published", "applied", "scheduled", "ok", "done")
        if not ok:
            await ctx.log("warn", f"Could not confirm the action from the connector response: {str(d.get('executed'))[:200]}")
        return {"confirmed": ok}
    return {}


# ── performance ──────────────────────────────────────────────────────────────


async def fetch(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out = await ctx.tool("ads.performance_read", period=ctx.parameters.get("period", "last_30_days"))
    return {"campaigns": out.get("campaigns", []), "fixture:fetch": bool(out.get("fixture")), "metrics_source": out.get("via", "ad accounts")}


def _metrics(c: dict[str, Any]) -> dict[str, Any]:
    def div(a: float | None, b: float | None) -> float | None:
        return round(a / b, 4) if a is not None and b else None

    return c | {
        "cpa": div(c.get("spend"), c.get("conversions")),
        "ctr": div(c.get("clicks"), c.get("impressions")),
        "cvr": div(c.get("conversions"), c.get("clicks")),
    }


async def analyse_performance(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    rows = [_metrics(c) for c in d.get("campaigns", [])]
    return {"metrics": rows}


async def recommend(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    rows = d.get("metrics", [])
    if not rows:
        return {"performance_md": "No campaign data was returned by the connected ad accounts, so there is nothing to evaluate yet."}
    table = "| Campaign | Spend | Conversions | CPA | CTR | CVR |\n|---|---|---|---|---|---|\n" + "\n".join(
        f"| {r['campaign']} | €{r.get('spend', 0):,.0f} | {r.get('conversions', 0)} | {'€{:.2f}'.format(r['cpa']) if r['cpa'] is not None else '—'} | {f'{r["ctr"]:.2%}' if r['ctr'] is not None else '—'} | {f'{r["cvr"]:.2%}' if r['cvr'] is not None else '—'} |"
        for r in rows
    )
    text = await ctx.text(
        "recommend",
        "reasoning",
        system=SYSTEM + " Interpret these computed metrics and recommend next actions. Quote only the numbers in the table.",
        user=table,
        sim={"rows": rows},
    )
    return {"performance_md": f"## Campaign performance\n\n{table}\n\n{text}"}


async def deliver_performance(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out = await ctx.tool("artifact.write", name="performance_report.md", content=d.get("performance_md", ""), deliverable="performance_report")
    return {"artifacts": [art_ref(out)]}


# ── Program ──────────────────────────────────────────────────────────────────


class MarketingProgram:
    key = "marketing"
    handlers = {
        "strategy": {
            "brief": brief,
            "brand": brand,
            "evidence": evidence,
            "analyse": analyse,
            "strategy": strategy,
            "brand_check": brand_check_strategy,
            "deliver": deliver_strategy,
        },
        "content": {"brand": brand, "angles": angles, "draft": draft, "brand_check": brand_check_content, "save": save_content},
        "campaign": {"objective": brief, "keywords": keywords, "concepts": concepts, "plan": plan, "measure": measure, "deliver": deliver_campaign},
        "publish": {"prepare": prepare, "execute": execute, "confirm": confirm},
        "performance": {"fetch": fetch, "analyse": analyse_performance, "recommend": recommend, "deliver": deliver_performance},
    }

    def approval_scope(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> list[str] | None:
        return [data["action"]["action"]] if data.get("action") else []

    def approval_facts(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> dict[str, Any]:
        """Facts a standing approval's conditions can check (ADR 0006)."""
        a = data.get("action") or {}
        if a.get("action") == "social.publish":
            return {"channel": a.get("channel")}
        if a.get("action") == "ads.budget_change":
            return {"amount": a.get("daily_budget"), "currency": a.get("currency"), "campaign": a.get("campaign")}
        return {}

    def approval_preview(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> str | None:
        a = data.get("action") or {}
        if a.get("action") == "social.publish":
            flags = data.get("brand_flags") or []
            return f"Publish to: {a['channel']}\n\n{a['text']}" + (f"\n\n⚠ Brand check: {'; '.join(flags)}" if flags else "")
        if a.get("action") == "ads.budget_change":
            return f"Change the daily budget of “{a['campaign']}” to {a['currency']} {a['daily_budget']:,.2f}."
        return None

    def finalize(self, ctx: ExecutionContext, data: dict[str, Any]) -> AgentResult:
        parts: list[str] = []
        claims: list[Claim] = []
        if data.get("strategy_md"):
            parts.append(data["strategy_md"])
            claims += [Claim(text=a, status="assumption") for a in (data.get("analysis") or {}).get("assumptions", [])]
        if data.get("pieces"):
            parts.append(_pieces_md(data["pieces"]) + f"\n\n_Saved {len(data.get('calendar_ids', []))} drafts to the content calendar. Nothing was published._")
        if data.get("campaign_md"):
            parts.append(data["campaign_md"])
        if data.get("performance_md"):
            parts.append(data["performance_md"])
            for r in data.get("metrics", []):
                if r.get("cpa") is not None:
                    claims.append(
                        Claim(
                            text=f"{r['campaign']}: CPA €{r['cpa']:.2f} ({r['conversions']} conversions on €{r['spend']:,.0f} spend)",
                            status="verified",
                            citations=[
                                Citation(
                                    source_id="ads",
                                    title=f"Ad account metrics via {data.get('metrics_source', 'connector')}",
                                    excerpt=f"spend {r['spend']}, conversions {r['conversions']}",
                                )
                            ],
                        )
                    )
        if data.get("action"):
            a, state = data["action"], approval_state(data)
            what = f"post on {a['channel']}" if a["action"] == "social.publish" else f"budget change for “{a['campaign']}”"
            if state == "approved" and data.get("confirmed"):
                parts.append(f"✅ Done: the {what} went through ({(data.get('executed') or {}).get('url') or (data.get('executed') or {}).get('status')}).")
            elif state == "approved":
                parts.append(f"⚠ The {what} was approved, but the connector didn't confirm it. Please check the account.")
            elif state == "rejected":
                rev = data.get("revised")
                parts.append(f"The {what} was **not** carried out: the approver rejected it ({data.get('approval_note:approval') or 'no note'}).")
                if rev:
                    parts.append(f"Here's a revised version for a new approval:\n\n{rev['body']}")
        if data.get("brand_flags"):
            parts.append("**Brand check — still needs a human look:**\n" + "\n".join(f"- {f}" for f in data["brand_flags"]))
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


def _topic(o: str) -> str:
    stop = {
        "write",
        "draft",
        "create",
        "plan",
        "three",
        "short",
        "posts",
        "post",
        "about",
        "our",
        "the",
        "for",
        "and",
        "new",
        "a",
        "an",
        "with",
        "how",
        "should",
        "we",
    }
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]+", o) if w.lower() not in stop and len(w) > 2]
    return " ".join(words[:4]) or "our product"


@simulated.register("marketing.brief")
def _sim_brief(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    m = re.search(r"€\s?(\d+(?:[.,]\d+)?)\s*(k)?", o, re.I)
    budget = float(m.group(1).replace(",", ".")) * (1000 if m.group(2) else 1) if m else None
    chans = [c for c in ("linkedin", "instagram", "email", "meta", "google") if c in o.lower()]
    return {
        "product": "AgentFirm tutoring beta",
        "audience": "adult learners",
        "goal": "signups",
        "market": "Poland" if "poland" in o.lower() else "",
        "channels": chans,
        "budget_eur": budget,
        "keywords": [f"{_topic(o).lower()}", "online tutoring for adults"],
    }


@simulated.register("marketing.analyse")
def _sim_analyse(req):  # type: ignore[no-untyped-def]
    return {
        "segments": ["Working professionals (25-45)", "Career changers"],
        "positioning_options": ["Human tutor + AI practice", "Exam-focused intensive"],
        "recommended": "Human tutor + AI practice",
        "risks": ["Price sensitivity vs free apps"],
        "assumptions": ["Adult learners value live feedback over gamification", "Competitor pricing has not changed this quarter"],
    }


@simulated.register("marketing.strategy")
def _sim_strategy(req):  # type: ignore[no-untyped-def]
    a = req.sim_context.get("analysis") or {}
    return (
        f"# Go-to-market strategy\n\n**Positioning.** {a.get('recommended', 'Human tutor + AI practice')}: the guidance of a real tutor, with AI practice between sessions.\n\n"
        f"**Audience.** {', '.join(a.get('segments', []))}.\n\n**Channels.** LinkedIn for professionals, email for the beta waitlist.\n\n"
        "**Messages.** Learn with a person, practise any time. Guaranteed results in 30 days.\n\n**Risks.** Price sensitivity versus free apps."
    )


@simulated.register("marketing.angles")
def _sim_angles(req):  # type: ignore[no-untyped-def]
    t = _topic(req.sim_context["objective"])
    return {"angles": [f"Why {t} needs a human touch", f"Behind the scenes of {t}", f"What early users asked for in {t}"]}


@simulated.register("marketing.draft")
def _sim_draft(req):  # type: ignore[no-untyped-def]
    c = req.sim_context
    t, angles = _topic(c["objective"]), c.get("angles") or ["An update"]
    out = []
    for i in range(max(c["n"], len(c["channels"]))):
        body = f"{angles[i % len(angles)]}. We built {t} with real learners — here's what changed and why it matters to you."
        if i == 0:
            body += " Learners improve 40% faster."  # exercised by the brand check: unsourced figure
        out.append({"channel": c["channels"][i % len(c["channels"])], "title": angles[i % len(angles)][:200], "body": body, "language": "en"})
    return {"pieces": out}


@simulated.register("marketing.revise")
def _sim_revise(req):  # type: ignore[no-untyped-def]
    p = dict(req.sim_context["piece"])
    body = re.sub(r"\s*[^.]*\d+%[^.]*\.", "", p["body"])
    body = re.sub(r"\s*[^.]*\bguarantee[sd]?\b[^.]*\.", "", body, flags=re.I)
    p["body"] = body.strip() or "Learn with a real tutor and practise any time."
    p.setdefault("language", "en")
    return p


@simulated.register("marketing.plan")
def _sim_plan(req):  # type: ignore[no-untyped-def]
    chans = (req.sim_context.get("brief") or {}).get("channels") or ["linkedin", "email"]
    share = round(1 / len(chans), 4)
    return {
        "concept": "Learn with a person, practise any time",
        "phases": ["Teaser to waitlist", "Launch week", "Retargeting and referrals"],
        "allocation": [{"channel": c, "share": share, "rationale": "Reaches the core audience"} for c in chans],
    }


@simulated.register("marketing.measure")
def _sim_measure(req):  # type: ignore[no-untyped-def]
    return {
        "kpis": [
            {"name": "Beta signups", "target": "200 seats filled", "how_measured": "Signup events in the product"},
            {"name": "Cost per signup", "target": "≤ €25", "how_measured": "Ad spend ÷ attributed signups"},
        ]
    }


@simulated.register("marketing.prepare")
def _sim_prepare(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    if re.search(r"budget|€|per day|spend", o, re.I):
        m = re.search(r"€\s?(\d+(?:[.,]\d+)?)", o)
        camp = "Autumn intake — Meta" if "meta" in o.lower() else "Brand search"
        return {"action": "ads.budget_change", "campaign": camp, "daily_budget": float(m.group(1).replace(",", ".")) if m else 50.0, "currency": "EUR"}
    text = (
        o.split(":", 1)[1].strip()
        if ":" in o
        else "Our tutoring beta is open: learn with a real tutor and practise with AI between sessions. Join the waitlist."
    )
    return {"action": "social.publish", "channel": "linkedin", "text": text}


@simulated.register("marketing.recommend")
def _sim_recommend(req):  # type: ignore[no-untyped-def]
    rows = sorted([r for r in req.sim_context["rows"] if r.get("cpa") is not None], key=lambda r: r["cpa"])
    if not rows:
        return "No campaign had conversions to compare."
    return f"**Recommendation.** Shift budget toward “{rows[0]['campaign']}” (lowest CPA) and review “{rows[-1]['campaign']}” (highest CPA) before its next flight."
