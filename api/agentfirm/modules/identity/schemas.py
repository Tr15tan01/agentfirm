from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from agentfirm.core.permissions import Role


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    organization_name: str = Field(min_length=2, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    organization_id: UUID | None = None


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class SwitchOrgIn(BaseModel):
    organization_id: UUID


class UserOut(Schema):
    id: UUID
    email: str
    name: str
    is_super_admin: bool


class OrgOut(Schema):
    id: UUID
    name: str
    slug: str


class MembershipOrgOut(BaseModel):
    organization: OrgOut
    role: Role


class TokenPair(BaseModel):
    token_type: str = "bearer"
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: UserOut
    organization: OrgOut | None
    role: Role | None


class AccessToken(BaseModel):
    token_type: str = "bearer"
    access_token: str
    access_expires_at: datetime
    organization: OrgOut | None
    role: Role | None


class MeOut(BaseModel):
    user: UserOut
    organization: OrgOut | None
    role: Role | None
    permissions: list[str]
    memberships: list[MembershipOrgOut]


class SessionOut(Schema):
    id: UUID
    user_agent: str | None
    ip: str | None
    created_at: datetime
    last_used_at: datetime
    current: bool = False


class MemberOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    email: str
    role: Role
    status: str
    joined_at: datetime


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.MEMBER


class InvitationOut(BaseModel):
    id: UUID
    email: str
    role: Role
    expires_at: datetime
    #: Returned only outside production (no email delivery yet). Production emails it.
    token: str | None = None


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class RoleChangeIn(BaseModel):
    role: Role
