/**
 * ⚠ DEMONSTRATION DATA — NOT PRODUCTION.
 *
 * Used only by Phase-1 screens until the FastAPI backend + SSE event stream
 * exist (Phase 3–4). Nothing in src/lib/api may import from this folder.
 * Every screen that renders this data shows a visible "Demo data" marker.
 *
 * Progress values here mimic what the backend will emit: they are derived
 * from completed/total plan steps, and are `null` where a plan is not yet known.
 */
import type {
  AgentSummary,
  CapabilityKey,
  ProviderKey,
  TaskRunSummary,
  TimelineEvent,
} from "@/lib/types";

export const DEMO_AGENTS: AgentSummary[] = [
  {
    key: "research",
    name: "Research & Knowledge",
    shortName: "Research",
    description: "Structured research, document analysis and cited reports.",
    status: "working",
    currentTask: "EdTech market scan — English learning, CEE region",
    lastActiveSecondsAgo: 4,
  },
  {
    key: "marketing",
    name: "AI Marketing",
    shortName: "Marketing",
    description: "Strategy, positioning, campaigns, SEO and on-brand content.",
    status: "waiting_approval",
    currentTask: "Publish LinkedIn launch post (needs approval)",
    lastActiveSecondsAgo: 140,
  },
  {
    key: "engineer",
    name: "Project Engineer",
    shortName: "Engineer",
    description: "Architecture, code, reviews, tests and technical documentation.",
    status: "working",
    currentTask: "Refactor billing webhooks + add idempotency tests",
    lastActiveSecondsAgo: 12,
  },
  {
    key: "bi",
    name: "Business Intelligence & Automation",
    shortName: "BI & Automation",
    description: "KPIs, forecasting, opportunity analysis and approved automations.",
    status: "completed",
    currentTask: "Q3 revenue cohort report",
    lastActiveSecondsAgo: 1_380,
  },
  {
    key: "assistant",
    name: "Personal Assistant",
    shortName: "Assistant",
    description: "Scheduling, drafting, discovery — and delegating to specialists.",
    status: "available",
    currentTask: null,
    lastActiveSecondsAgo: 3_900,
  },
  {
    key: "creative",
    name: "Creative & Brainstorming",
    shortName: "Creative",
    description: "Divergent ideation, SCAMPER, Six Hats and critical evaluation.",
    status: "working",
    currentTask: "Name candidates for the tutoring product line",
    lastActiveSecondsAgo: 2,
  },
];

export const DEMO_TASKS: TaskRunSummary[] = [
  {
    id: "tsk_7Q2M",
    executionId: "exe_01JD8K4V9R",
    title: "English-learning market: opportunities & launch strategy",
    agents: ["research", "bi", "creative", "marketing"],
    status: "running",
    progress: 5 / 9,
    stage: "Synthesizing competitor evidence",
    stepsCompleted: 5,
    stepsTotal: 9,
    startedSecondsAgo: 1_122,
  },
  {
    id: "tsk_3K9P",
    executionId: "exe_01JD8M2C1T",
    title: "Refactor billing webhooks + idempotency tests",
    agents: ["engineer"],
    status: "running",
    progress: 3 / 7,
    stage: "Running test suite (pytest)",
    stepsCompleted: 3,
    stepsTotal: 7,
    startedSecondsAgo: 486,
  },
  {
    id: "tsk_8V1X",
    executionId: "exe_01JD8N7H4B",
    title: "Name candidates for the tutoring product line",
    agents: ["creative"],
    status: "running",
    progress: null, // plan not finalised yet → indeterminate
    stage: "Planning — choosing thinking approach",
    stepsCompleted: null,
    stepsTotal: null,
    startedSecondsAgo: 38,
  },
  {
    id: "tsk_2B6R",
    executionId: "exe_01JD8H0Q8Z",
    title: "Publish LinkedIn launch post",
    agents: ["marketing"],
    status: "waiting_approval",
    progress: 4 / 5,
    stage: "Awaiting approval: external publish",
    stepsCompleted: 4,
    stepsTotal: 5,
    startedSecondsAgo: 2_140,
  },
];

