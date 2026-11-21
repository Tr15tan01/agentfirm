from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Identity, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentfirm.core.models_base import Base, created_at, tenant_table, uuid_pk

EXECUTION_STATUSES = ("queued", "running", "waiting_approval", "paused", "completed", "failed", "cancelled", "blocked", "waiting_subtasks", "skipped")
#: Statuses after which an execution never runs again.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "skipped"})
SIDE_EFFECTS = ("none", "internal", "external", "financial", "destructive")


class Task(Base):
    __tablename__ = tenant_table("tasks")
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "idempotency_key"),
        ForeignKeyConstraint(["org_id", "project_id"], ["projects.org_id", "projects.id"], ondelete="SET NULL (project_id)"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    #: Agent-specific parameters validated against the manifest `inputs` (e.g. depth, approach).
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = created_at()


class TaskExecution(Base):
    __tablename__ = tenant_table("task_executions")
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "task_id"], ["tasks.org_id", "tasks.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["org_id", "parent_execution_id"], ["task_executions.org_id", "task_executions.id"], ondelete="CASCADE"),
        CheckConstraint(f"status IN {EXECUTION_STATUSES}", name="status"),
        # Progress is NULL when unknown — never a guessed number.
        CheckConstraint("progress IS NULL OR (progress >= 0 AND progress <= 1)", name="progress_range"),
        CheckConstraint("steps_total IS NULL OR (steps_completed >= 0 AND steps_completed <= steps_total)", name="steps"),
        CheckConstraint("kind IN ('agent', 'orchestrator')", name="kind"),
        CheckConstraint("kind = 'orchestrator' OR agent_version_id IS NOT NULL", name="agent_version"),
        CheckConstraint("delegation_depth BETWEEN 0 AND 2", name="delegation_depth"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[UUID] = mapped_column(index=True)
    parent_execution_id: Mapped[UUID | None] = mapped_column()
    agent_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_versions.id"))
    #: agent = runs one agent version; orchestrator = plans and coordinates subtasks (Phase 5).
    kind: Mapped[str] = mapped_column(String(16), default="agent", server_default="agent")
    # Subtasks (children of an orchestrator execution):
    subtask_key: Mapped[str | None] = mapped_column(String(48))
    objective: Mapped[str | None] = mapped_column(Text)  # None → the task's objective
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # None → the task's parameters
    #: Upstream results handed to this subtask (data, never instructions).
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    depends_on: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    delegation_depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    origin: Mapped[str | None] = mapped_column(String(48))  # "orchestrator" or the agent that handed off
    status: Mapped[str] = mapped_column(String(24), default="queued", server_default="queued")
    progress: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    stage: Mapped[str | None] = mapped_column(String(240))
    steps_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    steps_total: Mapped[int | None] = mapped_column(Integer)
    queued_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    # Phase 4: worker leases, budgets and the final AgentResult.
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    budget_credits: Mapped[int | None] = mapped_column(Integer)
    credits_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ExecutionEvent(Base):
    """Append-only event log; `seq` is monotonic per execution (SSE Last-Event-ID)."""

    __tablename__ = tenant_table("execution_events")
    __table_args__ = (
        UniqueConstraint("execution_id", "seq"),
        ForeignKeyConstraint(["org_id", "execution_id"], ["task_executions.org_id", "task_executions.id"], ondelete="CASCADE"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID] = mapped_column(index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = created_at()


class ApprovalRequest(Base):
    __tablename__ = tenant_table("approval_requests")
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "execution_id"], ["task_executions.org_id", "task_executions.id"], ondelete="CASCADE"),
        CheckConstraint("status IN ('pending','approved','rejected','expired')", name="status"),
        CheckConstraint(f"side_effect IN {SIDE_EFFECTS}", name="side_effect"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID] = mapped_column(index=True)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"))
    tool_key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(Text)
    preview: Mapped[str | None] = mapped_column(Text)
    side_effect: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    #: Set when a standing approval (not a person, at the time) approved this request.
    standing_approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("standing_approvals.id"))
    created_at: Mapped[datetime] = created_at()


class Artifact(Base):
    __tablename__ = tenant_table("artifacts")
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(["org_id", "execution_id"], ["task_executions.org_id", "task_executions.id"], ondelete="CASCADE"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    #: R2 object key — always prefixed org/{org_id}/; served via presigned URLs only.
    storage_key: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = created_at()


class ToolExecution(Base):
    """One row per side-effecting or audited tool call. `idempotency_key` =
    execution:step:tool:call-index, so a resumed run never repeats a side effect."""

    __tablename__ = tenant_table("tool_executions")
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_tool_executions_idempotency"),
        ForeignKeyConstraint(["org_id", "execution_id"], ["task_executions.org_id", "task_executions.id"], ondelete="CASCADE"),
        CheckConstraint("status IN ('ok','error','timeout','blocked')", name="ck_tool_executions_status"),
    )

    id: Mapped[UUID] = uuid_pk()
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID] = mapped_column(index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    tool: Mapped[str] = mapped_column(String(80))
    side_effect: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    input_summary: Mapped[str | None] = mapped_column(String(500))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()


class StepResult(Base):
    """Output of a completed workflow step, committed atomically with its step.completed
    event (see engine: a recorded step is restored on resume instead of re-executed)."""

    __tablename__ = tenant_table("step_results")
    __table_args__ = (
        UniqueConstraint("execution_id", "step", name="uq_step_results_execution_step"),
        ForeignKeyConstraint(["org_id", "execution_id"], ["task_executions.org_id", "task_executions.id"], ondelete="CASCADE"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[UUID] = mapped_column()
    step: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
