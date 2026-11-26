/**
 * AgentFirm frontend ↔ backend contract.
 *
 * Every screen talks to this interface, never to a concrete implementation.
 * Phase 2 wires the mock adapter (src/mocks/adapter.ts); Phase 3 adds the HTTP
 * adapter generated from the FastAPI OpenAPI schema. Selection happens in
 * src/data/api.ts — the only module allowed to import both.
 */
import type {
  AgentKey,
  CapabilityKey,
  AgentProfile,
  AgentSummary,
  ApprovalRequest,
  ChatMessage,
  Connection,
  ConnectionKind,
  Conversation,
  Idea,
  IdeaColumn,
  KnowledgeDoc,
  Member,
  MemoryEntry,
  ModelImportResult,
  ProviderTestResult,
  SearchProviderKey,
  SearchSettings,
  SearchTestResult,
  StopResult,
  RoutingData,
  RoutingRoute,
  TaskEvent,
  TaskDetail,
  TaskRunSummary,
  ThinkingApproach,
  UsageRange,
  UsageReport,
} from "@/lib/types";

/** Incremental output of a streamed reply (maps 1:1 to SSE `token.delta` / `message.completed`). */
export type ReplyChunk =
  | { type: "status"; text: string }
  | { type: "delta"; text: string }
  | { type: "done"; model: string; executionId: string };

import type { components } from "./schema";

type Sch = components["schemas"];
export type BillingCatalog = Sch["Catalog"];
export type BillingAccount = Sch["AccountOut"];
export type BillingPlan = Sch["PlanOut"];
export type InvoiceRow = Sch["InvoiceOut"];
export type LedgerRow = Sch["LedgerOut"];
export type StandingApproval = Sch["StandingOut"];
export type StandingInput = Sch["StandingIn"];
export type AdminPlan = Sch["AdminPlanOut"];
export type AdminPlanInput = Sch["PlanIn"];
export type AdminPack = Sch["AdminPackOut"];
export type AdminPackInput = Sch["PackIn"];
export type AccountRow = Sch["AccountRow"];
export type ToolRow = Sch["ToolRow"];
export type AgentAdminRow = Sch["AgentAdminRow"];
export type BillingEventRow = Sch["BillingEventRow"];

export interface AgentFirmApi {
  /** True for the demo adapter — screens show a "Demo data" marker. */
  readonly isDemo: boolean;

  agents: {
    list(): Promise<AgentSummary[]>;
    profiles(): Promise<AgentProfile[]>;
    get(key: AgentKey): Promise<AgentProfile | null>;
  };

  conversations: {
    list(agent: AgentKey): Promise<Conversation[]>;
    messages(conversationId: string): Promise<ChatMessage[]>;
    streamReply(agent: AgentKey, prompt: string, signal?: AbortSignal): AsyncIterable<ReplyChunk>;
  };

  tasks: {
    list(): Promise<TaskRunSummary[]>;
    get(id: string): Promise<TaskDetail | null>;
    /** Queue a task for one agent; the worker picks it up. Resolves with the task id. */
    /** One agent runs directly; several (or none) are planned and coordinated by the orchestrator. */
    create(input: { agents: AgentKey[]; objective: string; parameters?: Record<string, unknown> }): Promise<{ id: string }>;
    events(id: string): Promise<TaskEvent[]>;
    /** Answer a task's question; a new attempt continues from where it stopped. */
    reply(id: string, message: string): Promise<void>;
    /** Execution control; resolves with the status the engine accepted. */
    control(id: string, action: "pause" | "resume" | "cancel" | "retry"): Promise<TaskRunSummary["status"]>;
    /** Stops anything still running, then deletes the task with its history and files. Cannot be undone. */
    remove(id: string): Promise<void>;
    /** Stops every running/queued task in this workspace, or only one agent's. */
    stopAll(agent?: AgentKey): Promise<StopResult>;
  };

  approvals: {
    pending(): Promise<ApprovalRequest[]>;
    decide(id: string, decision: "approved" | "rejected", note?: string): Promise<ApprovalRequest["status"]>;
  };

  ideas: {
    list(): Promise<Idea[]>;
    generate(objective: string, approach: ThinkingApproach, signal?: AbortSignal): AsyncIterable<Idea>;
    handoff(ideaId: string, agent: AgentKey): Promise<{ taskId: string }>;
    move(ideaId: string, column: IdeaColumn): Promise<void>;
  };

