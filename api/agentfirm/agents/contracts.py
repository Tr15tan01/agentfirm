"""Agent contracts — the machine-readable half of docs/agents/.

Three families of models live here:

1. **AgentManifest**: the 20-point standard agent definition (brief §21.1). Each
   specialised agent is a manifest (YAML) plus an optional LangGraph sub-graph; the
   shared engine executes it. Manifests are versioned and immutable once published.
2. **Interface envelopes**: `AgentTask` (orchestrator → agent), `AgentResult` (agent →
   orchestrator), `HandoffRequest`, `ContextPack`, `Budget`, `AgentError`.
3. **Events**: the typed execution events that the engine persists and streams over SSE.

The JSON Schemas in docs/agents/schemas/ are generated from these models (see
`agentfirm.agents.schemas`), and a test fails if the committed copies drift.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── Vocabularies ─────────────────────────────────────────────────────────────

ModelCapability = Literal["reasoning", "text", "code", "summarize", "classify", "creative", "vision", "long_context", "embeddings"]


class SideEffect(StrEnum):
    """What a tool can change. Anything beyond INTERNAL must be approval-gated."""

    NONE = "none"  # read-only
    INTERNAL = "internal"  # changes AgentFirm state only (artifacts, idea board, drafts)
    EXTERNAL = "external"  # visible outside AgentFirm (publish, send, deploy preview)
    FINANCIAL = "financial"  # spends or moves money
    DESTRUCTIVE = "destructive"  # irreversible (production deploy, delete data)


CONSEQUENTIAL = {SideEffect.EXTERNAL, SideEffect.FINANCIAL, SideEffect.DESTRUCTIVE}


class ApprovalPolicy(StrEnum):
    AUTO = "auto"
    REQUIRE = "require_approval"
    DENY = "deny"


APPROVAL_STRICTNESS = {ApprovalPolicy.AUTO: 0, ApprovalPolicy.REQUIRE: 1, ApprovalPolicy.DENY: 2}


class SharedCapability(StrEnum):
    """Reusable services (brief §21.8) — implemented once, invoked by many agents."""

    BRAINSTORMING = "brainstorming_engine"
    RESEARCH_RETRIEVAL = "research_retrieval_engine"
    DOCUMENT_PROCESSING = "document_processing_engine"
    PLANNING = "planning_engine"
    WEB_SEARCH = "web_search"
    CODE_EXECUTION = "code_execution"
    DATA_ANALYSIS = "data_analysis"
    MEMORY = "memory_service"


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    MISSING_CONTEXT = "missing_context"
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    MODEL_ERROR = "model_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    BUDGET_EXCEEDED = "budget_exceeded"
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    POLICY_VIOLATION = "policy_violation"
    UNSAFE_CONTENT = "unsafe_content"
    UPSTREAM_DATA_INVALID = "upstream_data_invalid"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


AgentKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,47}$")]
ToolKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── Tool catalog (shared Tool Registry definitions) ─────────────────────────


class ToolSpec(Strict):
    key: ToolKey
    label: str
    description: str
    side_effect: SideEffect
    default_approval: ApprovalPolicy
    #: RBAC permission the *requesting user* must hold for the agent to use this tool.
    required_permission: str
    shared_capability: SharedCapability | None = None
    network: Literal["none", "allowlist", "internet"] = "none"
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_per_minute: int = Field(default=60, ge=1)
    idempotent: bool = True
    #: Integration/provider (open decisions are marked "TBD:" and tracked in specs).
    provider: str
    status: Literal["available", "planned"] = "planned"

    @model_validator(mode="after")
    def _consequential_needs_approval(self) -> ToolSpec:
        if self.side_effect in CONSEQUENTIAL and self.default_approval == ApprovalPolicy.AUTO:
            raise ValueError(f"{self.key}: {self.side_effect} tools cannot default to auto-approval")
        return self


class ToolCatalog(Strict):
    schema_version: Literal["1"]
    tools: list[ToolSpec]

    def by_key(self) -> dict[str, ToolSpec]:
        return {t.key: t for t in self.tools}


# ── Agent manifest (brief §21.1) ─────────────────────────────────────────────


class Intent(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    description: str
    workflow: str
    examples: list[str] = Field(min_length=2)
    counter_examples: list[str] = Field(default_factory=list, description="Requests that look similar but belong elsewhere")
    min_confidence: float = Field(default=0.6, ge=0, le=1)


class InputParam(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    type: Literal["string", "text", "number", "boolean", "enum", "file", "list", "url", "date"]
    required: bool = False
    description: str
    enum: list[str] | None = None

    @model_validator(mode="after")
    def _enum_values(self) -> InputParam:
        if (self.type == "enum") != bool(self.enum):
            raise ValueError(f"{self.name}: enum params need values (and only enum params may have them)")
        return self


StepKind = Literal["plan", "classify", "retrieve", "model", "tool", "delegate", "approval", "verify", "synthesize", "human_input"]


class WorkflowStep(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    title: str
    kind: StepKind
    capability: ModelCapability | None = None
    tools: list[ToolKey] = Field(default_factory=list)
    #: Relative weight for progress = Σ completed weights ÷ Σ weights (never guessed).
    weight: float = Field(default=1.0, gt=0, le=10)
    checkpoint: bool = True
    on_failure: Literal["retry", "fallback_model", "skip", "replan", "ask_user", "fail"] = "retry"
    parallel_group: str | None = Field(default=None, description="Steps sharing a group may run concurrently")


class Workflow(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    title: str
    description: str
    steps: list[WorkflowStep] = Field(min_length=2)

    @field_validator("steps")
    @classmethod
    def _unique_steps(cls, steps: list[WorkflowStep]) -> list[WorkflowStep]:
        keys = [s.key for s in steps]
        if len(keys) != len(set(keys)):
            raise ValueError("workflow step keys must be unique")
        return steps


class ToolGrant(Strict):
    tool: ToolKey
    #: Optional override. May only make the policy STRICTER than the catalog default.
    approval: ApprovalPolicy | None = None
    max_calls_per_run: int = Field(default=20, ge=1, le=500)
    notes: str | None = None


KnowledgeSource = Literal[
    "workspace_files",
    "project_knowledge",
    "conversation_history",
    "web",
    "connectors",
    "brand_memory",
    "repositories",
    "idea_board",
    "structured_data",
    "agent_results",
]


class KnowledgeAccess(Strict):
    sources: list[KnowledgeSource] = Field(min_length=1)
    scope: Literal["project", "workspace"] = "workspace"
    citations_required: bool = False
    pii: Literal["avoid", "minimise"] = "minimise"
    #: Content from these sources is UNTRUSTED data: never instructions (prompt-injection defence).
    untrusted_sources: list[KnowledgeSource] = Field(default_factory=list)


class MemoryPolicy(Strict):
    conversation: bool = True
    user_preferences: bool = False
    project: bool = True
    agent_memory: list[str] = Field(default_factory=list, description="Named org-scoped memories, e.g. brand_voice")
    retention_days: int = Field(default=365, ge=1, le=3650)
    writes_require_confirmation: bool = False


class ModelPolicy(Strict):
    capabilities: list[ModelCapability] = Field(min_length=1, description="Capabilities this agent may request from the Model Gateway")
    default_capability: ModelCapability
    temperature: dict[ModelCapability, float] = Field(default_factory=dict)
    max_output_tokens: int = Field(default=4096, ge=256, le=64_000)
    preferences: list[str] = Field(default_factory=list, description="Routing hints for super-admins (non-binding)")

    @model_validator(mode="after")
    def _default_in_caps(self) -> ModelPolicy:
        if self.default_capability not in self.capabilities:
            raise ValueError("default_capability must be one of capabilities")
        return self


class Deliverable(Strict):
    key: str
    title: str
    format: Literal["markdown", "pdf", "docx", "xlsx", "csv", "json", "code_patch", "chart", "ideas", "email_draft", "calendar_proposal"]
    description: str


class CollaborationPolicy(Strict):
    can_delegate_to: list[AgentKey] = Field(default_factory=list)
    accepts_from: list[str] = Field(default_factory=lambda: ["user", "orchestrator"])
    shared_capabilities: list[SharedCapability] = Field(default_factory=list)
    #: Shared capability this agent itself provides to others (e.g. creative → brainstorming_engine).
    provides: list[SharedCapability] = Field(default_factory=list)


class ApprovalRule(Strict):
    key: str
    description: str
    tools: list[ToolKey] = Field(min_length=1)
    approver_permission: str = "approvals:decide"
    preview_required: bool = True
    timeout_hours: int = Field(default=72, ge=1, le=720)
    on_timeout: Literal["expire_and_replan", "cancel_execution"] = "expire_and_replan"


class RecoveryRule(Strict):
    error: ErrorCode
    strategy: Literal["retry_backoff", "fallback_model", "replan", "ask_user", "partial_result", "fail"]
    max_attempts: int = Field(default=1, ge=0, le=5)


class ExecutionLimits(Strict):
    max_steps: int = Field(ge=1, le=200)
    max_runtime_seconds: int = Field(ge=30, le=6 * 3600)
    max_credits: int = Field(ge=1, le=5000)
    max_tool_calls: int = Field(ge=0, le=500)
    max_parallel_subtasks: int = Field(default=1, ge=1, le=8)
    max_delegation_depth: int = Field(default=1, ge=0, le=2)


class QualityGate(Strict):
    metric: str
    threshold: float
    direction: Literal["min", "max"]
    description: str


class AgentManifest(Strict):
    """The standard agent definition (brief §21.1, items 1-20)."""

    schema_version: Literal["1"]
    # 1 identity · 20 versioning
    key: AgentKey
    name: str
    version: str
    status: Literal["draft", "published"] = "draft"
    changelog: list[str] = Field(min_length=1)
    description: str
    # 2 mission · 3 responsibilities · 4 scope & limitations
    mission: str
    responsibilities: list[str] = Field(min_length=3)
    scope_in: list[str] = Field(min_length=2)
    scope_out: list[str] = Field(min_length=2)
    limitations: list[str] = Field(min_length=1)
    # 5 capabilities · 6 intents · 7 inputs · 8 workflows
    capabilities: list[str] = Field(min_length=3)
    intents: list[Intent] = Field(min_length=2)
    inputs: list[InputParam] = Field(default_factory=list)
    workflows: list[Workflow] = Field(min_length=1)
    # 9 tools · 10 knowledge · 11 memory · 12 models
    tools: list[ToolGrant] = Field(min_length=1)
    knowledge: KnowledgeAccess
    memory: MemoryPolicy
    models: ModelPolicy
    # 13 outputs · 14 collaboration · 15 permissions · 16 approvals
    deliverables: list[Deliverable] = Field(min_length=1)
    collaboration: CollaborationPolicy
    permissions: list[str] = Field(min_length=1, description="RBAC permissions the requesting user needs to invoke this agent")
    approvals: list[ApprovalRule] = Field(default_factory=list)
    # 17 recovery · 18 limits · 19 quality
    recovery: list[RecoveryRule] = Field(min_length=1)
    limits: ExecutionLimits
    quality: list[QualityGate] = Field(min_length=2)
    #: Behavioural invariants enforced by prompts AND by verification steps/evals.
    rules: list[str] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.match(v):
            raise ValueError("version must be semantic (MAJOR.MINOR.PATCH)")
        return v

    def workflow(self, key: str) -> Workflow:
        return next(w for w in self.workflows if w.key == key)

    def plan_weight(self, workflow_key: str) -> float:
        return sum(s.weight for s in self.workflow(workflow_key).steps)


# ── Interface envelopes (orchestrator ↔ agent) ───────────────────────────────


class FileRef(Strict):
    id: UUID
    name: str
    kind: str


class UntrustedContent(Strict):
    """Wrapper for anything not written by the requesting user (web pages, files, tool
    output, other agents' raw results). The engine renders it inside explicit data
    delimiters; it can never grant permissions or change the plan's tool set."""

    source: str
    origin: str | None = None
    content: str = Field(max_length=200_000)


class SubtaskResultRef(Strict):
    execution_id: UUID
    agent: AgentKey
    summary: str
    artifact_ids: list[UUID] = Field(default_factory=list)


class ContextPack(Strict):
    conversation_summary: str | None = None
    project_id: UUID | None = None
    files: list[FileRef] = Field(default_factory=list)
    memory: dict[str, str] = Field(default_factory=dict)
    prior_results: list[SubtaskResultRef] = Field(default_factory=list)
    untrusted: list[UntrustedContent] = Field(default_factory=list)


class Budget(Strict):
    max_credits: int = Field(ge=1)
    max_runtime_seconds: int = Field(ge=1)
    max_steps: int = Field(ge=1)
    deadline: datetime | None = None


class AgentTask(Strict):
    """Orchestrator → agent invocation. Identical whether the caller is a user request,
    the orchestrator, or another agent's handoff (with delegation_depth > 0)."""

    task_id: UUID
    execution_id: UUID
    parent_execution_id: UUID | None = None
    org_id: UUID
    requested_by: UUID
    agent: AgentKey
    agent_version: str
    objective: str = Field(min_length=1, max_length=8000)
    intent: str | None = Field(default=None, description="Pre-classified intent; agent re-classifies if None")
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: ContextPack = Field(default_factory=ContextPack)
    budget: Budget
    delegation_depth: int = Field(default=0, ge=0, le=2)
    deliverables_expected: list[str] = Field(default_factory=list)
    locale: str = "en"
    idempotency_key: str


class Citation(Strict):
    source_id: str
    title: str
    url: str | None = None
    accessed_at: datetime | None = None
    excerpt: str | None = Field(default=None, max_length=300)


class Claim(Strict):
    text: str
    #: verified = backed by cited sources; assumption = stated premise; estimate = derived
    #: number with shown method; speculative = creative possibility, not a fact.
    status: Literal["verified", "assumption", "estimate", "speculative"]
    citations: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verified_needs_citation(self) -> Claim:
        if self.status == "verified" and not self.citations:
            raise ValueError("verified claims must carry at least one citation")
        return self


class ArtifactRef(Strict):
    id: UUID
    name: str
    kind: str


class HandoffRequest(Strict):
    to_agent: AgentKey
    objective: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    blocking: bool = True
    context: ContextPack = Field(default_factory=ContextPack)


class UsageSummary(Strict):
    credits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    models: list[str] = Field(default_factory=list)


class AgentError(Strict):
    code: ErrorCode
    message: str
    retriable: bool
    step: str | None = None


class AgentResult(Strict):
    execution_id: UUID
    status: Literal["completed", "partial", "needs_input", "failed", "cancelled"]
    summary: str = Field(description="Markdown answer shown to the user")
    claims: list[Claim] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    handoffs: list[HandoffRequest] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, description="Populated when status = needs_input")
    usage: UsageSummary = Field(default_factory=UsageSummary)
    quality: dict[str, float] = Field(default_factory=dict)
    error: AgentError | None = None

    @model_validator(mode="after")
    def _consistency(self) -> AgentResult:
        if self.status == "failed" and self.error is None:
            raise ValueError("failed results must include an error")
        if self.status == "needs_input" and not self.questions:
            raise ValueError("needs_input results must include questions")
        return self


