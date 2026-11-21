from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Computed, ForeignKey, ForeignKeyConstraint, Identity, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk


class KnowledgeDocument(Base):
    __tablename__ = tenant_table("knowledge_documents")
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_knowledge_documents_org_id_id"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="SET NULL (project_id)"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(32))
    mime: Mapped[str | None] = mapped_column(String(100))
    chars: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class KnowledgeChunk(Base):
    __tablename__ = tenant_table("knowledge_chunks")
    __table_args__ = (ForeignKeyConstraint(["org_id", "document_id"], ["knowledge_documents.org_id", "knowledge_documents.id"], ondelete="CASCADE"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[UUID] = mapped_column(index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True))
