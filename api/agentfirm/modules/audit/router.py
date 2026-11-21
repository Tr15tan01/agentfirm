from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from agentfirm.core.deps import DbSession, Principal, require
from agentfirm.core.permissions import Perm

from . import service

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_user_id: UUID | None
    action: str
    target_type: str
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    created_at: datetime


@router.get("", response_model=list[AuditOut])
async def list_audit(
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None, ge=1),
    principal: Principal = require(Perm.AUDIT_READ),
):  # type: ignore[no-untyped-def]
    assert principal.org_id is not None
    return await service.list_entries(session, principal.org_id, limit=limit, before_id=before_id)