/** Scripted replay for the collaboration task — stands in for the SSE stream. */
export const DEMO_TIMELINE: TimelineEvent[] = [
  { seq: 1, kind: "plan", agent: "orchestrator", title: "Execution plan created", detail: "9 steps · 4 agents · 2 parallel branches", atMs: 0 },
  { seq: 2, kind: "subtask", agent: "research", title: "Subtask assigned: market sizing", atMs: 1_800 },
  { seq: 3, kind: "tool_call", agent: "research", title: "web.search", detail: "\"English learning app market CEE 2026\"", atMs: 4_200 },
  { seq: 4, kind: "model_call", agent: "research", title: "Reasoning · gemini-3.8-flash", detail: "Routed via capability: reasoning", atMs: 7_000 },
  { seq: 5, kind: "step_completed", agent: "research", title: "Evidence collected", detail: "23 sources · 6 flagged low-confidence", atMs: 9_600 },
  { seq: 6, kind: "subtask", agent: "bi", title: "Subtask assigned: opportunity scoring", atMs: 11_400 },
  { seq: 7, kind: "tool_call", agent: "bi", title: "gn7t.query", detail: "segment_revenue · read-only", atMs: 13_800 },
  { seq: 8, kind: "artifact", agent: "bi", title: "Artifact: opportunity-matrix.xlsx", atMs: 16_500 },
  { seq: 9, kind: "step_started", agent: "creative", title: "SCAMPER on top 3 opportunities", atMs: 18_400 },
  { seq: 10, kind: "approval", agent: "marketing", title: "Approval required", detail: "Ad budget simulation uses paid API", atMs: 21_000 },
];

export const DEMO_TOKENS_14D: { day: string; tokens: number }[] = [
  { day: "Nov 3", tokens: 182_000 },
  { day: "Nov 4", tokens: 214_000 },
  { day: "Nov 5", tokens: 201_000 },
  { day: "Nov 6", tokens: 268_000 },
  { day: "Nov 7", tokens: 244_000 },
  { day: "Nov 8", tokens: 121_000 },
  { day: "Nov 9", tokens: 96_000 },
  { day: "Nov 10", tokens: 289_000 },
  { day: "Nov 11", tokens: 312_000 },
  { day: "Nov 12", tokens: 297_000 },
  { day: "Nov 13", tokens: 344_000 },
  { day: "Nov 14", tokens: 330_000 },
  { day: "Nov 15", tokens: 158_000 },
  { day: "Nov 16", tokens: 211_000 },
];

export const DEMO_USAGE = {
  aiRequests: 4_812,
  tokensThisMonth: 3_067_000,
  monthlyAllowance: 5_000_000,
  creditsRemaining: 6_420,
  creditsTotal: 10_000,
  activeTasks: 4,
  completedTasks: 1_284,
};

export const DEMO_REQUESTS_BY_AGENT: { agent: string; requests: number }[] = [
  { agent: "Research", requests: 1_420 },
  { agent: "Engineer", requests: 1_106 },
  { agent: "Marketing", requests: 812 },
  { agent: "Creative", requests: 704 },
  { agent: "BI", requests: 511 },
  { agent: "Assistant", requests: 259 },
];

export type ActivityKind = "report" | "file" | "collab" | "research" | "failure";
export const DEMO_ACTIVITY: { id: string; kind: ActivityKind; title: string; meta: string; secondsAgo: number }[] = [
  { id: "a1", kind: "report", title: "Q3 revenue cohort report delivered", meta: "BI & Automation · 14 pages · 6 charts", secondsAgo: 1_380 },
  { id: "a2", kind: "collab", title: "Collaboration started: English-learning market", meta: "Research → BI → Creative → Marketing", secondsAgo: 1_122 },
  { id: "a3", kind: "file", title: "api-spec-billing-v2.yaml generated", meta: "Engineer · 412 lines", secondsAgo: 5_400 },
  { id: "a4", kind: "research", title: "Competitor teardown: 8 tutoring platforms", meta: "Research · 31 cited sources", secondsAgo: 9_800 },
  { id: "a5", kind: "failure", title: "Calendar sync failed — token expired", meta: "Assistant · reconnect Google Calendar", secondsAgo: 14_200 },
];

