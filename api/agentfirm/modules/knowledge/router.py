"""Knowledge & Files: documents agents can retrieve from (keyword search; embeddings later).

Text and Markdown arrive as JSON; PDFs/text files as multipart uploads. Content is chunked
at ingestion; agents read it through the `knowledge.retrieve` / `docs.parse` tools, always
inside an `<untrusted>` wrapper.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.errors import NotFound, Unprocessable
from agentfirm.core.permissions import Perm
from agentfirm.modules.audit.service import record
from agentfirm.modules.projects.service import get_project
from agentfirm.runtime.tools.docs import chunk_text, pdf_text

from .models import KnowledgeChunk, KnowledgeDocument

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
MAX_UPLOAD = 15 * 1024 * 1024
MAX_CHARS = 2_000_000


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=MAX_CHARS)
    project_id: UUID | None = None


class DocumentOut(BaseModel):
    id: UUID
    title: str
    source: str
    mime: str | None
    chars: int
    chunks: int
    project_id: UUID | None
    created_at: datetime


async def _ingest(session: DbSession, principal: Principal, *, title: str, text: str, source: str, mime: str | None, project_id: UUID | None) -> DocumentOut:
    if project_id:
        await get_project(session, principal, project_id)
    text = text.replace("\x00", "").strip()
    if not text:
        raise Unprocessable("The document contains no extractable text.")
    doc = KnowledgeDocument(org_id=principal.org_id, project_id=project_id, title=title[:300], source=source, mime=mime, chars=len(text), created_by=principal.user_id)
    session.add(doc)
    await session.flush()
    chunks = chunk_text(text)
    session.add_all(KnowledgeChunk(org_id=principal.org_id, document_id=doc.id, ordinal=n, content=c) for n, c in enumerate(chunks))
    await session.flush()
    await record(session, action="knowledge.document_added", target_type="knowledge_document", target_id=doc.id, actor=principal, after={"title": doc.title, "chars": doc.chars})
    return DocumentOut(id=doc.id, title=doc.title, source=source, mime=mime, chars=doc.chars, chunks=len(chunks), project_id=project_id, created_at=doc.created_at)


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def add_document(body: DocumentIn, session: DbSession, principal: Principal = require(Perm.KNOWLEDGE_MANAGE)) -> DocumentOut:
    return await _ingest(session, principal, title=body.title, text=body.content, source="text", mime="text/markdown", project_id=body.project_id)


@router.post("/documents/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    session: DbSession,
    file: UploadFile = File(...),
    project_id: UUID | None = Form(default=None),
    principal: Principal = require(Perm.KNOWLEDGE_MANAGE),
) -> DocumentOut:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise Unprocessable("Files are limited to 15 MB.")
    name = (file.filename or "document")[:300]
    if data[:5] == b"%PDF-":
        text, mime = pdf_text(data), "application/pdf"
    else:
        try:
            text, mime = data.decode("utf-8"), "text/plain"
        except UnicodeDecodeError as exc:
            raise Unprocessable("Only PDF and UTF-8 text/Markdown files are supported for now.") from exc
    return await _ingest(session, principal, title=name, text=text[:MAX_CHARS], source="upload", mime=mime, project_id=project_id)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(session: DbSession, principal: Principal = require(Perm.WORKSPACE_READ)) -> list[DocumentOut]:
    counts = select(KnowledgeChunk.document_id, func.count().label("n")).where(KnowledgeChunk.org_id == principal.org_id).group_by(KnowledgeChunk.document_id).subquery()
    rows = (
        await session.execute(
            select(KnowledgeDocument, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.org_id == principal.org_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
    ).all()
    return [DocumentOut(id=d.id, title=d.title, source=d.source, mime=d.mime, chars=d.chars, chunks=n, project_id=d.project_id, created_at=d.created_at) for d, n in rows]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, session: DbSession, principal: Principal = require(Perm.KNOWLEDGE_MANAGE)) -> Response:
    doc = (await session.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.org_id == principal.org_id))).scalar_one_or_none()
    if doc is None:
        raise NotFound("Document not found.")
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id, KnowledgeChunk.org_id == principal.org_id))
    await session.delete(doc)
    await record(session, action="knowledge.document_deleted", target_type="knowledge_document", target_id=doc.id, actor=principal, before={"title": doc.title})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
