/**
 * ⚠ DEMONSTRATION ADAPTER. Implements the real API contract with fixtures and
 * simulated streaming so every Phase-2 screen exercises production code paths.
 */
import type { AgentFirmApi, ReplyChunk } from "@/lib/api/contracts";
import type { AgentProfile, ApprovalRequest, Connection, Idea, KnowledgeDoc, MemoryEntry, UsageRange, UsageReport, TaskRunSummary } from "@/lib/types";
import { DEMO_AGENTS, DEMO_PROVIDERS, DEMO_ROUTES } from "./demo-data";
import {
  CONVERSATIONS,
  IDEAS,
  MEMBERS,
  MESSAGES,
  PROFILES,
  REPLIES,
  TASKS,
  TASK_DETAILS,
  generatedIdeas,
  genericMessages,
} from "./phase2-data";

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

function usageReport(range: UsageRange): UsageReport {
  const days = range === "7d" ? 7 : range === "30d" ? 30 : 90;
  const end = Date.UTC(2026, 10, 16);
  const daily = Array.from({ length: days }, (_, i) => {
    const d = new Date(end - (days - 1 - i) * 86_400_000);
    const weekday = d.getUTCDay();
    const weekend = weekday === 0 || weekday === 6;
    const trend = 1 + i / (days * 2.5);
    const wobble = 0.82 + (((i * 37) % 23) / 23) * 0.36;
    const tokens = Math.round((weekend ? 110_000 : 250_000) * trend * wobble);
    return { day: d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }), tokens, credits: Math.round(tokens / 2070) };
  });
  const scale = days / 30;
  const r = (n: number) => Math.round(n * scale);
  const tokens = daily.reduce((s, d) => s + d.tokens, 0);
  const credits = daily.reduce((s, d) => s + d.credits, 0);
  return {
    range,
    daily,
    byAgent: [
      { agent: "research", requests: r(1420), tokens: Math.round(tokens * 0.31), credits: Math.round(credits * 0.29), successRate: 0.97 },
      { agent: "engineer", requests: r(1106), tokens: Math.round(tokens * 0.27), credits: Math.round(credits * 0.33), successRate: 0.91 },
      { agent: "marketing", requests: r(812), tokens: Math.round(tokens * 0.14), credits: Math.round(credits * 0.13), successRate: 0.95 },
      { agent: "creative", requests: r(704), tokens: Math.round(tokens * 0.11), credits: Math.round(credits * 0.08), successRate: 0.99 },
      { agent: "bi", requests: r(511), tokens: Math.round(tokens * 0.13), credits: Math.round(credits * 0.14), successRate: 0.98 },
      { agent: "assistant", requests: r(259), tokens: Math.round(tokens * 0.04), credits: Math.round(credits * 0.03), successRate: 0.93 },
    ],
    byModel: [
      { model: "gemini-2.5-pro", provider: "gemini", capability: "reasoning", requests: r(1310), tokensIn: Math.round(tokens * 0.24), tokensOut: Math.round(tokens * 0.06), costUsd: 0 },
      { model: "gpt-5", provider: "openai", capability: "code", requests: r(980), tokensIn: Math.round(tokens * 0.18), tokensOut: Math.round(tokens * 0.07), costUsd: 0 },
      { model: "gpt-5-mini", provider: "openai", capability: "text", requests: r(1450), tokensIn: Math.round(tokens * 0.12), tokensOut: Math.round(tokens * 0.05), costUsd: 0 },
      { model: "gemini-2.5-flash", provider: "gemini", capability: "creative", requests: r(690), tokensIn: Math.round(tokens * 0.08), tokensOut: Math.round(tokens * 0.04), costUsd: 0 },
      { model: "gn7t-core", provider: "gn7t", capability: "summarize", requests: r(2120), tokensIn: Math.round(tokens * 0.11), tokensOut: Math.round(tokens * 0.02), costUsd: 0 },
      { model: "text-embedding-3-large", provider: "openai", capability: "embeddings", requests: r(3400), tokensIn: Math.round(tokens * 0.03), tokensOut: 0, costUsd: 0 },
    ].map((m) => {
      const price: Record<string, [number, number]> = {
        "gemini-2.5-pro": [1.25, 10], "gpt-5": [1.25, 10], "gpt-5-mini": [0.25, 2], "gemini-2.5-flash": [0.3, 2.5], "gn7t-core": [0, 0], "text-embedding-3-large": [0.13, 0],
      };
      const [pi, po] = price[m.model];
      return { ...m, provider: m.provider as UsageReport["byModel"][number]["provider"], capability: m.capability as UsageReport["byModel"][number]["capability"], costUsd: Math.round(((m.tokensIn / 1e6) * pi + (m.tokensOut / 1e6) * po) * 100) / 100 };
    }),
    byMember: [
      { name: "Demo User", role: "owner", tasks: r(412), credits: Math.round(credits * 0.46) },
      { name: "Maya Chen", role: "admin", tasks: r(268), credits: Math.round(credits * 0.27) },
      { name: "Daniel Okafor", role: "member", tasks: r(190), credits: Math.round(credits * 0.18) },
      { name: "Sofia Rossi", role: "member", tasks: r(96), credits: Math.round(credits * 0.09) },
    ],
    totals: { requests: r(4812), tokens, credits, tasks: r(966) },
    plan: { name: "Growth", creditsTotal: 10_000, creditsRemaining: 6_420, renewsOn: "Dec 1, 2026", seats: 10, seatsUsed: 6 },
    invoices: [
      { id: "INV-2026-011", period: "Nov 2026", amountUsd: 249, status: "open" },
      { id: "INV-2026-010", period: "Oct 2026", amountUsd: 249, status: "paid" },
      { id: "INV-2026-009", period: "Sep 2026", amountUsd: 199, status: "paid" },
    ],
  };
}

