"""Creative & Brainstorming agent program (manifest: agents/manifests/creative.yaml)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentfirm.agents.contracts import AgentResult, ArtifactRef, Claim

from ..context import ExecutionContext
from ..gateway import simulated
from ..gateway.simulated import tokens

Approach = Literal["divergent", "convergent", "first_principles", "lateral", "scamper", "six_hats", "analogical", "debate", "premortem"]

LENSES: dict[str, list[str]] = {
    "six_hats": ["White hat — facts", "Red hat — feelings", "Black hat — risks", "Yellow hat — benefits", "Green hat — creativity", "Blue hat — process"],
    "scamper": ["Substitute", "Combine", "Adapt", "Modify", "Put to another use", "Eliminate", "Reverse"],
    "premortem": ["Failure mode: demand", "Failure mode: execution", "Failure mode: competition", "Failure mode: economics", "Early warning signals"],
    "debate": ["Case for", "Case against", "Rebuttal", "Synthesis"],
    "analogical": ["Borrowed from fitness", "Borrowed from gaming", "Borrowed from banking", "Borrowed from music"],
    "first_principles": ["Fundamental truths", "Constraints", "Cost drivers", "Rebuilt solution"],
    "lateral": ["Random entry", "Provocation", "Reversal", "Escape"],
}
GENERIC = re.compile(r"\b(gamif\w*|social media (campaign|presence)|ai[- ]powered|use ai|loyalty program|newsletter|mobile app|chatbot)\b", re.I)


# ── Output schemas ───────────────────────────────────────────────────────────


class Frame(BaseModel):
    objective: str
    approach: Approach
    constraints: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=lambda: ["impact", "feasibility", "novelty"])
    rationale: str = ""


class IdeaDraft(BaseModel):
    title: str = Field(max_length=160)
    summary: str = Field(max_length=800)
    lens: str | None = None
    tags: list[str] = Field(default_factory=list)


class IdeaBatch(BaseModel):
    ideas: list[IdeaDraft]


class AssumptionCheck(BaseModel):
    assumption: str
    challenge: str


class Challenges(BaseModel):
    assumptions: list[AssumptionCheck]


class IdeaScore(BaseModel):
    index: int = Field(ge=0)
    impact: int = Field(ge=1, le=10)
    feasibility: int = Field(ge=1, le=10)
    novelty: int = Field(ge=1, le=10)
    rationale: str = ""


class Scores(BaseModel):
    scores: list[IdeaScore]


class Section(BaseModel):
    lens: str
    points: list[str]


class FrameworkOut(BaseModel):
    sections: list[Section]
    actions: list[str]


class RankItem(BaseModel):
    option: str
    score: int = Field(ge=1, le=10)
    strengths: list[str]
    risks: list[str]


class Evaluation(BaseModel):
    ranking: list[RankItem]
    recommendation: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _choose_approach(ctx: ExecutionContext, objective: str) -> Approach | None:
    explicit = ctx.parameters.get("approach")
    if explicit in LENSES or explicit in ("divergent", "convergent"):
        return explicit  # type: ignore[return-value]
    low = objective.lower()
    for key, words in {
        "premortem": ["premortem", "pre-mortem"],
        "six_hats": ["six thinking hats", "six hats"],
        "scamper": ["scamper"],
        "debate": ["debate"],
        "first_principles": ["first principles"],
    }.items():
        if any(w in low for w in words):
            return key  # type: ignore[return-value]
    return None


def _norm(title: str) -> set[str]:
    return tokens(title)


def _similar(a: str, b: str) -> bool:
    ta, tb = _norm(a), _norm(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6


def diversity_filter(ideas: list[dict[str, Any]], existing: list[str], rejected: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop near-duplicates, board repeats, rejected ideas and generic suggestions (deterministic)."""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for i in ideas:
        title = i["title"]
        if any(_similar(title, r) for r in rejected):
            dropped.append(f"{title} (previously rejected)")
        elif any(_similar(title, e) for e in existing):
            dropped.append(f"{title} (already on the board)")
        elif any(_similar(title, k["title"]) for k in kept):
            dropped.append(f"{title} (duplicate)")
        elif GENERIC.search(f"{title} {i['summary']}"):
            dropped.append(f"{title} (generic)")
        else:
            kept.append(i)
    return kept, dropped


def _ideas_md(ideas: list[dict[str, Any]]) -> str:
    lines = []
    for n, i in enumerate(ideas, 1):
        s = i.get("scores") or {}
        score = f" — impact {s.get('impact')}/10 · feasibility {s.get('feasibility')}/10 · novelty {s.get('novelty')}/10" if s else ""
        lens = f" _({i['lens']})_" if i.get("lens") else ""
        lines.append(f"{n}. **{i['title']}**{lens}{score}\n   {i['summary']}")
    return "\n".join(lines)


