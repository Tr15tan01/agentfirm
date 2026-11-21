"""Request-scoped dependencies: database session, authenticated principal, permission checks.

The token says who the caller claims to be; the database decides what they may do.
Membership and role are re-loaded on every request, and the auth session must still
be active, so revocations and role changes take effect immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import DbContext, apply_context, get_session
from .errors import Forbidden, Unauthorized
from .permissions import ROLE_PERMISSIONS, Perm, Role
from .security import decode_access_token

DbSession = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    session_id: UUID
    email: str
    name: str
    is_super_admin: bool
    org_id: UUID | None = None
    membership_id: UUID | None = None
    role: Role | None = None
    permissions: frozenset[Perm] = field(default_factory=frozenset)
    ip: str | None = None

    def can(self, perm: Perm) -> bool:
        return perm in self.permissions


def client_ip(request: Request) -> str | None:
    # The BFF forwards the browser IP; trust it only from the internal network in deployment.
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)


async def get_principal(request: Request, session: DbSession) -> Principal:
    from agentfirm.modules.identity.models import AuthSession, Membership, User

    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token.")
    claims = decode_access_token(header[7:].strip())

    await apply_context(session, DbContext(org_id=claims.org_id, user_id=claims.user_id))

    auth = await session.get(AuthSession, claims.session_id)
    now = datetime.now(UTC)
    if auth is None or auth.user_id != claims.user_id or auth.revoked_at is not None or auth.expires_at <= now:
        raise Unauthorized("Session is no longer active.", code="session_revoked")

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is disabled.")

    role: Role | None = None
    membership_id: UUID | None = None
    if claims.org_id is not None:
        m = (
            await session.execute(select(Membership).where(Membership.org_id == claims.org_id, Membership.user_id == user.id, Membership.status == "active"))
        ).scalar_one_or_none()
        if m is not None:
            role, membership_id = Role(m.role), m.id

    return Principal(
        user_id=user.id,
        session_id=auth.id,
        email=user.email,
        name=user.name,
        is_super_admin=user.is_super_admin,
        org_id=claims.org_id if role else None,
        membership_id=membership_id,
        role=role,
        permissions=ROLE_PERMISSIONS[role] if role else frozenset(),
        ip=client_ip(request),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(perm: Perm):
    """Dependency factory: caller must be an active member of the token's org with `perm`."""

    async def _dep(principal: CurrentPrincipal) -> Principal:
        if principal.org_id is None or principal.role is None:
            raise Forbidden("You are not a member of this workspace.", code="no_membership")
        if not principal.can(perm):
            raise Forbidden(f"Missing permission: {perm.value}", code="missing_permission")
        return principal

    return Depends(_dep)


async def _super_admin(principal: CurrentPrincipal, session: DbSession) -> Principal:
    if not principal.is_super_admin:
        raise Forbidden("Platform administrators only.", code="not_super_admin")
    # Elevate RLS context for this transaction only (cross-org reads for platform administration).
    await apply_context(session, DbContext(org_id=principal.org_id, user_id=principal.user_id, platform_admin=True))
    return principal


SuperAdmin = Annotated[Principal, Depends(_super_admin)]
