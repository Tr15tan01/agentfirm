"""Import every model so Base.metadata is complete (Alembic, tests)."""

from agentfirm.core.models_base import TENANT_TABLES, Base
from agentfirm.modules.agents.models import Agent, AgentVersion, OrgAgentSetting
from agentfirm.modules.audit.models import AuditLog
from agentfirm.modules.billing.models import BillingEvent, CreditBalance, CreditLedgerEntry, CreditPack, Invoice, Plan, Subscription, UsageRecord
from agentfirm.modules.conversations.models import Conversation, Message
from agentfirm.modules.gateway.models import Model, ModelProvider, ModelRoute, ProviderCredential
from agentfirm.modules.governance.models import StandingApproval, ToolOverride
from agentfirm.modules.ideas.models import Idea
from agentfirm.modules.identity.models import AuthSession, Invitation, Membership, Organization, PermissionRow, RolePermission, RoleRow, User
from agentfirm.modules.integrations.models import Connection, ContentCalendarEntry, EmailDraft, ReportSchedule
from agentfirm.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from agentfirm.modules.memory.models import Memory
from agentfirm.modules.projects.models import Project
from agentfirm.modules.tasks.models import ApprovalRequest, Artifact, ExecutionEvent, StepResult, Task, TaskExecution, ToolExecution

__all__ = [
    "TENANT_TABLES",
    "Agent",
    "AgentVersion",
    "ApprovalRequest",
    "Artifact",
    "AuditLog",
    "AuthSession",
    "Base",
    "BillingEvent",
    "Connection",
    "ContentCalendarEntry",
    "Conversation",
    "CreditBalance",
    "CreditLedgerEntry",
    "CreditPack",
    "EmailDraft",
    "ExecutionEvent",
    "Idea",
    "Invitation",
    "Invoice",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Membership",
    "Memory",
    "Message",
    "Model",
    "ModelProvider",
    "ModelRoute",
    "OrgAgentSetting",
    "Organization",
    "PermissionRow",
    "Plan",
    "Project",
    "ProviderCredential",
    "ReportSchedule",
    "RolePermission",
    "RoleRow",
    "StandingApproval",
    "StepResult",
    "Subscription",
    "Task",
    "TaskExecution",
    "ToolExecution",
    "ToolOverride",
    "UsageRecord",
    "User",
]