function withModels(p: (typeof PROFILES)[number]): AgentProfile {
  return {
    ...p,
    models: p.modelCapabilities.map((capability) => {
      const id = DEMO_ROUTES.find((r) => r.capability === capability)?.primary ?? "";
      const provider = DEMO_PROVIDERS.find((pr) => pr.models.some((m) => m.id === id));
      const label = provider?.models.find((m) => m.id === id)?.label ?? id;
      return { capability, model: label, provider: provider?.key ?? "openai" };
    }),
  };
}

const approvalState = new Map<string, ApprovalRequest["status"]>();

const DEMO_DOCS: KnowledgeDoc[] = [
  { id: "doc_1", title: "Q2 customer interviews.md", source: "upload", mime: "text/markdown", chars: 18_420, chunks: 16, createdAt: "2026-10-02T09:12:00Z" },
  { id: "doc_2", title: "Brand guidelines.pdf", source: "upload", mime: "application/pdf", chars: 41_380, chunks: 35, createdAt: "2026-09-18T14:40:00Z" },
];
const DEMO_CONNECTIONS: Connection[] = [
  { id: "conn_1", kind: "github", name: "GitHub", config: { repositories: ["acme/billing-service"], default_repository: "acme/billing-service", api_base: "https://api.github.com" }, secretLast4: "7f2c", status: "active", createdAt: "2026-10-12T10:00:00Z" },
];
const DEMO_MEMORIES: MemoryEntry[] = [{ key: "brand_voice", value: "Confident, warm, plain language. No jargon.", updatedAt: "2026-10-20T08:00:00Z" }];

const liveOnly = (): Promise<never> => Promise.reject(new Error("Available with the live API (NEXT_PUBLIC_AGENTFIRM_API=http)."));

