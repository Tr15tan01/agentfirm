/**
 * Domain types shared by UI components. These mirror the backend API contracts
 * planned in docs/ARCHITECTURE.md §5–6 and will be replaced by types generated
 * from the FastAPI OpenAPI schema in Phase 3.
 */

export type AgentKey =
  | "research"
  | "marketing"
  | "engineer"
  | "bi"
  | "assistant"
  | "creative";

export type AgentStatus =
  | "available"
  | "working"
  | "waiting_approval"
  | "paused"
  | "completed"
  | "failed";

/** Visual state of the AgentActivityCore. */
export type CoreState = "idle" | "working" | "collaborating" | "completed" | "failed";

export interface AgentSummary {
  key: AgentKey;
  name: string;
  shortName: string;
  description: string;
  status: AgentStatus;
  currentTask: string | null;
  /** Seconds since last activity (relative so demo data never goes stale). */
  lastActiveSecondsAgo: number;
}

export type ExecutionStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface TaskRunSummary {
  id: string;
  executionId: string;
  title: string;
  agents: AgentKey[];
  status: ExecutionStatus;
  /**
   * 0–1 when the backend can compute it from the execution plan; `null` when
   * unknown — UI must then render an indeterminate indicator, never a guess.
   */
  progress: number | null;
  stage: string;
  stepsCompleted: number | null;
  stepsTotal: number | null;
  startedSecondsAgo: number;
  /** Planned and coordinated by the orchestrator (several agents, or chosen automatically). */
  orchestrated?: boolean;
}

export type TimelineEventKind =
  | "plan"
  | "step_started"
  | "step_completed"
  | "tool_call"
  | "model_call"
  | "approval"
  | "artifact"
  | "subtask"
  | "completed";

export interface TimelineEvent {
  seq: number;
  kind: TimelineEventKind;
  agent: AgentKey | "orchestrator";
  title: string;
  detail?: string;
  /** Offset from execution start, ms. */
  atMs: number;
}

export type ProviderKey = "openai" | "gemini" | "gn7t";

export type CapabilityKey =
  | "reasoning"
  | "text"
  | "code"
  | "summarize"
  | "classify"
  | "creative"
  | "vision"
  | "long_context"
  | "embeddings";

/* ── Phase 2 contracts ─────────────────────────────────────── */

export type SideEffect = "none" | "internal" | "external" | "financial" | "destructive";

export interface AgentTool {
  key: string;
  label: string;
  sideEffect: SideEffect;
  /** Approval policy resolved for this workspace. */
  approval: "auto" | "require_approval" | "deny";
}

export interface ExecutionRef {
  id: string;
  taskId: string;
  title: string;
  status: ExecutionStatus;
  durationSec: number;
  finishedSecondsAgo: number;
}

export interface AgentProfile extends AgentSummary {
  version: string;
  mission: string;
  capabilities: string[];
  /** Capability keys this agent requests from the Model Gateway. */
  modelCapabilities: CapabilityKey[];
  tools: AgentTool[];
  usage: { requestsMonth: number; successRate: number; avgDurationSec: number; creditsMonth: number };
  recentExecutions: ExecutionRef[];
  knowledgeSources: { name: string; kind: "file" | "repo" | "web" | "connector" | "memory"; detail: string }[];
  /** Resolved by the Model Gateway routing policy for this workspace. */
  models: { capability: CapabilityKey; model: string; provider: ProviderKey }[];
}

export interface Conversation {
  id: string;
  agent: AgentKey;
  title: string;
  preview: string;
  updatedSecondsAgo: number;
  project?: string;
  pinned?: boolean;
}

export interface Attachment {
  name: string;
  kind: "pdf" | "docx" | "xlsx" | "csv" | "md" | "image" | "code";
  sizeKb: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  /** Markdown. */
  content: string;
  createdSecondsAgo: number;
  attachments?: Attachment[];
  /** Model actually used, as reported by the Model Gateway. */
  model?: string;
  executionId?: string;
}

export type StepStatus = "done" | "running" | "waiting" | "pending" | "failed" | "skipped";

export interface PlanStep {
  id: string;
  title: string;
  agent: AgentKey | "orchestrator";
  status: StepStatus;
  durationSec?: number;
  detail?: string;
}

export interface ToolCall {
  id: string;
  tool: string;
  agent: AgentKey;
  input: string;
  status: "ok" | "error" | "running" | "blocked";
  durationMs: number | null;
  sideEffect: SideEffect;
  atMs: number;
}

export interface LogLine {
  atMs: number;
  level: "debug" | "info" | "warn" | "error";
  source: string;
  message: string;
}

export interface Artifact {
  id: string;
  name: string;
  kind: Attachment["kind"];
  sizeKb: number;
  agent: AgentKey;
  createdSecondsAgo: number;
}

export interface ApprovalRequest {
  id: string;
  executionId: string;
  title: string;
  reason: string;
  sideEffect: SideEffect;
  agent: AgentKey;
  status: "pending" | "approved" | "rejected";
  preview?: string;
  requestedSecondsAgo: number;
}

