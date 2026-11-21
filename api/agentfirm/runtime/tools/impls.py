"""Tool implementations available in Phase 4a (used by the Research and Creative agents).
Every database access runs inside the execution's organisation context (RLS applies)."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select, text

from agentfirm.agents.contracts import ErrorCode
from agentfirm.core.db import DbContext, apply_context, sessionmaker
from agentfirm.modules.ideas.models import Idea
from agentfirm.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from agentfirm.modules.memory.models import Memory
from agentfirm.modules.tasks.models import Artifact

from ..artifacts import get_store, object_key
from ..errors import StepError
from . import web

if TYPE_CHECKING:
    from ..context import ExecutionContext

Impl = Callable[["ExecutionContext", dict[str, Any]], Awaitable[dict[str, Any]]]
IMPLS: dict[str, Impl] = {}
#: Idempotency key of the tool call being executed (sent to connectors as Idempotency-Key).
CURRENT_CALL: ContextVar[str] = ContextVar("af_tool_call", default="")


def tool(key: str) -> Callable[[Impl], Impl]:
    def deco(fn: Impl) -> Impl:
        IMPLS[key] = fn
        return fn

    return deco


def _session(ctx: ExecutionContext):  # type: ignore[no-untyped-def]
    class _S:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            self.cm = sessionmaker()()
            self.s = await self.cm.__aenter__()
            self.tx = self.s.begin()
            await self.tx.__aenter__()
            await apply_context(self.s, DbContext(org_id=ctx.org_id))
            return self.s

        async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
            await self.tx.__aexit__(*exc)
            await self.cm.__aexit__(*exc)

    return _S()


# ── Idea board ───────────────────────────────────────────────────────────────


@tool("ideas.board_read")
async def ideas_read(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    async with _session(ctx) as s:
        q = select(Idea).where(Idea.org_id == ctx.org_id, Idea.board_column != "rejected").order_by(Idea.created_at.desc()).limit(int(args.get("limit", 100)))
        if ctx.project_id:
            q = q.where(Idea.project_id == ctx.project_id)
        rows = list((await s.execute(q)).scalars())
    return {"ideas": [{"id": str(i.id), "title": i.title, "summary": i.summary, "column": i.board_column, "scores": i.scores} for i in rows]}


@tool("ideas.board_write")
async def ideas_write(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    created: list[str] = []
    async with _session(ctx) as s:
        for item in args.get("ideas", [])[:60]:
            idea = Idea(
                org_id=ctx.org_id,
                project_id=ctx.project_id,
                execution_id=ctx.execution_id,
                title=str(item["title"])[:240],
                summary=str(item["summary"])[:4000],
                approach=str(item.get("approach", "divergent"))[:32],
                lens=(item.get("lens") or None),
                tags=[str(t)[:48] for t in item.get("tags", [])][:8],
                scores=item.get("scores") or {},
                board_column=item.get("column", "new"),
                created_by=ctx.requested_by,
            )
            s.add(idea)
            await s.flush()
            created.append(str(idea.id))
    return {"created": created}


# ── Memory service ───────────────────────────────────────────────────────────


@tool("memory.read")
async def memory_read(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    keys = [str(k) for k in args.get("keys", [])][:20]
    async with _session(ctx) as s:
        rows = (await s.execute(select(Memory).where(Memory.org_id == ctx.org_id, Memory.key.in_(keys)))).scalars()
        found: dict[str, str] = {}
        for m in rows:  # project-scoped memory overrides org-wide memory
            if m.project_id is None and m.key in found:
                continue
            if m.project_id in (None, ctx.project_id):
                found[m.key] = m.value
    return {"memories": found}


@tool("memory.write")
async def memory_write(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    # Proposals only: the user confirms memory changes (Agent Interface §5).
    return {"proposed": {"key": str(args.get("key"))[:64], "value": str(args.get("value"))[:4000]}, "requires_confirmation": True}


# ── Artifacts ────────────────────────────────────────────────────────────────

CONTENT_TYPES = {
    "md": "text/markdown",
    "json": "application/json",
    "csv": "text/csv",
    "txt": "text/plain",
    "svg": "image/svg+xml",
    "diff": "text/x-diff",
    "patch": "text/x-diff",
}


@tool("artifact.write")
async def artifact_write(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args["name"])
    kind = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
    content = args["content"]
    data = (json.dumps(content, indent=2, ensure_ascii=False) if not isinstance(content, str) else content).encode()
    key = object_key(ctx.org_id, ctx.execution_id, name)
    await get_store().put(key, data, CONTENT_TYPES.get(kind, "application/octet-stream"))
    async with _session(ctx) as s:
        art = Artifact(org_id=ctx.org_id, execution_id=ctx.execution_id, name=name, kind=kind, size_bytes=len(data), storage_key=key)
        s.add(art)
        await s.flush()
        art_id = art.id
    await ctx.emit("artifact.created", {"artifact": {"id": str(art_id), "name": name, "kind": kind}, "deliverable": args.get("deliverable")})
    return {"artifact_id": str(art_id), "name": name, "size_bytes": len(data)}


# ── Delegation (recorded now; the orchestrator spawns subtasks in Phase 5) ───


@tool("agents.delegate")
async def delegate(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("to_agent"))
    if target not in ctx.manifest.collaboration.can_delegate_to:
        raise StepError(ErrorCode.POLICY_VIOLATION, f"{ctx.manifest.key} may not delegate to {target}")
    handoff = {
        "to_agent": target,
        "objective": str(args.get("objective", ""))[:2000],
        "reason": str(args.get("reason", ""))[:500],
        "blocking": bool(args.get("blocking", False)),
    }
    ctx.handoffs.append(handoff)
    return {"status": "recorded", "handoff": handoff, "note": "Subtask execution is coordinated by the orchestrator (Phase 5)."}


# ── Web & sources ────────────────────────────────────────────────────────────


@tool("web.search")
async def web_search(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"results": await web.search(str(args["query"])[:400], count=int(args.get("count", 6)))}


@tool("web.fetch")
async def web_fetch(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    page = await web.fetch(str(args["url"]))
    page["text"] = page["text"][:60_000]
    return page


@tool("sources.verify")
async def sources_verify(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    url, excerpt = str(args["url"]), str(args["excerpt"])
    if url.startswith("kb://"):
        doc_id = UUID(url.removeprefix("kb://").split("#", 1)[0])
        async with _session(ctx) as s:
            texts = (await s.execute(select(KnowledgeChunk.content).where(KnowledgeChunk.org_id == ctx.org_id, KnowledgeChunk.document_id == doc_id))).scalars()
            body = " ".join(texts)
    else:
        body = (await web.fetch(url))["text"]
    return {"url": url, "verified": web.contains_excerpt(body, excerpt)}


# ── Knowledge ────────────────────────────────────────────────────────────────


STOPWORDS = {"the", "and", "for", "our", "with", "this", "that", "what", "how", "from", "into", "about", "your", "you", "are", "was", "were",
             "did", "does", "say", "send", "tell", "give", "please", "can", "could", "would", "should", "need", "want", "make", "write", "draft"}


@tool("knowledge.retrieve")
async def knowledge_retrieve(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args["query"])[:400]
    k = min(int(args.get("top_k", 6)), 20)
    # Rank by ANY overlap, not "every word must appear": requests are sentences ("send the
    # meeting notes to the team"), documents aren't. Terms are plain alphanumerics, so no
    # tsquery syntax from the request can reach the parser.
    terms = list(dict.fromkeys(w for w in re.findall(r"[^\W_]{3,}", query.lower()) if w not in STOPWORDS))[:24]
    if not terms:
        return {"chunks": []}
    async with _session(ctx) as s:
        tsq = func.to_tsquery("simple", " | ".join(terms))
        q = (
            select(KnowledgeChunk, KnowledgeDocument.title, func.ts_rank(KnowledgeChunk.tsv, tsq).label("rank"))
            .join(KnowledgeDocument, (KnowledgeDocument.id == KnowledgeChunk.document_id) & (KnowledgeDocument.org_id == KnowledgeChunk.org_id))
            .where(KnowledgeChunk.org_id == ctx.org_id, KnowledgeChunk.tsv.op("@@")(tsq))
            .order_by(text("rank DESC"))
            .limit(k)
        )
        if ctx.project_id and ctx.manifest.knowledge.scope == "project":
            q = q.where((KnowledgeDocument.project_id == ctx.project_id) | (KnowledgeDocument.project_id.is_(None)))
        rows = (await s.execute(q)).all()
    return {
        "chunks": [
            {"document_id": str(c.document_id), "title": title, "locator": c.locator, "content": c.content, "url": f"kb://{c.document_id}#{c.ordinal}"}
            for c, title, _ in rows
        ]
    }


@tool("docs.parse")
async def docs_parse(ctx: ExecutionContext, args: dict[str, Any]) -> dict[str, Any]:
    out = []
    async with _session(ctx) as s:
        for raw in args.get("document_ids", [])[:10]:
            doc = (
                await s.execute(select(KnowledgeDocument).where(KnowledgeDocument.org_id == ctx.org_id, KnowledgeDocument.id == UUID(str(raw))))
            ).scalar_one_or_none()
            if doc is None:
                raise StepError(ErrorCode.MISSING_CONTEXT, f"Document {raw} not found")
            chunks = (await s.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.ordinal))).scalars()
            out.append({"document_id": str(doc.id), "title": doc.title, "text": "\n".join(c.content for c in chunks)[:200_000]})
    return {"documents": out}