# ── Execution events (persisted, then streamed over SSE) ─────────────────────


class _Event(Strict):
    execution_id: UUID
    seq: int = Field(ge=1)
    at: datetime


class PlanStepRef(Strict):
    key: str
    title: str
    weight: float = Field(gt=0)
    agent: AgentKey | Literal["orchestrator"]


class PlanCreated(_Event):
    type: Literal["plan.created"] = "plan.created"
    steps: list[PlanStepRef] = Field(min_length=1)


class PlanUpdated(_Event):
    type: Literal["plan.updated"] = "plan.updated"
    steps: list[PlanStepRef] = Field(min_length=1)
    reason: str


class StepStarted(_Event):
    type: Literal["step.started"] = "step.started"
    step: str


class StepCompleted(_Event):
    type: Literal["step.completed"] = "step.completed"
    step: str


class StepFailed(_Event):
    type: Literal["step.failed"] = "step.failed"
    step: str
    error: AgentError


class ToolCalled(_Event):
    type: Literal["tool.called"] = "tool.called"
    call_id: str
    tool: ToolKey
    side_effect: SideEffect
    input_summary: str = Field(max_length=500, description="Redacted summary — never secrets")


class ToolResult(_Event):
    type: Literal["tool.result"] = "tool.result"
    call_id: str
    tool: ToolKey
    status: Literal["ok", "error", "timeout", "blocked"]
    duration_ms: int