  knowledge: {
    list(): Promise<KnowledgeDoc[]>;
    add(title: string, content: string): Promise<KnowledgeDoc>;
    upload(file: File): Promise<KnowledgeDoc>;
    remove(id: string): Promise<void>;
  };

  integrations: {
    list(): Promise<Connection[]>;
    create(input: { kind: ConnectionKind; name: string; config: Record<string, unknown>; secret?: string }): Promise<Connection>;
    update(id: string, patch: { name?: string; config?: Record<string, unknown>; secret?: string; status?: "active" | "disabled" }): Promise<Connection>;
    remove(id: string): Promise<void>;
  };

  memories: {
    list(): Promise<MemoryEntry[]>;
    put(key: string, value: string): Promise<MemoryEntry>;
  };

  admin: {
    routing(): Promise<RoutingData>;
    saveRoute(route: RoutingRoute): Promise<void>;
    updateProvider(providerId: string, patch: { enabled?: boolean; baseUrl?: string }): Promise<void>;
    setCredential(providerId: string, apiKey: string): Promise<{ last4: string }>;
    /** Sends one tiny real request to the provider so a wrong URL or key shows up here, not in a failed task. */
    testProvider(providerId: string): Promise<ProviderTestResult>;
    /** Fetches the provider's own model list; new models are created disabled for review. */
    importModels(providerId: string): Promise<ModelImportResult>;
    /** Web search used by the research tools (super-admin). */
    search(): Promise<SearchSettings>;
    saveSearch(input: { provider: SearchProviderKey; fallback: SearchProviderKey; geminiModel: string }): Promise<SearchSettings>;
    setBraveKey(apiKey: string): Promise<SearchSettings>;
    clearBraveKey(): Promise<SearchSettings>;
    testSearch(provider: "brave" | "gemini"): Promise<SearchTestResult>;
    updateModel(modelId: string, patch: { enabled?: boolean; label?: string; capabilities?: CapabilityKey[]; priceIn?: number | null; priceOut?: number | null }): Promise<void>;
  };

  /** Plans, credits and Paddle billing for the current workspace (Phase 6). */
  account: {
    catalog(): Promise<BillingCatalog>;
    summary(): Promise<BillingAccount>;
    invoices(): Promise<InvoiceRow[]>;
    invoicePdf(id: string): Promise<{ url: string }>;
    ledger(): Promise<LedgerRow[]>;
    checkout(input: { plan?: string; credit_pack?: string }): Promise<{ checkout_url?: string | null; changed?: boolean; transaction_id?: string | null }>;
    portal(): Promise<{ url: string }>;
    cancel(): Promise<BillingAccount>;
    completeFixtureCheckout(transactionId: string): Promise<{ events: string[] }>;
  };
  standing: {
    list(): Promise<StandingApproval[]>;
    tools(): Promise<Record<string, string[]>>;
    create(input: StandingInput): Promise<StandingApproval>;
    revoke(id: string): Promise<StandingApproval>;
  };
  /** Super-admin platform administration (server-enforced). */
  platform: {
    plans(): Promise<AdminPlan[]>;
    savePlan(key: string, input: AdminPlanInput): Promise<AdminPlan[]>;
    packs(): Promise<AdminPack[]>;
    savePack(key: string, input: AdminPackInput): Promise<AdminPack[]>;
    accounts(): Promise<AccountRow[]>;
    grantCredits(orgId: string, credits: number, note: string): Promise<AccountRow[]>;
    setPlan(orgId: string, plan: string, note: string): Promise<AccountRow[]>;
    tools(): Promise<ToolRow[]>;
    switchTool(key: string, disabled: boolean, reason: string): Promise<ToolRow[]>;
    agents(): Promise<AgentAdminRow[]>;
    setAgentEnabled(key: string, enabled: boolean, reason: string): Promise<AgentAdminRow[]>;
    /** Emergency stop across all workspaces (or one): every agent, or just `agent`. */
    stopAgents(input: { agent?: string; orgId?: string }): Promise<StopResult>;
    rollbackAgent(key: string, version: string, reason: string): Promise<AgentAdminRow[]>;
    billingEvents(): Promise<BillingEventRow[]>;
  };
  usage: {
    report(range: UsageRange): Promise<UsageReport>;
  };

  workspace: {
    members(): Promise<Member[]>;
  };
}
