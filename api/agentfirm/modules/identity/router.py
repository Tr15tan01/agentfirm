from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from agentfirm.core.deps import CurrentPrincipal, DbSession, Principal, client_ip, require
from agentfirm.core.permissions import Perm

from . import service
from .schemas import (
    AcceptInviteIn,
    AccessToken,
    InvitationOut,
    InviteIn,
    LoginIn,
    MemberOut,
    MembershipOrgOut,
    MeOut,
    OrgOut,
    RefreshIn,
    RegisterIn,
    RoleChangeIn,
    SessionOut,
    SwitchOrgIn,
    TokenPair,
    UserOut,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
members_router = APIRouter(prefix="/members", tags=["members"])


@auth_router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, session: DbSession) -> TokenPair:
    return await service.register(
        session,
        email=body.email,
        name=body.name,
        password=body.password,
        org_name=body.organization_name,
        ip=client_ip(request),
        ua=request.headers.get("user-agent"),
    )


@auth_router.post("/login", response_model=TokenPair)
async def login(body: LoginIn, request: Request, session: DbSession) -> TokenPair:
    return await service.login(
        session,
        email=body.email,
        password=body.password,
        preferred_org=body.organization_id,
        ip=client_ip(request),
        ua=request.headers.get("user-agent"),
    )


@auth_router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, request: Request, session: DbSession) -> TokenPair:
    return await service.refresh(session, refresh_token=body.refresh_token, ip=client_ip(request))


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: CurrentPrincipal, session: DbSession) -> Response:
    await service.logout(session, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal, session: DbSession) -> MeOut:
    memberships = await service.my_memberships(session, principal)
    current = next((m.organization for m in memberships if m.organization.id == principal.org_id), None)
    return MeOut(
        user=UserOut(id=principal.user_id, email=principal.email, name=principal.name, is_super_admin=principal.is_super_admin),
        organization=current,
        role=principal.role,
        permissions=service.permissions_for(principal.role),
        memberships=memberships,
    )


@auth_router.get("/sessions", response_model=list[SessionOut])
async def sessions(principal: CurrentPrincipal, session: DbSession) -> list[SessionOut]:
    rows = await service.list_sessions(session, principal)
    return [SessionOut.model_validate(r).model_copy(update={"current": r.id == principal.session_id}) for r in rows]


@auth_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: UUID, principal: CurrentPrincipal, session: DbSession) -> Response:
    await service.revoke_session(session, principal, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/switch-organization", response_model=AccessToken)
async def switch_org(body: SwitchOrgIn, principal: CurrentPrincipal, session: DbSession) -> AccessToken:
    return await service.switch_org(session, principal, body.organization_id)


@auth_router.post("/invitations/accept", response_model=MembershipOrgOut)
async def accept_invitation(body: AcceptInviteIn, principal: CurrentPrincipal, session: DbSession) -> MembershipOrgOut:
    return await service.accept_invitation(session, principal, body.token)


@members_router.get("", response_model=list[MemberOut])
async def list_members(session: DbSession, principal: Principal = require(Perm.MEMBERS_READ)) -> list[MemberOut]:
    return await service.list_members(session, principal)


@members_router.post("/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def invite(body: InviteIn, session: DbSession, principal: Principal = require(Perm.MEMBERS_MANAGE)) -> InvitationOut:
    return await service.invite(session, principal, email=body.email, role=body.role)


@members_router.patch("/{membership_id}", response_model=MemberOut)
async def change_role(membership_id: UUID, body: RoleChangeIn, session: DbSession, principal: Principal = require(Perm.MEMBERS_MANAGE)) -> MemberOut:
    return await service.change_role(session, principal, membership_id, body.role)


@members_router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(membership_id: UUID, session: DbSession, principal: Principal = require(Perm.MEMBERS_MANAGE)) -> Response:
    await service.remove_member(session, principal, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["OrgOut", "auth_router", "members_router"]