class ModelCalled(_Event):
    type: Literal["model.called"] = "model.called"
    capability: ModelCapability
    provider: str
    model: str
    fallback_index: int = Field(ge=0, description="0 = primary route, n = n-th fallback")
    tokens_in: int
    tokens_out: int


class TokenDelta(_Event):
    type: Literal["token.delta"] = "token.delta"
    text: str


class ApprovalRequested(_Event):
    type: Literal["approval.requested"] = "approval.requested"
    approval_id: UUID
    tool: ToolKey
    side_effect: SideEffect
    title: str
    preview: str | None = None


class ApprovalResolved(_Event):
    type: Literal["approval.resolved"] = "approval.resolved"
    approval_id: UUID
    decision: Literal["approved", "rejected", "expired"]


class ArtifactCreated(_Event):
    type: Literal["artifact.created"] = "artifact.created"
    artifact: ArtifactRef


class SubtaskSpawned(_Event):
    type: Literal["subtask.spawned"] = "subtask.spawned"
    subtask_execution_id: UUID
    agent: AgentKey
    depends_on: list[UUID] = Field(default_factory=list)


class SubtaskCompleted(_Event):
    type: Literal["subtask.completed"] = "subtask.completed"
    subtask_execution_id: UUID
    status: Literal["completed", "partial", "failed", "cancelled"]