export const mockApi: AgentFirmApi = {
  account: {
    catalog: liveOnly,
    summary: liveOnly,
    invoices: liveOnly,
    invoicePdf: liveOnly,
    ledger: liveOnly,
    checkout: liveOnly,
    portal: liveOnly,
    cancel: liveOnly,
    completeFixtureCheckout: liveOnly,
  },
  standing: { list: liveOnly, tools: liveOnly, create: liveOnly, revoke: liveOnly },
  platform: {
    plans: liveOnly,
    savePlan: liveOnly,
    packs: liveOnly,
    savePack: liveOnly,
    accounts: liveOnly,
    grantCredits: liveOnly,
    setPlan: liveOnly,
    tools: liveOnly,
    switchTool: liveOnly,
    agents: liveOnly,
    setAgentEnabled: liveOnly,
    rollbackAgent: liveOnly,
    billingEvents: liveOnly,
  },
  isDemo: true,

  agents: {
    list: async () => DEMO_AGENTS,
    profiles: async () => PROFILES.map(withModels),
    get: async (key) => {
      const p = PROFILES.find((x) => x.key === key);
      return p ? withModels(p) : null;
    },
  },

  conversations: {
    list: async (agent) => CONVERSATIONS.filter((c) => c.agent === agent),
    messages: async (id) => {
      const conv = CONVERSATIONS.find((c) => c.id === id);
      if (!conv) return [];
      return MESSAGES[id] ?? genericMessages(conv);
    },
    async *streamReply(agent, _prompt, signal): AsyncIterable<ReplyChunk> {
      yield { type: "status", text: "Routing via Model Gateway…" };
      await sleep(500, signal);
      yield { type: "status", text: "Planning…" };
      await sleep(500, signal);
      const text = REPLIES[agent] ?? REPLIES.assistant;
      const tokens = text.match(/\S+\s*|\s+/g) ?? [text];
      for (const t of tokens) {
        await sleep(24 + Math.random() * 30, signal);
        yield { type: "delta", text: t };
      }
      const model: Record<string, string> = { research: "gemini-2.5-pro · reasoning", engineer: "gpt-5 · code", creative: "gemini-2.5-flash · creative" };
      yield { type: "done", model: model[agent] ?? "gpt-5-mini · text", executionId: `exe_demo_${Math.random().toString(36).slice(2, 8)}` };
    },
  },

  tasks: {
    list: async () => TASKS,
    get: async (id) => TASK_DETAILS[id] ?? null,
    create: async () => {
      await sleep(300);
      return { id: TASKS[0]?.id ?? "tsk_demo" };
    },
    events: async () => [],
    reply: liveOnly,
    control: async (_id, action) => {
      await sleep(350);
      const next: Record<typeof action, TaskRunSummary["status"]> = { pause: "paused", resume: "running", cancel: "cancelled", retry: "running" };
      return next[action];
    },
  },

  approvals: {
    pending: async () =>
      Object.values(TASK_DETAILS)
        .flatMap((t) => t.approvals)
        .map((a) => ({ ...a, status: approvalState.get(a.id) ?? a.status }))
        .filter((a) => a.status === "pending"),
    decide: async (id, decision) => {
      await sleep(400);
      approvalState.set(id, decision);
      return decision;
    },
  },

  ideas: {
    list: async () => IDEAS,
    async *generate(objective, approach, signal): AsyncIterable<Idea> {
      for (const i of generatedIdeas(approach, objective)) {
        await sleep(650, signal);
        yield i;
      }
    },
    handoff: async () => {
      await sleep(400);
      return { taskId: `tsk_demo_${Math.random().toString(36).slice(2, 6)}` };
    },
    move: async () => {
      await sleep(150);
    },
  },

  knowledge: {
    list: async () => [...DEMO_DOCS],
    add: async (title, content) => {
      const doc = { id: `doc_${DEMO_DOCS.length + 1}`, title, source: "text", mime: "text/markdown", chars: content.length, chunks: Math.max(1, Math.ceil(content.length / 1200)), createdAt: new Date().toISOString() };
      DEMO_DOCS.unshift(doc);
      return doc;
    },
    upload: async (file) => {
      const doc = { id: `doc_${DEMO_DOCS.length + 1}`, title: file.name, source: "upload", mime: file.type || null, chars: file.size, chunks: Math.max(1, Math.ceil(file.size / 1200)), createdAt: new Date().toISOString() };
      DEMO_DOCS.unshift(doc);
      return doc;
    },
    remove: async (id) => {
      const i = DEMO_DOCS.findIndex((d) => d.id === id);
      if (i >= 0) DEMO_DOCS.splice(i, 1);
    },
  },

  integrations: {
    list: async () => [...DEMO_CONNECTIONS],
    create: async (input) => {
      const c = { id: `conn_${DEMO_CONNECTIONS.length + 1}`, kind: input.kind, name: input.name, config: input.config, secretLast4: input.secret ? input.secret.slice(-4) : null, status: "active" as const, createdAt: new Date().toISOString(), signingSecret: input.kind === "webhook" && !input.secret ? "whsec_demo_not_a_real_secret" : null };
      DEMO_CONNECTIONS.push({ ...c, signingSecret: null });
      return c;
    },
    update: async (id, patch) => {
      const c = DEMO_CONNECTIONS.find((x) => x.id === id);
      if (!c) throw new Error("not found");
      Object.assign(c, { ...(patch.name ? { name: patch.name } : {}), ...(patch.status ? { status: patch.status } : {}), ...(patch.secret ? { secretLast4: patch.secret.slice(-4) } : {}) });
      return { ...c };
    },
    remove: async (id) => {
      const i = DEMO_CONNECTIONS.findIndex((c) => c.id === id);
      if (i >= 0) DEMO_CONNECTIONS.splice(i, 1);
    },
  },

  memories: {
    list: async () => [...DEMO_MEMORIES],
    put: async (key, value) => {
      const m = { key, value, updatedAt: new Date().toISOString() };
      const i = DEMO_MEMORIES.findIndex((x) => x.key === key);
      if (i >= 0) DEMO_MEMORIES[i] = m;
      else DEMO_MEMORIES.push(m);
      return m;
    },
  },

  admin: {
    routing: async () => ({
      providers: DEMO_PROVIDERS.map((p) => ({ ...p, id: p.key, enabled: p.key !== "tea800" })),
      routes: DEMO_ROUTES.map((r) => ({ ...r })),
    }),
    saveRoute: async () => {
      await sleep(250);
    },
    updateProvider: async () => {
      await sleep(150);
    },
    setCredential: async (_id, key) => {
      await sleep(250);
      return { last4: key.slice(-4) };
    },
  },

  usage: { report: async (range) => usageReport(range) },
  workspace: { members: async () => MEMBERS },
};
