from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.deps import Principal

from .models import AuditLog


async def record(
    session: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: str | UUID | None,
    actor: Principal | None = None,
    actor_user_id: UUID | None = None,
    org_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    platform: bool = False,
) -> None:
    """Append an audit entry in the SAME transaction as the change it describes."""
    resolved_org = None if platform else (org_id or (actor.org_id if actor else None))
    if resolved_org is None:
        await session.execute(
            text("SELECT log_platform_audit(:a, :tt, :tid, :actor, :ip, CAST(:after AS jsonb))"),
            {
                "a": action,
                "tt": target_type,
                "tid": str(target_id) if target_id is not None else None,
                "actor": actor_user_id or (actor.user_id if actor else None),
                "ip": ip or (actor.ip if actor else None),
                "after": json.dumps(after) if after is not None else None,
            },
        )
        return
    session.add(
        AuditLog(
            org_id=resolved_org,
            actor_user_id=actor_user_id or (actor.user_id if actor else None),
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            before=before,
            after=after,
            ip=ip or (actor.ip if actor else None),
        )
    )


async def list_entries(session: AsyncSession, org_id: UUID, *, limit: int = 100, before_id: int | None = None) -> list[AuditLog]:
    q = select(AuditLog).where(AuditLog.org_id == org_id).order_by(AuditLog.id.desc()).limit(limit)
    if before_id:
        q = q.where(AuditLog.id < before_id)
    return list((await session.execute(q)).scalars())