class Progress(_Event):
    """Emitted only by the engine, computed from plan weights — agents cannot emit it."""

    type: Literal["progress"] = "progress"
    completed_weight: float = Field(ge=0)
    total_weight: float = Field(gt=0)

    @model_validator(mode="after")
    def _bounded(self) -> Progress:
        if self.completed_weight > self.total_weight:
            raise ValueError("completed_weight cannot exceed total_weight")
        return self


class ExecutionStatus(_Event):
    type: Literal["execution.status"] = "execution.status"
    status: Literal["queued", "running", "waiting_approval", "paused", "completed", "failed", "cancelled"]


class Log(_Event):
    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warn", "error"]
    message: str = Field(max_length=2000)


AgentEvent = Annotated[
    PlanCreated
    | PlanUpdated
    | StepStarted
    | StepCompleted
    | StepFailed
    | ToolCalled
    | ToolResult
    | ModelCalled
    | TokenDelta
    | ApprovalRequested
    | ApprovalResolved
    | ArtifactCreated
    | SubtaskSpawned
    | SubtaskCompleted
    | Progress
    | ExecutionStatus
    | Log,
    Field(discriminator="type"),
]


class EventEnvelope(Strict):
    event: AgentEvent


# ── Evaluation cases (brief §21.10) ──────────────────────────────────────────

