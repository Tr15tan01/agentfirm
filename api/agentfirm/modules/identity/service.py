"""Sign-in, sessions, organisations, memberships and invitations (Python-only auth)."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core import ratelimit
from agentfirm.core.config import get_settings
from agentfirm.core.db import DbContext, apply_context, independent_tx
from agentfirm.core.deps import Principal
from agentfirm.core.errors import Conflict, Forbidden, NotFound, Unauthorized, Unprocessable
from agentfirm.core.permissions import ROLE_PERMISSIONS, ROLE_RANK, Perm, Role
from agentfirm.core.security import (
    hash_password_async,
    hash_token,
    issue_access_token,
    needs_rehash,
    new_refresh_secret,
    tokens_equal,
    validate_password_policy,
    verify_password_async,
)
from agentfirm.modules.audit.service import record

from .models import AuthSession, Invitation, Membership, Organization, User
from .schemas import AccessToken, InvitationOut, MemberOut, MembershipOrgOut, OrgOut, TokenPair, UserOut

GENERIC_LOGIN_ERROR = "Email or password is incorrect."


def _now() -> datetime:
    return datetime.now(UTC)


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "workspace"
    return s


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = _slugify(name)
    # Slugs are globally unique but RLS hides other orgs, so ask the narrow DB function.
    for i in range(50):
        candidate = base if i == 0 else f"{base}-{secrets.token_hex(2)}"
        exists = await session.scalar(text("SELECT org_slug_taken(:s)"), {"s": candidate})
        if not exists:
            return candidate
    raise Conflict("Could not allocate a workspace URL.")


async def _user_by_email(session: AsyncSession, email: str) -> User | None:
    return (await session.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()


async def _first_membership(session: AsyncSession, user_id: UUID, preferred: UUID | None) -> Membership | None:
    q = select(Membership).where(Membership.user_id == user_id, Membership.status == "active")
    rows = list((await session.execute(q.order_by(Membership.created_at))).scalars())
    if preferred:
        for m in rows:
            if m.org_id == preferred:
                return m
    return rows[0] if rows else None


async def _start_session(session: AsyncSession, user: User, org: Organization | None, role: Role | None, *, ip: str | None, ua: str | None) -> TokenPair:
    s = get_settings()
    secret = new_refresh_secret()
    auth = AuthSession(
        id=uuid4(),
        user_id=user.id,
        org_id=org.id if org else None,
        refresh_hash=hash_token(secret),
        ip=ip,
        user_agent=(ua or "")[:400] or None,
        expires_at=_now() + timedelta(seconds=s.refresh_token_ttl_seconds),
    )
    session.add(auth)
    await session.flush()
    access, exp = issue_access_token(user_id=user.id, org_id=org.id if org else None, session_id=auth.id)
    return TokenPair(
        access_token=access,
        access_expires_at=exp,
        refresh_token=f"{auth.id}.{secret}",
        refresh_expires_at=auth.expires_at,
        user=UserOut.model_validate(user),
        organization=OrgOut.model_validate(org) if org else None,
        role=role,
    )


# ── Registration & sign-in ───────────────────────────────────────────────────


async def register(session: AsyncSession, *, email: str, name: str, password: str, org_name: str, ip: str | None, ua: str | None) -> TokenPair:
    await ratelimit.hit(f"register:{ip}", limit=get_settings().login_rate_per_minute)
    validate_password_policy(password, email)
    if await _user_by_email(session, email):
        # Don't reveal account existence beyond what sign-up inherently does; keep message neutral.
        raise Conflict("An account with this email already exists. Sign in instead.", code="email_taken")

    user = User(id=uuid4(), email=email.strip(), name=name.strip(), password_hash=await hash_password_async(password))
    session.add(user)
    org_id = uuid4()
    await apply_context(session, DbContext(org_id=org_id, user_id=user.id))
    # Check-then-insert can race when two workspaces with the same name sign up at once (found by
    # the Phase 7 load test): insert under a savepoint and retry with a fresh suffix on conflict.
    org = None
    for _attempt in range(5):
        candidate = Organization(id=org_id, name=org_name.strip(), slug=await _unique_slug(session, org_name))
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            org = candidate
            break
        except IntegrityError as exc:
            if "uq_organizations_slug" not in str(exc.orig):
                raise
            if candidate in session:  # the savepoint rollback usually detached it already
                session.expunge(candidate)
    if org is None:
        raise Conflict("Could not allocate a workspace URL. Please try again.")
    session.add(Membership(org_id=org.id, user_id=user.id, role=Role.OWNER.value))
    await session.flush()
    from agentfirm.modules.billing.accounts import ensure_account

    await ensure_account(session, org.id)  # free plan + monthly allowance
    await record(session, action="user.registered", target_type="user", target_id=user.id, actor_user_id=user.id, org_id=org.id, ip=ip)
    await record(
        session,
        action="organization.created",
        target_type="organization",
        target_id=org.id,
        actor_user_id=user.id,
        org_id=org.id,
        ip=ip,
        after={"name": org.name, "slug": org.slug},
    )
    return await _start_session(session, user, org, Role.OWNER, ip=ip, ua=ua)


async def login(session: AsyncSession, *, email: str, password: str, preferred_org: UUID | None, ip: str | None, ua: str | None) -> TokenPair:
    s = get_settings()
    await ratelimit.hit(f"login-ip:{ip}", limit=s.login_rate_per_minute * 3)
    await ratelimit.hit(f"login-email:{email.lower()}", limit=s.login_rate_per_minute)

    user = await _user_by_email(session, email)
    if user is not None and user.locked_until and user.locked_until > _now():
        await verify_password_async(password, None)  # constant-ish timing
        raise Unauthorized("Too many failed attempts. Try again later or reset your password.", code="account_locked")

    if not await verify_password_async(password, user.password_hash if user else None) or user is None or not user.is_active:
        if user is not None:
            await _record_failed_login(user.id, ip)
        raise Unauthorized(GENERIC_LOGIN_ERROR, code="invalid_credentials")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = _now()
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = await hash_password_async(password)

    await apply_context(session, DbContext(user_id=user.id))
    m = await _first_membership(session, user.id, preferred_org)
    org: Organization | None = None
    if m is not None:
        await apply_context(session, DbContext(org_id=m.org_id, user_id=user.id))
        org = await session.get(Organization, m.org_id)
    pair = await _start_session(session, user, org, Role(m.role) if m else None, ip=ip, ua=ua)
    await record(
        session, action="auth.login", target_type="user", target_id=user.id, actor_user_id=user.id, org_id=org.id if org else None, ip=ip, platform=org is None
    )
    return pair


async def _record_failed_login(user_id: UUID, ip: str | None) -> None:
    """Persist the failure counter outside the request transaction (which rolls back on 401)."""
    s = get_settings()
    async with independent_tx() as tx:
        locked = await tx.scalar(
            text(
                "UPDATE users SET "
                " locked_until = CASE WHEN failed_logins + 1 >= :max THEN now() + make_interval(secs => :lock) ELSE locked_until END,"
                " failed_logins = CASE WHEN failed_logins + 1 >= :max THEN 0 ELSE failed_logins + 1 END "
                "WHERE id = :id RETURNING locked_until IS NOT NULL AND locked_until > now()"
            ),
            {"max": s.login_max_failures, "lock": s.login_lock_seconds, "id": user_id},
        )
        if locked:
            await record(tx, action="user.locked", target_type="user", target_id=user_id, actor_user_id=user_id, ip=ip, platform=True)


def _parse_refresh(token: str) -> tuple[UUID, str]:
    try:
        sid, secret = token.split(".", 1)
        return UUID(sid), secret
    except ValueError as exc:
        raise Unauthorized("Invalid refresh token.", code="invalid_token") from exc


async def _revoke_for_reuse(auth_id: UUID, user_id: UUID, ip: str | None) -> None:
    """Replay of a rotated refresh secret: assume theft and kill the session. Committed
    independently because the request transaction rolls back when we raise."""
    async with independent_tx() as tx:
        await tx.execute(
            text("UPDATE auth_sessions SET revoked_at = now(), revoke_reason = 'refresh_reuse_detected' WHERE id = :id AND revoked_at IS NULL"),
            {"id": auth_id},
        )
        await record(tx, action="auth.refresh_reuse_detected", target_type="session", target_id=auth_id, actor_user_id=user_id, ip=ip, platform=True)


async def refresh(session: AsyncSession, *, refresh_token: str, ip: str | None) -> TokenPair:
    sid, secret = _parse_refresh(refresh_token)
    auth = await session.get(AuthSession, sid)
    if auth is None or auth.revoked_at is not None or auth.expires_at <= _now():
        raise Unauthorized("Session expired. Please sign in again.", code="session_revoked")
    presented = hash_token(secret)
    if not tokens_equal(auth.refresh_hash, presented):
        await _revoke_for_reuse(auth.id, auth.user_id, ip)
        raise Unauthorized("Session revoked for your security. Please sign in again.", code="session_revoked")

    user = await session.get(User, auth.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is disabled.")

    # Compare-and-swap rotation: exactly one concurrent refresh can win; the loser looks like reuse.
    new_secret = new_refresh_secret()
    rotated = await session.scalar(
        text("UPDATE auth_sessions SET refresh_hash = :new, last_used_at = now() WHERE id = :id AND refresh_hash = :old AND revoked_at IS NULL RETURNING id"),
        {"new": hash_token(new_secret), "id": auth.id, "old": presented},
    )
    if rotated is None:
        raise Unauthorized("Session was refreshed elsewhere. Please retry.", code="refresh_conflict")
    await session.refresh(auth)

    await apply_context(session, DbContext(org_id=auth.org_id, user_id=user.id))
    org, role = None, None
    if auth.org_id:
        m = (
            await session.execute(select(Membership).where(Membership.org_id == auth.org_id, Membership.user_id == user.id, Membership.status == "active"))
        ).scalar_one_or_none()
        if m:
            org, role = await session.get(Organization, auth.org_id), Role(m.role)
        else:
            auth.org_id = None
    access, exp = issue_access_token(user_id=user.id, org_id=org.id if org else None, session_id=auth.id)
    await session.flush()
    return TokenPair(
        access_token=access,
        access_expires_at=exp,
        refresh_token=f"{auth.id}.{new_secret}",
        refresh_expires_at=auth.expires_at,
        user=UserOut.model_validate(user),
        organization=OrgOut.model_validate(org) if org else None,
        role=role,
    )


async def logout(session: AsyncSession, principal: Principal) -> None:
    auth = await session.get(AuthSession, principal.session_id)
    if auth and auth.revoked_at is None:
        auth.revoked_at, auth.revoke_reason = _now(), "logout"
    await record(session, action="auth.logout", target_type="session", target_id=principal.session_id, actor=principal, platform=principal.org_id is None)


async def list_sessions(session: AsyncSession, principal: Principal) -> list[AuthSession]:
    q = select(AuthSession).where(AuthSession.user_id == principal.user_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > _now())
    return list((await session.execute(q.order_by(AuthSession.last_used_at.desc()))).scalars())


async def revoke_session(session: AsyncSession, principal: Principal, session_id: UUID) -> None:
    auth = await session.get(AuthSession, session_id)
    if auth is None or auth.user_id != principal.user_id:
        raise NotFound("Session not found.")
    auth.revoked_at, auth.revoke_reason = _now(), "user_revoked"
    await record(session, action="auth.session_revoked", target_type="session", target_id=session_id, actor=principal, platform=principal.org_id is None)


async def switch_org(session: AsyncSession, principal: Principal, org_id: UUID) -> AccessToken:
    await apply_context(session, DbContext(org_id=org_id, user_id=principal.user_id))
    m = (
        await session.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == principal.user_id, Membership.status == "active"))
    ).scalar_one_or_none()
    if m is None:
        raise NotFound("Workspace not found.")
    auth = await session.get(AuthSession, principal.session_id)
    assert auth is not None
    auth.org_id = org_id
    org = await session.get(Organization, org_id)
    access, exp = issue_access_token(user_id=principal.user_id, org_id=org_id, session_id=auth.id)
    return AccessToken(access_token=access, access_expires_at=exp, organization=OrgOut.model_validate(org), role=Role(m.role))


async def my_memberships(session: AsyncSession, principal: Principal) -> list[MembershipOrgOut]:
    rows = (
        await session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.org_id)
            .where(Membership.user_id == principal.user_id, Membership.status == "active")
            .order_by(Organization.name)
        )
    ).all()
    return [MembershipOrgOut(organization=OrgOut.model_validate(o), role=Role(m.role)) for m, o in rows]


# ── Members & invitations ────────────────────────────────────────────────────


def _assert_can_assign(principal: Principal, target_role: Role, current_role: Role | None = None) -> None:
    touches_owner = target_role == Role.OWNER or current_role == Role.OWNER
    if touches_owner and not principal.can(Perm.MEMBERS_MANAGE_OWNERS):
        raise Forbidden("Only owners can grant or change the owner role.", code="owner_only")


async def list_members(session: AsyncSession, principal: Principal) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.org_id == principal.org_id).order_by(Membership.created_at)
        )
    ).all()
    return [MemberOut(id=m.id, user_id=u.id, name=u.name, email=u.email, role=Role(m.role), status=m.status, joined_at=m.created_at) for m, u in rows]


async def _get_membership(session: AsyncSession, principal: Principal, membership_id: UUID) -> Membership:
    m = (await session.execute(select(Membership).where(Membership.id == membership_id, Membership.org_id == principal.org_id))).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found.")
    return m


async def _owner_count(session: AsyncSession, org_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Membership).where(Membership.org_id == org_id, Membership.role == Role.OWNER.value, Membership.status == "active")
        )
        or 0
    )


async def change_role(session: AsyncSession, principal: Principal, membership_id: UUID, role: Role) -> MemberOut:
    m = await _get_membership(session, principal, membership_id)
    current = Role(m.role)
    _assert_can_assign(principal, role, current)
    if current == Role.OWNER and role != Role.OWNER and await _owner_count(session, m.org_id) <= 1:
        raise Conflict("A workspace must keep at least one owner.", code="last_owner")
    m.role = role.value
    await record(
        session,
        action="member.role_changed",
        target_type="membership",
        target_id=m.id,
        actor=principal,
        before={"role": current.value},
        after={"role": role.value},
    )
    await session.flush()
    user = await session.get(User, m.user_id)
    assert user
    return MemberOut(id=m.id, user_id=user.id, name=user.name, email=user.email, role=role, status=m.status, joined_at=m.created_at)


async def remove_member(session: AsyncSession, principal: Principal, membership_id: UUID) -> None:
    m = await _get_membership(session, principal, membership_id)
    _assert_can_assign(principal, Role(m.role), Role(m.role))
    if m.role == Role.OWNER.value and await _owner_count(session, m.org_id) <= 1:
        raise Conflict("A workspace must keep at least one owner.", code="last_owner")
    await record(
        session, action="member.removed", target_type="membership", target_id=m.id, actor=principal, before={"user_id": str(m.user_id), "role": m.role}
    )
    await session.delete(m)
    # Revoke that user's sessions bound to this org so access ends immediately.
    for auth in (
        await session.execute(select(AuthSession).where(AuthSession.user_id == m.user_id, AuthSession.org_id == m.org_id, AuthSession.revoked_at.is_(None)))
    ).scalars():
        auth.revoked_at, auth.revoke_reason = _now(), "membership_removed"


async def invite(session: AsyncSession, principal: Principal, *, email: str, role: Role) -> InvitationOut:
    _assert_can_assign(principal, role)
    from agentfirm.modules.billing.accounts import check_seat

    await check_seat(session, principal.org_id)  # plan limit (checked again on acceptance)
    token = secrets.token_urlsafe(32)
    inv = Invitation(
        org_id=principal.org_id,
        email=email.strip(),
        role=role.value,
        token_hash=hash_token(token),
        invited_by=principal.user_id,
        expires_at=_now() + timedelta(days=7),
    )
    session.add(inv)
    await session.flush()
    await record(session, action="member.invited", target_type="invitation", target_id=inv.id, actor=principal, after={"email": inv.email, "role": role.value})
    return InvitationOut(id=inv.id, email=inv.email, role=role, expires_at=inv.expires_at, token=None if get_settings().is_production else token)


async def accept_invitation(session: AsyncSession, principal: Principal, token: str) -> MembershipOrgOut:
    org_id = await session.scalar(text("SELECT invitation_org(:h)"), {"h": hash_token(token)})
    if org_id is None:
        raise NotFound("Invitation not found or expired.")
    await apply_context(session, DbContext(org_id=org_id, user_id=principal.user_id))
    inv = (await session.execute(select(Invitation).where(Invitation.token_hash == hash_token(token), Invitation.org_id == org_id))).scalar_one()
    if inv.email.lower() != principal.email.lower():
        raise Forbidden("This invitation was sent to a different email address.", code="invite_email_mismatch")
    existing = (await session.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == principal.user_id))).scalar_one_or_none()
    if existing:
        raise Conflict("You are already a member of this workspace.")
    from agentfirm.modules.billing.accounts import check_seat

    await check_seat(session, org_id)
    inv.accepted_at = _now()
    session.add(Membership(org_id=org_id, user_id=principal.user_id, role=inv.role))
    await record(
        session,
        action="member.joined",
        target_type="invitation",
        target_id=inv.id,
        actor_user_id=principal.user_id,
        org_id=org_id,
        ip=principal.ip,
        after={"role": inv.role},
    )
    await session.flush()
    org = await session.get(Organization, org_id)
    return MembershipOrgOut(organization=OrgOut.model_validate(org), role=Role(inv.role))


def permissions_for(role: Role | None) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS[role]) if role else []


__all__ = ["ROLE_RANK", "Unprocessable"]