/* ── Super-admin model routing demo ─────────────────────────── */

export interface DemoProvider {
  key: ProviderKey;
  name: string;
  kind: string;
  status: "healthy" | "degraded" | "not_configured";
  credentialHint: string | null;
  latencyMs: number | null;
  models: { id: string; label: string; capabilities: CapabilityKey[]; priceIn: number | null; priceOut: number | null }[];
}

/**
 * Model ids are placeholders for demo purposes; the real catalog is loaded
 * from the `models` table, maintained by super-admins.
 */
export const DEMO_PROVIDERS: DemoProvider[] = [
  {
    key: "openai",
    name: "OpenAI",
    kind: "External API",
    status: "healthy",
    credentialHint: "sk-…a91F",
    latencyMs: 640,
    models: [
      { id: "openai:gpt-5", label: "GPT-5", capabilities: ["reasoning", "text", "code", "long_context", "vision"], priceIn: 1.25, priceOut: 10 },
      { id: "openai:gpt-5-mini", label: "GPT-5 mini", capabilities: ["text", "summarize", "classify", "code", "creative"], priceIn: 0.25, priceOut: 2 },
      { id: "openai:text-embedding-3-large", label: "text-embedding-3-large", capabilities: ["embeddings"], priceIn: 0.13, priceOut: null },
    ],
  },
  {
    key: "gemini",
    name: "Google Gemini",
    kind: "External API",
    status: "healthy",
    credentialHint: "AIza…7cQe",
    latencyMs: 710,
    models: [
      { id: "gemini:gemini-3.8-flash", label: "Gemini 3.8 Flash", capabilities: ["reasoning", "text", "code", "long_context", "vision"], priceIn: 1.5, priceOut: 7.5 },
      { id: "gemini:gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite", capabilities: ["text", "summarize", "classify", "creative", "vision"], priceIn: 0.3, priceOut: 2.5 },
      { id: "gemini:gemini-embedding", label: "Gemini Embedding", capabilities: ["embeddings"], priceIn: 0.15, priceOut: null },
    ],
  },
  {
    key: "gn7t",
    name: "GN7T",
    kind: "In-house service",
    status: "degraded",
    credentialHint: "gn7t_…41aa",
    latencyMs: 1_480,
    models: [
      { id: "gn7t:gn7t-core", label: "GN7T Core", capabilities: ["text", "summarize", "classify", "reasoning"], priceIn: null, priceOut: null },
      { id: "gn7t:gn7t-embed", label: "GN7T Embed", capabilities: ["embeddings"], priceIn: null, priceOut: null },
    ],
  },
];

export interface DemoRoute {
  capability: CapabilityKey;
  primary: string;
  fallbacks: string[];
  temperature: number;
}

export const DEMO_ROUTES: DemoRoute[] = [
  { capability: "reasoning", primary: "gemini:gemini-3.8-flash", fallbacks: ["openai:gpt-5"], temperature: 0.2 },
  { capability: "text", primary: "openai:gpt-5-mini", fallbacks: ["gemini:gemini-3.5-flash-lite", "gn7t:gn7t-core"], temperature: 0.6 },
  { capability: "code", primary: "openai:gpt-5", fallbacks: ["gemini:gemini-3.8-flash"], temperature: 0.1 },
  { capability: "summarize", primary: "gn7t:gn7t-core", fallbacks: ["gemini:gemini-3.5-flash-lite"], temperature: 0.3 },
  { capability: "classify", primary: "gn7t:gn7t-core", fallbacks: ["openai:gpt-5-mini"], temperature: 0 },
  { capability: "creative", primary: "gemini:gemini-3.5-flash-lite", fallbacks: ["openai:gpt-5-mini"], temperature: 0.95 },
  { capability: "vision", primary: "gemini:gemini-3.8-flash", fallbacks: ["openai:gpt-5"], temperature: 0.2 },
  { capability: "long_context", primary: "gemini:gemini-3.8-flash", fallbacks: [], temperature: 0.2 },
  { capability: "embeddings", primary: "openai:text-embedding-3-large", fallbacks: ["gn7t:gn7t-embed"], temperature: 0 },
];
