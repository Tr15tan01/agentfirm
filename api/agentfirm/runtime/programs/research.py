"""Personal Research & Knowledge agent program (manifest: agents/manifests/research.yaml).

Integrity rule enforced in code, not just in prompts: a claim can only be `verified` if
its excerpt is found (normalised) in a source collected during THIS execution, and
`sources.verify` re-confirms it before delivery. Everything else is downgraded.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agentfirm.agents.contracts import AgentResult, ArtifactRef, Citation, Claim, ErrorCode, HandoffRequest

from ..context import ExecutionContext, untrusted
from ..errors import StepError
from ..gateway import simulated
from ..tools.web import contains_excerpt

DEPTH = {"quick": (1, 3), "standard": (3, 6), "deep": (5, 12)}  # (queries, pages)
SYSTEM = (
    "You are AgentFirm's Research & Knowledge agent. Only use the sources provided. Never invent "
    "citations or facts. Separate verified facts from assumptions and estimates, and surface conflicts."
)


class Understanding(BaseModel):
    question: str
    decision: str = ""
    info_requirements: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    web_queries: list[str] = Field(default_factory=list)
    internal_queries: list[str] = Field(default_factory=list)


class SourceScore(BaseModel):
    source_id: str
    quality: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    recency: str = "unknown"
    keep: bool = True


class SourceScores(BaseModel):
    scores: list[SourceScore]


class Extracted(BaseModel):
    text: str
    source_id: str
    excerpt: str = Field(max_length=400)


class Extraction(BaseModel):
    claims: list[Extracted]


class Conflict(BaseModel):
    topic: str
    claim_indexes: list[int]
    explanation: str


class Conflicts(BaseModel):
    conflicts: list[Conflict]


class Rating(BaseModel):
    claim: str
    verdict: str = Field(pattern="^(supported|contradicted|unverifiable)$")
    source_id: str | None = None
    excerpt: str | None = None


class Ratings(BaseModel):
    ratings: list[Rating]


class ClaimList(BaseModel):
    claims: list[str]


def _depth(ctx: ExecutionContext) -> tuple[int, int]:
    return DEPTH.get(str(ctx.parameters.get("depth", "standard")), DEPTH["standard"])


def _sources(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [*d.get("web_sources", []), *d.get("internal_sources", [])]


def _source_block(sources: list[dict[str, Any]], limit: int = 6000) -> str:
    return "\n\n".join(f"[{s['id']}] {s['title']} ({s['url']})\n{untrusted(s['url'], s['text'], limit)}" for s in sources)


async def _search_with_retry(ctx: ExecutionContext, query: str) -> list[dict[str, str]]:
    for attempt in range(3):
        try:
            return (await ctx.tool("web.search", query=query, count=6)).get("results", [])
        except StepError as exc:
            if not exc.retriable or attempt == 2:
                await ctx.log("warn", f"Search failed for “{query[:80]}”: {exc.message} — continuing with reduced coverage")
                return []
    return []


# ── deep_research ────────────────────────────────────────────────────────────


async def understand(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    u = await ctx.structured(
        "understand",
        "classify",
        Understanding,
        system=SYSTEM + " Restate the question, the decision it supports and the information required.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"understanding": u.model_dump()}


async def plan(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    nq, _ = _depth(ctx)
    p = await ctx.structured(
        "plan",
        "reasoning",
        Plan,
        system=SYSTEM + f" Write up to {nq} web search queries and up to 3 internal knowledge queries.",
        user=str(d.get("understanding")),
        sim={"objective": ctx.objective, "n": nq},
    )
    return {"plan": {"web_queries": p.web_queries[:nq], "internal_queries": p.internal_queries[:3]}}


async def retrieve_web(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    _, max_pages = _depth(ctx)
    seen: dict[str, dict[str, str]] = {}
    for q in d.get("plan", {}).get("web_queries", []):
        for r in await _search_with_retry(ctx, q):
            if r.get("url") and r["url"] not in seen:
                seen[r["url"]] = r
    sources = []
    for url, r in list(seen.items())[:max_pages]:
        try:
            page = await ctx.tool("web.fetch", url=url)
        except StepError as exc:
            await ctx.log("warn", f"Skipped {url[:100]}: {exc.message}")
            continue
        sources.append(
            {
                "id": f"w{len(sources) + 1}",
                "url": page["url"],
                "title": page.get("title") or r.get("title") or url,
                "text": page["text"][:15_000],
                "origin": "web",
            }
        )
    return {"web_sources": sources}


async def retrieve_internal(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    queries = d.get("plan", {}).get("internal_queries") or [ctx.objective]
    out, seen = [], set()
    for q in queries:
        for c in (await ctx.tool("knowledge.retrieve", query=q, top_k=5)).get("chunks", []):
            if c["url"] not in seen:
                seen.add(c["url"])
                out.append({"id": f"k{len(out) + 1}", "url": c["url"], "title": c["title"], "text": c["content"], "origin": "workspace"})
    return {"internal_sources": out}


async def evaluate(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sources = _sources(d)
    if not sources:
        return {"kept_ids": []}
    sc = await ctx.structured(
        "evaluate_sources",
        "reasoning",
        SourceScores,
        system=SYSTEM + " Score each source's quality (primary > secondary), relevance and recency. keep=false for unreliable or irrelevant ones.",
        user=_source_block(sources, 1500),
        sim={"ids": [s["id"] for s in sources]},
    )
    kept = [s.source_id for s in sc.scores if s.keep and s.relevance >= 2] or [s["id"] for s in sources]
    return {"kept_ids": kept, "source_scores": [s.model_dump() for s in sc.scores]}


async def extract(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sources = [s for s in _sources(d) if s["id"] in set(d.get("kept_ids", []))]
    if not sources:
        return {"claims": []}
    ex = await ctx.structured(
        "extract",
        "long_context",
        Extraction,
        system=SYSTEM + " Extract factual claims relevant to the question. Each needs a source_id and a SHORT verbatim excerpt from that source.",
        user=f"Question: {ctx.objective}\n\n{_source_block(sources)}",
        sim={"sources": sources},
    )
    by_id = {s["id"]: s for s in sources}
    valid, rejected = [], 0
    for c in ex.claims:
        src = by_id.get(c.source_id)
        if src and c.excerpt and contains_excerpt(src["text"], c.excerpt):
            valid.append(c.model_dump())
        else:
            rejected += 1
    if rejected:
        await ctx.log("warn", f"Discarded {rejected} extracted claims whose excerpt was not found in the cited source")
    return {"claims": valid}


async def reconcile(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    claims = d.get("claims", [])
    if len(claims) < 2:
        return {"conflicts": []}
    cf = await ctx.structured(
        "reconcile",
        "reasoning",
        Conflicts,
        system=SYSTEM + " Identify claims that contradict each other (different numbers or conclusions on the same subject). Do not resolve by averaging.",
        user="\n".join(f"[{n}] {c['text']} ({c['source_id']})" for n, c in enumerate(claims)),
        sim={"claims": claims},
    )
    return {"conflicts": [c.model_dump() for c in cf.conflicts if all(0 <= i < len(claims) for i in c.claim_indexes)]}


async def synthesize(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    claims, conflicts = d.get("claims", []), d.get("conflicts", [])
    sources = {s["id"]: s for s in _sources(d)}
    if not claims:
        return {
            "report_md": f"## {ctx.objective}\n\nI could not find reliable sources for this question, so I'm not giving an answer or any citations. "
            "Try rephrasing, adding documents to Knowledge & Files, or allowing a broader search."
        }
    body = await ctx.text(
        "synthesize",
        "reasoning",
        system=SYSTEM + " Write the report: executive summary, findings with [source_id] markers, conflicting evidence, open questions.",
        user=f"Question: {ctx.objective}\nClaims: {claims}\nConflicts: {conflicts}",
        sim={"objective": ctx.objective, "claims": claims, "conflicts": conflicts, "sources": sources},
    )
    refs = "\n".join(f"- [{sid}] {s['title']} — {s['url']}" for sid, s in sources.items() if any(c["source_id"] == sid for c in claims))
    return {"report_md": f"{body}\n\n### Sources\n{refs}"}


async def verify(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sources = {s["id"]: s for s in _sources(d)}
    statuses: dict[int, bool] = {}
    for n, c in enumerate(d.get("claims", [])[:40]):
        src = sources.get(c["source_id"])
        if not src:
            statuses[n] = False
            continue
        try:
            statuses[n] = bool((await ctx.tool("sources.verify", url=src["url"], excerpt=c["excerpt"])).get("verified"))
        except StepError as exc:
            await ctx.log("warn", f"Could not re-verify {src['url'][:80]}: {exc.message}")
            statuses[n] = False
    failed = [n for n, ok in statuses.items() if not ok]
    if failed:
        await ctx.log("warn", f"{len(failed)} citations failed re-verification and were downgraded to assumptions")
    return {"verified_index": {str(k): v for k, v in statuses.items()}}


async def deliver(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    arts = []
    report = await ctx.tool("artifact.write", name="research_report.md", content=d.get("report_md", ""), deliverable="research_report")
    arts.append({"id": report["artifact_id"], "name": report["name"], "kind": "md"})
    pack = await ctx.tool(
        "artifact.write",
        name="evidence_pack.json",
        content={"question": ctx.objective, "claims": d.get("claims", []), "conflicts": d.get("conflicts", []), "verified": d.get("verified_index", {})},
        deliverable="evidence_pack",
    )
    arts.append({"id": pack["artifact_id"], "name": pack["name"], "kind": "json"})
    handoffs = []
    if re.search(r"\b(score|rank|prioriti[sz]e|segments?|cost model)\b", ctx.objective, re.I):
        h = await ctx.tool(
            "agents.delegate",
            to_agent="bi",
            objective=f"Score the opportunities from this research: {ctx.objective[:300]}",
            reason="Quantitative scoring belongs to the BI agent",
            blocking=False,
        )
        handoffs.append(h["handoff"])
    return {"artifacts": arts, "handoffs": handoffs}


# ── document_analysis ────────────────────────────────────────────────────────


async def doc_parse(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    ids = ctx.parameters.get("files") or []
    if not ids:
        raise StepError(ErrorCode.MISSING_CONTEXT, "Which document should I analyse? Add it to Knowledge & Files and reference it in the task.")
    docs = (await ctx.tool("docs.parse", document_ids=ids))["documents"]
    return {
        "internal_sources": [
            {"id": f"d{n + 1}", "url": f"kb://{x['document_id']}", "title": x["title"], "text": x["text"], "origin": "workspace"} for n, x in enumerate(docs)
        ],
        "kept_ids": [f"d{n + 1}" for n in range(len(docs))],
    }


async def doc_verify(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    return {"verified_index": {str(n): True for n in range(len(d.get("claims", [])))}}  # excerpts already checked against the parsed text in extract


async def doc_deliver(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    lines = "\n".join(f"- {c['text']} — “{c['excerpt']}” [{c['source_id']}]" for c in d.get("claims", []))
    md = f"## Document analysis\n\n{lines or 'No extractable statements matched the request.'}"
    art = await ctx.tool("artifact.write", name="executive_summary.md", content=md, deliverable="executive_summary")
    return {"report_md": md, "artifacts": [{"id": art["artifact_id"], "name": art["name"], "kind": "md"}]}


# ── fact_check ───────────────────────────────────────────────────────────────


async def fc_claims(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    cl = await ctx.structured(
        "fact_claims",
        "classify",
        ClaimList,
        system=SYSTEM + " List the individual checkable claims in the request.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"to_check": cl.claims[:8], "plan": {"web_queries": cl.claims[:3] or [ctx.objective], "internal_queries": [ctx.objective]}}


async def fc_search(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    web_part = await retrieve_web(ctx, d)
    internal = await retrieve_internal(ctx, d)
    return web_part | internal


async def fc_rate(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    sources = _sources(d)
    rt = await ctx.structured(
        "fact_rate",
        "reasoning",
        Ratings,
        system=SYSTEM + " Rate each claim supported / contradicted / unverifiable, citing a source_id and a verbatim excerpt when not unverifiable.",
        user=f"Claims: {d.get('to_check')}\n\n{_source_block(sources)}",
        sim={"claims": d.get("to_check", []), "sources": sources},
    )
    by_id = {s["id"]: s for s in sources}
    claims = []
    for r in rt.ratings:
        src = by_id.get(r.source_id or "")
        if r.verdict != "unverifiable" and src and r.excerpt and contains_excerpt(src["text"], r.excerpt):
            claims.append({"text": f"{r.claim} — {r.verdict}", "source_id": src["id"], "excerpt": r.excerpt})
        else:
            claims.append({"text": f"{r.claim} — unverifiable with the sources found", "source_id": "", "excerpt": ""})
    md = "\n".join(f"- {c['text']}" + (f" [{c['source_id']}]" if c["source_id"] else "") for c in claims)
    return {
        "claims": [c for c in claims if c["source_id"]],
        "unverifiable": [c for c in claims if not c["source_id"]],
        "report_md": f"## Fact check\n\n{md or 'No checkable claims found.'}",
    }


# ── Program ──────────────────────────────────────────────────────────────────


class ResearchProgram:
    key = "research"
    handlers = {
        "deep_research": {
            "understand": understand,
            "plan": plan,
            "retrieve_web": retrieve_web,
            "retrieve_internal": retrieve_internal,
            "evaluate": evaluate,
            "extract": extract,
            "reconcile": reconcile,
            "synthesize": synthesize,
            "verify": verify,
            "deliver": deliver,
        },
        "document_analysis": {"parse": doc_parse, "extract": extract, "verify": doc_verify, "deliver": doc_deliver},
        "fact_check": {"claims": fc_claims, "search": fc_search, "rate": fc_rate, "verify": verify},
    }

    def approval_preview(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> str | None:
        return None

    def finalize(self, ctx: ExecutionContext, data: dict[str, Any]) -> AgentResult:
        sources = {s["id"]: s for s in _sources(data)}
        verified_index = data.get("verified_index", {})
        claims: list[Claim] = []
        for n, c in enumerate(data.get("claims", [])):
            src = sources.get(c["source_id"])
            if src and verified_index.get(str(n), False):
                claims.append(
                    Claim(
                        text=c["text"],
                        status="verified",
                        citations=[Citation(source_id=src["id"], title=src["title"][:200], url=src["url"], excerpt=c["excerpt"][:300])],
                    )
                )
            else:
                claims.append(Claim(text=c["text"], status="assumption"))
        for c in data.get("unverifiable", []):
            claims.append(Claim(text=c["text"], status="assumption"))
        for cf in data.get("conflicts", []):
            claims.append(Claim(text=f"Sources disagree on {cf['topic']}: {cf['explanation']}", status="assumption"))
        summary = data.get("report_md") or "No report produced."
        if data.get("_partial_reason"):
            summary += f"\n\n> **Partial result:** {data['_partial_reason']}"
        artifacts = [ArtifactRef(id=a["id"], name=a["name"], kind=a["kind"]) for a in data.get("artifacts", [])]
        handoffs = [
            HandoffRequest(to_agent=h["to_agent"], objective=h["objective"], reason=h["reason"], blocking=h["blocking"]) for h in data.get("handoffs", [])
        ]
        return AgentResult(execution_id=ctx.execution_id, status="completed", summary=summary, claims=claims, artifacts=artifacts, handoffs=handoffs)


# ── Simulator builders (offline/dev only) ────────────────────────────────────

SENT = re.compile(r"(?<=[.!?])\s+")


@simulated.register("research.understand")
def _sim_understand(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    return {"question": o, "decision": "Inform the next step", "info_requirements": ["Key facts", "Conflicting evidence", "Open questions"]}


@simulated.register("research.plan")
def _sim_plan(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    return {"web_queries": [o, f"{o} 2026", f"{o} statistics"][: req.sim_context["n"]], "internal_queries": [o]}


@simulated.register("research.evaluate_sources")
def _sim_eval(req):  # type: ignore[no-untyped-def]
    return {"scores": [{"source_id": i, "quality": 4, "relevance": 4, "recency": "recent", "keep": True} for i in req.sim_context["ids"]]}


@simulated.register("research.extract")
def _sim_extract(req):  # type: ignore[no-untyped-def]
    claims = []
    for s in req.sim_context["sources"]:
        for sent in [x.strip() for x in SENT.split(s["text"]) if len(x.strip()) > 40][:2]:
            if "ignore previous instructions" in sent.lower():
                continue
            claims.append({"text": sent, "source_id": s["id"], "excerpt": sent[:300]})
    return {"claims": claims}


NUM = re.compile(r"\d[\d.,]*\s*(?:%|million|billion|m\b|bn\b|€|\$)?", re.I)


@simulated.register("research.reconcile")
def _sim_reconcile(req):  # type: ignore[no-untyped-def]
    claims = req.sim_context["claims"]
    out = []
    for i, a in enumerate(claims):
        for j in range(i + 1, len(claims)):
            b = claims[j]
            if a["source_id"] != b["source_id"] and len(simulated.tokens(a["text"]) & simulated.tokens(b["text"])) >= 3:
                na, nb = NUM.findall(a["text"]), NUM.findall(b["text"])
                if na and nb and na[0] != nb[0]:
                    out.append(
                        {
                            "topic": "a reported figure",
                            "claim_indexes": [i, j],
                            "explanation": f"[{a['source_id']}] says {na[0].strip()} while [{b['source_id']}] says {nb[0].strip()}.",
                        }
                    )
    return {"conflicts": out}


@simulated.register("research.synthesize")
def _sim_synth(req):  # type: ignore[no-untyped-def]
    c = req.sim_context
    findings = "\n".join(f"- {x['text']} [{x['source_id']}]" for x in c["claims"][:12])
    conflicts = "\n".join(f"- {x['explanation']}" for x in c["conflicts"]) or "- None found."
    return f"## {c['objective']}\n\n**Executive summary.** Based on {len(c['sources'])} sources (simulated synthesis).\n\n### Findings\n{findings}\n\n### Conflicting evidence\n{conflicts}\n\n### Verified vs assumed\nClaims marked verified carry citations; everything else is an assumption."


@simulated.register("research.fact_claims")
def _sim_fact_claims(req):  # type: ignore[no-untyped-def]
    return {"claims": [req.sim_context["objective"]]}


@simulated.register("research.fact_rate")
def _sim_fact_rate(req):  # type: ignore[no-untyped-def]
    c = req.sim_context
    out = []
    for claim in c["claims"]:
        best = None
        for s in c["sources"]:
            for sent in [x.strip() for x in SENT.split(s["text"]) if len(x.strip()) > 30]:
                if len(simulated.tokens(claim) & simulated.tokens(sent)) >= 2:
                    best = (s["id"], sent[:300])
                    break
            if best:
                break
        out.append(
            {"claim": claim, "verdict": "supported" if best else "unverifiable", "source_id": best[0] if best else None, "excerpt": best[1] if best else None}
        )
    return {"ratings": out}