SYSTEM = (
    "You are AgentFirm's Creative & Brainstorming agent. Produce specific, non-generic ideas. "
    "Ideas are possibilities, not facts: never present invented statistics as true."
)


# ── Handlers: ideation ───────────────────────────────────────────────────────


async def frame(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    f = await ctx.structured(
        "frame",
        "reasoning",
        Frame,
        system=SYSTEM + " Frame the objective and pick the best thinking approach.",
        user=f"Objective: {ctx.objective}\nUser parameters: {ctx.parameters}",
        sim={"objective": ctx.objective, "approach": _choose_approach(ctx, ctx.objective)},
    )
    if (forced := _choose_approach(ctx, ctx.objective)) is not None:
        f.approach = forced
    return {"frame": f.model_dump()}


async def context(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    board = await ctx.tool("ideas.board_read", limit=200)
    mem = await ctx.tool("memory.read", keys=["rejected_ideas", "preferred_approaches"])
    rejected = [r.strip() for r in mem.get("memories", {}).get("rejected_ideas", "").split("\n") if r.strip()]
    return {"existing_titles": [i["title"] for i in board.get("ideas", [])], "rejected": rejected}


async def diverge(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    f = Frame(**d["frame"])
    n = int(ctx.parameters.get("count", 12))
    batch = await ctx.structured(
        "diverge",
        "creative",
        IdeaBatch,
        system=SYSTEM + f" Use the {f.approach} approach. Lenses: {LENSES.get(f.approach, ['open'])}. Avoid these existing or rejected ideas.",
        user=f"Objective: {f.objective}\nConstraints: {f.constraints}\nGenerate {n + 4} ideas.\nAvoid: {d.get('existing_titles', [])[:50] + d.get('rejected', [])}",
        sim={"objective": f.objective, "approach": f.approach, "count": n + 4, "avoid": d.get("existing_titles", []) + d.get("rejected", [])},
    )
    return {"raw_ideas": [i.model_dump() | {"approach": f.approach} for i in batch.ideas]}


async def dedupe(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    kept, dropped = diversity_filter(d.get("raw_ideas", []), d.get("existing_titles", []), d.get("rejected", []))
    n = int(ctx.parameters.get("count", 12))
    if dropped:
        await ctx.log("info", f"Diversity filter removed {len(dropped)}: " + "; ".join(dropped)[:1500])
    return {"ideas": kept[:n], "dropped": dropped}


async def challenge(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    c = await ctx.structured(
        "challenge",
        "reasoning",
        Challenges,
        system=SYSTEM + " List the hidden assumptions behind these ideas and challenge each.",
        user=f"Objective: {ctx.objective}\nIdeas:\n{_ideas_md(d.get('ideas', []))}",
        sim={"objective": ctx.objective},
    )
    return {"assumptions": [a.model_dump() for a in c.assumptions]}


async def score(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    ideas = d.get("ideas", [])
    sc = await ctx.structured(
        "score",
        "reasoning",
        Scores,
        system=SYSTEM + " Score each idea 1-10 on impact, feasibility and novelty. Scores are judgement.",
        user="\n".join(f"[{n}] {i['title']}: {i['summary']}" for n, i in enumerate(ideas)),
        sim={"titles": [i["title"] for i in ideas]},
    )
    by_index = {s.index: s for s in sc.scores}
    scored = [i | {"scores": {k: getattr(by_index[n], k) for k in ("impact", "feasibility", "novelty")}} if n in by_index else i for n, i in enumerate(ideas)]
    scored.sort(key=lambda i: -sum((i.get("scores") or {}).values()))
    return {"ideas": scored}


async def save(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    ideas = d.get("ideas") or d.get("framework_ideas") or []
    tags = [t for t in ["Generated", *(Frame(**d["frame"]).constraints[:1] if d.get("frame") else [])] if t]
    out = await ctx.tool("ideas.board_write", ideas=[{**i, "tags": i.get("tags") or tags, "column": "new"} for i in ideas])
    data: dict[str, Any] = {"saved_ids": out.get("created", [])}
    if d.get("ideas") and not d.get("framework"):
        art = await ctx.tool("artifact.write", name="ideas.md", content=_ideas_md(ideas), deliverable="idea_collection")
        data["artifacts"] = [*d.get("artifacts", []), {"id": art["artifact_id"], "name": art["name"], "kind": "md"}]
    if d.get("framework"):
        art = await ctx.tool("artifact.write", name="framework_output.md", content=d["framework_md"], deliverable="framework_output")
        data["artifacts"] = [*d.get("artifacts", []), {"id": art["artifact_id"], "name": art["name"], "kind": "md"}]
    return data


# ── Handlers: evaluation ─────────────────────────────────────────────────────


async def eval_criteria(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    crit = ctx.parameters.get("criteria") or ["impact", "feasibility", "risk", "differentiation"]
    return {"criteria": crit}


async def eval_analyse(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    ev = await ctx.structured(
        "evaluate",
        "reasoning",
        Evaluation,
        system=SYSTEM + " Critically evaluate each option against the criteria. Be direct about weaknesses.",
        user=f"Request: {ctx.objective}\nCriteria: {d.get('criteria')}",
        sim={"objective": ctx.objective},
    )
    return {"evaluation": ev.model_dump()}


async def eval_compare(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    ev = Evaluation(**d["evaluation"])
    ranked = sorted(ev.ranking, key=lambda r: -r.score)
    md = "\n".join(
        f"{n}. **{r.option}** — {r.score}/10\n   Strengths: {'; '.join(r.strengths)}\n   Risks: {'; '.join(r.risks)}" for n, r in enumerate(ranked, 1)
    )
    return {"evaluation_md": f"{md}\n\n**Recommendation:** {ev.recommendation}"}


async def eval_save(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    art = await ctx.tool("artifact.write", name="ranked_proposals.md", content=d.get("evaluation_md", ""), deliverable="ranked_proposals")
    return {"artifacts": [{"id": art["artifact_id"], "name": art["name"], "kind": "md"}]}


# ── Handlers: framework session ──────────────────────────────────────────────


async def fw_setup(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    f = await frame(ctx, d)
    fr = Frame(**f["frame"])
    if fr.approach in ("divergent", "convergent"):
        fr.approach = "six_hats"
    return {"frame": fr.model_dump()}


async def fw_perspectives(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    fr = Frame(**d["frame"])
    lenses = LENSES[fr.approach]
    out = await ctx.structured(
        "framework",
        "creative",
        FrameworkOut,
        system=SYSTEM + f" Run the {fr.approach} framework. Produce one section per lens: {lenses}. End with concrete actions.",
        user=f"Problem: {fr.objective}",
        sim={"objective": fr.objective, "lenses": lenses},
    )
    have = {s.lens for s in out.sections}
    missing = [lens for lens in lenses if lens not in have]
    if missing:
        await ctx.log("warn", f"Framework output missed lenses: {missing}")
    return {"framework": out.model_dump()}


async def fw_synthesis(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    fw = FrameworkOut(**d["framework"])
    md = "\n\n".join(f"### {s.lens}\n" + "\n".join(f"- {p}" for p in s.points) for s in fw.sections)
    md += "\n\n### Next actions\n" + "\n".join(f"{n}. {a}" for n, a in enumerate(fw.actions, 1))
    ideas = [
        {
            "title": a[:160],
            "summary": f"Action from {Frame(**d['frame']).approach.replace('_', ' ')} session: {a}",
            "lens": "Action",
            "approach": Frame(**d["frame"]).approach,
        }
        for a in fw.actions[:6]
    ]
    return {"framework_md": md, "framework_ideas": ideas}


# ── Handlers: develop & hand off ─────────────────────────────────────────────

HANDOFF_WORDS = {
    "marketing": "marketing",
    "campaign": "marketing",
    "research": "research",
    "validate": "research",
    "engineer": "engineer",
    "build": "engineer",
    "bi ": "bi",
    "business case": "bi",
}


async def dev_read(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    board = await ctx.tool("ideas.board_read", limit=50)
    m = re.search(r"[\"“](.+?)[\"”]", ctx.objective)
    target = m.group(1) if m else None
    chosen = next((i for i in board["ideas"] if target and _similar(i["title"], target)), board["ideas"][0] if board["ideas"] else None)
    return {"idea": chosen or {"title": target or ctx.objective[:120], "summary": ctx.objective}}


async def dev_develop(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    idea = d["idea"]
    concept = await ctx.text(
        "develop",
        "creative",
        system=SYSTEM + " Develop the idea into a concept: problem, audience, solution, differentiation, risks, open questions.",
        user=f"Idea: {idea['title']} — {idea['summary']}",
        sim={"idea": idea},
    )
    return {"concept_md": concept}


async def dev_brief(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    brief = await ctx.text(
        "brief",
        "reasoning",
        system=SYSTEM + " Write a one-page creative brief another agent can execute.",
        user=d["concept_md"],
        sim={"idea": d["idea"]},
    )
    art = await ctx.tool("artifact.write", name="creative_brief.md", content=brief, deliverable="creative_brief")
    return {"brief_md": brief, "artifacts": [{"id": art["artifact_id"], "name": art["name"], "kind": "md"}]}


async def dev_handoff(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    low = f" {ctx.objective.lower()} "
    target = next((agent for word, agent in HANDOFF_WORDS.items() if word in low), None)
    if target is None:
        return {"handoffs": []}
    out = await ctx.tool(
        "agents.delegate",
        to_agent=target,
        objective=f"Act on this creative brief: {d['idea']['title']}",
        reason="Selected idea developed into a brief",
        blocking=False,
    )
    return {"handoffs": [out["handoff"]]}


# ── Program ──────────────────────────────────────────────────────────────────


class CreativeProgram:
    key = "creative"
    handlers = {
        "ideation": {"frame": frame, "context": context, "diverge": diverge, "dedupe": dedupe, "challenge": challenge, "score": score, "save": save},
        "evaluation": {"criteria": eval_criteria, "analyse": eval_analyse, "compare": eval_compare, "save": eval_save},
        "framework_session": {"setup": fw_setup, "perspectives": fw_perspectives, "synthesis": fw_synthesis, "save": save},
        "develop": {"read": dev_read, "develop": dev_develop, "brief": dev_brief, "handoff": dev_handoff},
    }

    def approval_preview(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> str | None:
        return None

    def finalize(self, ctx: ExecutionContext, data: dict[str, Any]) -> AgentResult:
        ideas = data.get("ideas") or data.get("framework_ideas") or []
        parts: list[str] = []
        if data.get("framework_md"):
            parts.append(data["framework_md"])
        elif data.get("evaluation_md"):
            parts.append(data["evaluation_md"])
        elif data.get("brief_md"):
            parts.append(data["brief_md"])
        if ideas and not data.get("framework_md"):
            parts.append(_ideas_md(ideas))
        if data.get("assumptions"):
            parts.append("**Assumptions challenged**\n" + "\n".join(f"- *{a['assumption']}* — {a['challenge']}" for a in data["assumptions"]))
        if data.get("saved_ids"):
            parts.append(f"_Saved {len(data['saved_ids'])} ideas to your idea board. Scores are judgement, not measurements._")
        claims = [Claim(text=f"{i['title']}: {i['summary']}", status="speculative") for i in ideas]
        artifacts = [ArtifactRef(id=a["id"], name=a["name"], kind=a["kind"]) for a in data.get("artifacts", [])]
        from agentfirm.agents.contracts import HandoffRequest

        handoffs = [
            HandoffRequest(to_agent=h["to_agent"], objective=h["objective"], reason=h["reason"], blocking=h["blocking"]) for h in data.get("handoffs", [])
        ]
        return AgentResult(
            execution_id=ctx.execution_id,
            status="completed",
            summary="\n\n".join(parts) or "No ideas produced.",
            claims=claims,
            artifacts=artifacts,
            handoffs=handoffs,
        )


# ── Simulator builders (offline/dev only) ────────────────────────────────────

TEMPLATES = [
    ("{T} in 15 minutes a day", "Short daily sessions built around {t}, so progress becomes a habit rather than a project."),
    ("The {T} sprint", "A fixed six-week programme for {t} with a visible finish line and weekly checkpoints."),
    ("{T} for teams", "A B2B version of {t} that runs inside a company's existing meetings and tools."),
    ("Proof-of-progress for {t}", "A verifiable record of {t} outcomes that people can share with employers or partners."),
    ("{T} without the classroom", "Audio-first micro-lessons for {t} that fit commutes and queues."),
    ("Peer circles for {t}", "Small cohorts of four that hold each other accountable on {t}."),
    ("{T} concierge", "A human expert reviews each week of {t} and adjusts the plan."),
    ("Reverse {t}", "Learners teach a beginner what they just learned about {t}, locking it in."),
    ("{T} pay-as-you-improve", "Pricing for {t} tied to measured improvement rather than hours."),
    ("Local {t} partnerships", "Partner with libraries and coworking spaces to host {t} sessions."),
    ("{T} starter kit", "A boxed first month of {t} with a printed plan and a mentor call."),
    ("Seasonal {t} challenge", "A public 30-day {t} challenge timed to the start of each quarter."),
    ("{T} for parents", "Evening and weekend {t} formats designed around childcare."),
    ("Exam-day {t} rehearsal", "Full simulation days for {t} with feedback the same afternoon."),
    ("{T} office hours", "Drop-in expert hours for {t}, booked like a doctor's appointment."),
    ("Open-source {t} curriculum", "Publish the {t} curriculum openly and sell the coaching on top."),
]
STOP = {"brainstorm", "ideas", "idea", "names", "name", "give", "generate", "our", "the", "for", "with", "and", "new", "more", "about", "some"}


def _topic(objective: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]+", objective) if w.lower() not in STOP and len(w) > 2]
    return " ".join(words[-3:]).lower() or "your idea"


def _h(s: str, mod: int) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16) % mod


@simulated.register("creative.frame")
def _sim_frame(req):  # type: ignore[no-untyped-def]
    ctx = req.sim_context
    return {
        "objective": ctx["objective"],
        "approach": ctx.get("approach") or "divergent",
        "constraints": [],
        "criteria": ["impact", "feasibility", "novelty"],
        "rationale": "simulated",
    }


@simulated.register("creative.diverge")
def _sim_diverge(req):  # type: ignore[no-untyped-def]
    c = req.sim_context
    topic = _topic(c["objective"])
    lenses = LENSES.get(c["approach"], [None])
    avoid = [a.lower() for a in c.get("avoid", [])]
    out = []
    for n, (title, summary) in enumerate(TEMPLATES * 2):
        t = title.format(T=topic.title(), t=topic)
        if any(_similar(t, a) for a in avoid) or len(out) >= c["count"]:
            continue
        out.append({"title": t, "summary": summary.format(T=topic.title(), t=topic), "lens": lenses[n % len(lenses)], "tags": []})
    out.append(
        {"title": f"{topic.title()} gamification", "summary": f"Add gamification to {topic}.", "lens": None, "tags": []}
    )  # exercised by the generic filter
    return {"ideas": out}


@simulated.register("creative.challenge")
def _sim_challenge(req):  # type: ignore[no-untyped-def]
    return {
        "assumptions": [
            {"assumption": "People want more content", "challenge": "Most drop out from lack of time, not lack of material."},
            {"assumption": "Price is the main barrier", "challenge": "Accountability and visible progress may matter more."},
        ]
    }


@simulated.register("creative.score")
def _sim_score(req):  # type: ignore[no-untyped-def]
    return {
        "scores": [
            {"index": n, "impact": 4 + _h(t + "i", 6), "feasibility": 3 + _h(t + "f", 7), "novelty": 3 + _h(t + "n", 7), "rationale": "simulated judgement"}
            for n, t in enumerate(req.sim_context["titles"])
        ]
    }


@simulated.register("creative.framework")
def _sim_framework(req):  # type: ignore[no-untyped-def]
    topic = _topic(req.sim_context["objective"])
    return {
        "sections": [
            {"lens": lens, "points": [f"{lens.split('—')[-1].strip()} view on {topic}: point A", f"{lens.split('—')[-1].strip()} view on {topic}: point B"]}
            for lens in req.sim_context["lenses"]
        ],
        "actions": [
            f"Validate the riskiest assumption about {topic} with five customer calls",
            f"Prototype the cheapest version of {topic} within two weeks",
            f"Define a kill metric for {topic} before launch",
        ],
    }


@simulated.register("creative.evaluate")
def _sim_evaluate(req):  # type: ignore[no-untyped-def]
    opts = re.findall(r"[\"“](.+?)[\"”]", req.sim_context["objective"]) or ["Option A", "Option B", "Option C"]
    return {
        "ranking": [{"option": o, "score": 4 + _h(o, 6), "strengths": [f"{o} is easy to explain"], "risks": [f"{o} may be easy to copy"]} for o in opts],
        "recommendation": f"Pursue {opts[0]} with a two-week validation test.",
    }


@simulated.register("creative.develop")
def _sim_develop(req):  # type: ignore[no-untyped-def]
    i = req.sim_context["idea"]
    return f"## {i['title']}\n\n**Problem.** …\n\n**Audience.** …\n\n**Solution.** {i['summary']}\n\n**Differentiation.** …\n\n**Risks.** Demand is unproven (speculative)."


@simulated.register("creative.brief")
def _sim_brief(req):  # type: ignore[no-untyped-def]
    i = req.sim_context["idea"]
    return f"# Creative brief — {i['title']}\n\n- Objective: test demand for {i['title']}\n- Audience: early adopters\n- Message: {i['summary']}\n- Success metric: sign-ups per 1,000 visitors"