export interface Subtask {
  id: string;
  title: string;
  agent: AgentKey;
  status: StepStatus;
  dependsOn: string[];
  /** null when unknown. */
  progress: number | null;
  /** "orchestrator", or the agent whose handoff created this subtask. */
  origin?: string;
  /** Engine stage text, e.g. "Skipped because research failed." */
  stage?: string;
}

export interface TaskDetail extends TaskRunSummary {
  objective: string;
  project?: string;
  createdBy: string;
  agentVersion: string;
  plan: PlanStep[];
  events: TimelineEvent[];
  toolCalls: ToolCall[];
  logs: LogLine[];
  artifacts: Artifact[];
  approvals: ApprovalRequest[];
  subtasks: Subtask[];
  /** Which controls the execution engine supports for this run. */
  controls: { pause: boolean; resume: boolean; cancel: boolean; retry: boolean };
  /** Final agent output (Markdown) once the run has finished. */
  result?: string | null;
  /** AgentResult status (completed, partial, needs_input, failed) and open questions. */
  resultStatus?: string | null;
  questions?: string[];
  /** Models used, as reported by the Model Gateway ("model · capability"). */
  models?: string[];
  /** True if any model call came from the offline simulator (dev/CI only). */
  simulated?: boolean;
  /** Execution id → agent and subtask key (orchestrated tasks), for attributing live events. */
  executionMap?: Record<string, ExecMeta>;
  /** Next steps an agent proposed that the orchestrator didn't run (policy or budget). */
  suggestions?: { agent: AgentKey; objective: string; reason: string }[];
}

export interface ExecMeta {
  agent: AgentKey | "orchestrator";
  key: string | null;
  status: string;
}

export type ThinkingApproach =
  | "divergent"
  | "convergent"
  | "first_principles"
  | "lateral"
  | "scamper"
  | "six_hats"
  | "analogical"
  | "debate"
  | "premortem";

export type IdeaColumn = "new" | "shortlisted" | "developing" | "parked" | "rejected";

export interface Idea {
  id: string;
  title: string;
  summary: string;
  approach: ThinkingApproach;
  /** Perspective label, e.g. a Six Hats colour or SCAMPER verb. */
  lens?: string;
  tags: string[];
  scores: { impact: number; feasibility: number; novelty: number };
  column: IdeaColumn;
  /** Creative output is speculative unless explicitly verified. */
  verified: false;
}

export type UsageRange = "7d" | "30d" | "90d";

export interface UsageReport {
  range: UsageRange;
  daily: { day: string; tokens: number; credits: number }[];
  byAgent: { agent: AgentKey | "orchestrator"; requests: number; tokens: number; credits: number; successRate: number }[];
  byModel: { model: string; provider: ProviderKey; capability: CapabilityKey; requests: number; tokensIn: number; tokensOut: number; costUsd: number }[];
  byMember: { name: string; role: OrgRole; tasks: number; credits: number }[];
  totals: { requests: number; tokens: number; credits: number; tasks: number };
  /** Plans and invoices arrive with billing (Phase 6); absent from the live API until then. */
  plan?: { name: string; creditsTotal: number; creditsRemaining: number; renewsOn: string; seats: number; seatsUsed: number };
  invoices?: { id: string; period: string; amountUsd: number; status: "paid" | "open" }[];
}

export type OrgRole = "owner" | "admin" | "member" | "viewer";

export interface Member {
  id: string;
  name: string;
  email: string;
  role: OrgRole;
  lastActiveSecondsAgo: number;
  status: "active" | "invited";
}

/* ── Phase 4b contracts (live backend) ─────────────────────── */

/** Raw persisted execution event (SSE `id` = `id`). */
export interface TaskEvent {
  id: number;
  seq: number;
  executionId: string;
  type: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface KnowledgeDoc {
  id: string;
  title: string;
  source: string;
  mime: string | null;
  chars: number;
  chunks: number;
  createdAt: string;
}

export type ConnectionKind = "github" | "webhook" | "smtp" | "gn7t";

export interface Connection {
  id: string;
  kind: ConnectionKind;
  name: string;
  config: Record<string, unknown>;
  secretLast4: string | null;
  status: "active" | "disabled";
  createdAt: string;
  /** Returned once, when the server generated a webhook signing secret. */
  signingSecret?: string | null;
}

export interface MemoryEntry {
  key: string;
  value: string;
  updatedAt: string;
}

export interface RoutingProvider {
  id: string;
  key: ProviderKey;
  name: string;
  kind: string;
  enabled: boolean;
  /** "configured" = a key is stored; health is not measured yet, so we never claim "healthy" in live mode. */
  status: "healthy" | "degraded" | "configured" | "not_configured";
  credentialHint: string | null;
  /** In-house services (GN7T) are reached at an admin-set base URL. */
  baseUrl?: string | null;
  latencyMs: number | null;
  models: { id: string; label: string; capabilities: CapabilityKey[]; priceIn: number | null; priceOut: number | null }[];
}

export interface RoutingRoute {
  capability: CapabilityKey;
  primary: string;
  fallbacks: string[];
  temperature: number;
}

/** Result of asking a provider for its own model list. Imported models start disabled. */
export interface ModelImportResult {
  provider: ProviderKey;
  found: number;
  added: string[];
  alreadyPresent: number;
  note: string;
}

export interface RoutingData {
  providers: RoutingProvider[];
  routes: RoutingRoute[];
}
