"""Organisation roles → permissions. Code is the source of truth; the initial
migration seeds `roles`, `permissions` and `role_permissions` from this mapping
and a test asserts they stay identical."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Perm(StrEnum):
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    MEMBERS_MANAGE_OWNERS = "members:manage_owners"
    AGENTS_USE = "agents:use"
    AGENTS_CONFIGURE = "agents:configure"
    TASKS_READ = "tasks:read"
    TASKS_CREATE = "tasks:create"
    TASKS_CONTROL = "tasks:control"
    APPROVALS_DECIDE = "approvals:decide"
    PROJECTS_MANAGE = "projects:manage"
    KNOWLEDGE_MANAGE = "knowledge:manage"
    USAGE_READ = "usage:read"
    BILLING_MANAGE = "billing:manage"
    AUDIT_READ = "audit:read"


ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.OWNER: "Full control, billing and deletion",
    Role.ADMIN: "Manage members, agents and integrations",
    Role.MEMBER: "Create and run tasks, decide approvals",
    Role.VIEWER: "Read-only access to results",
}

_VIEWER = {Perm.WORKSPACE_READ, Perm.MEMBERS_READ, Perm.TASKS_READ, Perm.USAGE_READ}
_MEMBER = _VIEWER | {Perm.AGENTS_USE, Perm.TASKS_CREATE, Perm.TASKS_CONTROL, Perm.APPROVALS_DECIDE, Perm.PROJECTS_MANAGE, Perm.KNOWLEDGE_MANAGE}
_ADMIN = _MEMBER | {Perm.WORKSPACE_MANAGE, Perm.MEMBERS_MANAGE, Perm.AGENTS_CONFIGURE, Perm.AUDIT_READ}
_OWNER = _ADMIN | {Perm.MEMBERS_MANAGE_OWNERS, Perm.BILLING_MANAGE}

ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.MEMBER: frozenset(_MEMBER),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset(_OWNER),
}

ROLE_RANK = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}