EvalCategory = Literal[
    "classification",
    "output_quality",
    "tool_selection",
    "workflow_completion",
    "permission_enforcement",
    "error_recovery",
    "hallucination_resistance",
    "cost",
    "duration",
    "collaboration",
]
EVAL_CATEGORIES: tuple[str, ...] = EvalCategory.__args__  # type: ignore[attr-defined]


class EvalExpectation(Strict):
    intent: str | None = None
    workflow: str | None = None
    status: Literal["completed", "partial", "needs_input", "failed", "cancelled"] | None = None
    error_code: ErrorCode | None = None
    tools_called: list[ToolKey] = Field(default_factory=list)
    tools_not_called: list[ToolKey] = Field(default_factory=list)
    approval_required_for: list[ToolKey] = Field(default_factory=list)
    handoff_to: list[AgentKey] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    claim_statuses_required: list[Literal["verified", "assumption", "estimate", "speculative"]] = Field(default_factory=list)
    max_credits: int | None = None
    max_duration_seconds: int | None = None
    rubric: list[str] = Field(default_factory=list, description="LLM-judge / human rubric statements that must hold")
    # Orchestrated (multi-agent) cases:
    subtask_agents: list[AgentKey] = Field(default_factory=list, description="Agents of the subtasks, in creation order")
    handoff_edges: list[str] = Field(default_factory=list, description="Accepted handoffs, as 'from->to'")
    skipped_agents: list[AgentKey] = Field(default_factory=list)


class EvalCase(Strict):
    id: str = Field(pattern=r"^[a-z]+-[a-z0-9-]+$")
    category: EvalCategory
    description: str
    objective: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    setup: list[str] = Field(default_factory=list, description="Fixture directives for the harness (stubbed tools, injected failures)")
    requester_role: Literal["owner", "admin", "member", "viewer"] = "member"
    #: Orchestrator suite only: agents the user selects (empty = the orchestrator chooses).
    agents: list[AgentKey] = Field(default_factory=list)
    expect: EvalExpectation


class EvalSuite(Strict):
    schema_version: Literal["1"]
    agent: AgentKey
    cases: list[EvalCase] = Field(min_length=10)
