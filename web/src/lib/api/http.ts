/**
 * HTTP adapter: the live backend through the Next.js BFF (`/api/v1/*` → FastAPI `/v1/*`).
 * The BFF attaches the access token from the httpOnly cookie and refreshes it; the browser
 * never sees a token. Response shapes come from the generated OpenAPI types (schema.d.ts)
 * and are mapped to the UI types here — the only place that knows both.
 *
 * Client-side only: relative `/api/v1` URLs and cookies need a browser. Pages load live data
 * through `components/live/*` (see ADR 0004).
 */
import type { AgentFirmApi, ReplyChunk } from "./contracts";
import type { components } from "./schema";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { deriveTask, outcomeStep } from "@/lib/events/derive";
import type {
  AgentKey,
  AgentProfile,
  AgentSummary,
  ApprovalRequest,
  Artifact,
  CapabilityKey,
  Connection,
  ExecMeta,
  ExecutionStatus,
  Idea,
  KnowledgeDoc,
  Member,
  ProviderKey,
  RoutingData,
  SideEffect,
  TaskDetail,
  TaskEvent,
  TaskRunSummary,
  ThinkingApproach,
  UsageReport,
} from "@/lib/types";

type S = components["schemas"];
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined && !(body instanceof FormData)) headers["content-type"] = "application/json";
  if (method === "POST") headers["idempotency-key"] = crypto.randomUUID();
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers,
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const p = (await res.json()) as { detail?: unknown };
      detail = typeof p.detail === "string" ? p.detail : JSON.stringify(p.detail ?? p);
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
const get = <T>(path: string) => call<T>("GET", path);

const secondsAgo = (iso: string | null | undefined) => (iso ? Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000)) : 0);
const asAgent = (k: string): AgentKey => (k in AGENT_IDENTITIES ? (k as AgentKey) : "assistant");
const ARTIFACT_KIND: Record<string, Artifact["kind"]> = { md: "md", json: "code", csv: "csv", svg: "image", diff: "code", txt: "md", pdf: "pdf" };

/* ── mappers ─────────────────────────────────────────────────────────────── */

function root(t: S["TaskOut"]): S["ExecutionOut"] | undefined {
  return t.executions.find((e) => !e.parent_execution_id) ?? t.executions[0];
}

export function toSummary(t: S["TaskOut"]): TaskRunSummary {
  const ex = root(t);
  const orchestrated = ex?.kind === "orchestrator";
  return {
    id: t.id,
    executionId: ex?.id ?? "",
    title: t.title,
    // An orchestrated task's agents are its subtasks' agents (none until the plan exists).
    agents: [...new Set(t.executions.filter((e) => e.kind !== "orchestrator" && (!orchestrated || e.parent_execution_id === ex?.id)).map((e) => asAgent(e.agent)))],
    status: t.status as ExecutionStatus, // the API maps orchestrator-internal states (waiting for subtasks) to task states
    orchestrated,
    progress: ex?.progress ?? null,
    stage: ex?.stage ?? "",
    stepsCompleted: ex?.steps_total ? ex.steps_completed : null,
    stepsTotal: ex?.steps_total ?? null,
    startedSecondsAgo: secondsAgo(ex?.started_at ?? ex?.queued_at ?? t.created_at),
  };
}

function toApproval(a: S["ApprovalOut"]): ApprovalRequest {
  return {
    id: a.id,
    executionId: a.execution_id,
    title: a.title,
    reason: a.reason,
    sideEffect: a.side_effect as SideEffect,
    agent: asAgent(a.agent),
    status: a.status === "approved" || a.status === "rejected" ? a.status : "pending",
    preview: a.preview ?? undefined,
    requestedSecondsAgo: secondsAgo(a.created_at),
  };
}

export function toEvent(e: S["EventOut"]): TaskEvent {
  return { id: e.id, seq: e.seq, executionId: e.execution_id, type: e.type, payload: e.payload, createdAt: e.created_at };
}

export function toDetail(t: S["TaskDetailOut"], events: TaskEvent[]): TaskDetail {
  const summary = toSummary(t);
  const ex = root(t);
  const agent = summary.agents[0] ?? "assistant";
  const executionMap: Record<string, ExecMeta> = Object.fromEntries(
    t.executions.map((e) => [e.id, { agent: e.kind === "orchestrator" ? "orchestrator" : asAgent(e.agent), key: e.subtask_key ?? null, status: e.status }]),
  );
  const d = deriveTask(events, ex?.id ?? "", executionMap);
  const result = (ex?.result ?? null) as { summary?: string; handoffs?: { to_agent: string; objective: string; reason: string }[] } | null;
  const children = t.executions.filter((e) => ex && e.parent_execution_id === ex.id && e.kind !== "orchestrator");
  const idByKey = new Map(children.map((e) => [e.subtask_key ?? "", e.id]));
  const agentOf = new Map(t.executions.map((e) => [e.id, asAgent(e.agent)]));
  const terminal = ["completed", "failed", "cancelled"].includes(summary.status);
  return {
    ...summary,
    progress: summary.progress ?? d.progress,
    objective: t.objective,
    createdBy: t.created_by,
    agentVersion: summary.orchestrated ? children.map((e) => `${e.agent} ${e.agent_version}`).join(" · ") || "planning" : (ex?.agent_version ?? ""),
    plan: d.plan,
    events: d.timeline,
    toolCalls: d.toolCalls,
    logs: d.logs,
    artifacts: t.artifacts.map((a) => ({ id: a.id, name: a.name, kind: ARTIFACT_KIND[a.kind] ?? "md", sizeKb: Math.max(1, Math.round(a.size_bytes / 1024)), agent: agentOf.get(a.execution_id) ?? agent, createdSecondsAgo: secondsAgo(a.created_at) })),
    approvals: t.approvals.map(toApproval),
    subtasks: children.map((e) => {
      const r = (e.result ?? null) as { status?: string } | null;
      return {
        id: e.id,
        title: e.objective ?? e.stage ?? e.agent,
        agent: asAgent(e.agent),
        status: outcomeStep(e.status === "completed" ? (r?.status ?? "completed") : e.status),
        dependsOn: (e.depends_on ?? []).map((k) => idByKey.get(k) ?? "").filter(Boolean),
        progress: e.progress ?? null,
        origin: e.origin ?? undefined,
        stage: e.stage ?? undefined,
      };
    }),
    executionMap,
    suggestions: (result?.handoffs ?? []).map((h) => ({ agent: asAgent(h.to_agent), objective: h.objective, reason: h.reason })),
    controls: { pause: !terminal, resume: summary.status === "paused", cancel: !terminal, retry: summary.status === "failed" || summary.status === "completed" },
    result: result?.summary ?? null,
    resultStatus: (result as { status?: string } | null)?.status ?? null,
    questions: (result as { questions?: string[] } | null)?.questions ?? [],
    models: d.models,
    simulated: d.simulated,
  };
}

function toAgentSummary(a: S["AgentOut"]): AgentSummary {
  const id = AGENT_IDENTITIES[asAgent(a.key)];
  return { key: asAgent(a.key), name: a.name || id.name, shortName: id.shortName, description: a.description || id.description, status: "available", currentTask: null, lastActiveSecondsAgo: 0 };
}

function toProfile(a: S["AgentOut"]): AgentProfile {
  const m = a.manifest as { mission?: string; capabilities?: string[]; models?: { capabilities?: CapabilityKey[] }; knowledge?: { sources?: string[] } };
  const recent = a.recent ?? [];
  const running = recent.find((r) => r.status === "running" || r.status === "waiting_approval");
  return {
    ...toAgentSummary(a),
    status: running ? (running.status === "waiting_approval" ? "waiting_approval" : "working") : "available",
    currentTask: running?.title ?? null,
    lastActiveSecondsAgo: secondsAgo(recent[0]?.queued_at),
    version: a.version,
    mission: m.mission ?? a.description,
    capabilities: m.capabilities ?? [],
    modelCapabilities: m.models?.capabilities ?? [],
    tools: (a.tools ?? []).map((t) => ({ key: t.key, label: t.description, sideEffect: t.side_effect as SideEffect, approval: t.approval as "auto" | "require_approval" | "deny" })),
    usage: {
      requestsMonth: a.usage?.runs_30d ?? 0,
      successRate: a.usage?.success_rate ?? 0,
      avgDurationSec: a.usage?.avg_duration_s ?? 0,
      creditsMonth: a.usage?.credits_30d ?? 0,
    },
    recentExecutions: recent.map((r) => ({
      id: r.execution_id,
      taskId: r.task_id,
      title: r.title,
      status: r.status as ExecutionStatus,
      durationSec: r.finished_at ? Math.round((Date.parse(r.finished_at) - Date.parse(r.queued_at)) / 1000) : 0,
      finishedSecondsAgo: secondsAgo(r.finished_at ?? r.queued_at),
    })),
    knowledgeSources: [{ name: "Knowledge & Files", kind: "file", detail: "Workspace documents (keyword search)" }],
    models: (a.models ?? []).filter((x) => x.model).map((x) => ({ capability: x.capability as CapabilityKey, model: x.model ?? "", provider: (x.provider ?? "openai") as ProviderKey })),
  };
}

function toIdea(i: S["IdeaOut"]): Idea {
  const sc = (i.scores ?? {}) as Record<string, number>;
  return {
    id: i.id,
    title: i.title,
    summary: i.summary,
    approach: i.approach as ThinkingApproach,
    lens: i.lens ?? undefined,
    tags: i.tags,
    scores: { impact: sc.impact ?? 0, feasibility: sc.feasibility ?? 0, novelty: sc.novelty ?? 0 },
    column: i.column,
    verified: false,
  };
}

const toDoc = (d: S["DocumentOut"]): KnowledgeDoc => ({ id: d.id, title: d.title, source: d.source, mime: d.mime, chars: d.chars, chunks: d.chunks, createdAt: d.created_at });
const toConnection = (c: S["ConnectionOut"]): Connection => ({
  id: c.id,
  kind: c.kind,
  name: c.name,
  config: c.config,
  secretLast4: c.secret_last4,
  status: c.status === "disabled" ? "disabled" : "active",
  createdAt: c.created_at,
  signingSecret: c.signing_secret ?? null,
});

function toUsage(u: S["UsageReport"], range: UsageReport["range"]): UsageReport {
  return {
    range,
    daily: u.daily,
    byAgent: u.by_agent.map((a) => ({ agent: a.agent === "orchestrator" ? ("orchestrator" as const) : asAgent(a.agent), requests: a.requests, tokens: a.tokens, credits: a.credits, successRate: 0 })),
    byModel: u.by_model.map((m) => ({ model: m.model, provider: m.provider as ProviderKey, capability: m.capability as CapabilityKey, requests: m.requests, tokensIn: m.tokens_in, tokensOut: m.tokens_out, costUsd: Number(m.cost_usd) })),
    byMember: u.by_member.map((m) => ({ name: m.name, role: m.role as Member["role"], tasks: m.requests, credits: m.credits })),
    totals: { requests: u.totals.requests ?? 0, tokens: u.totals.tokens ?? 0, credits: u.totals.credits ?? 0, tasks: u.totals.tasks ?? 0 },
  };
}

/* ── streaming ───────────────────────────────────────────────────────────── */

/** Read a task's SSE stream (GET; fetch-based so it can be aborted and parsed incrementally). */
export async function* taskStream(taskId: string, signal?: AbortSignal, afterId = 0): AsyncIterable<TaskEvent | { end: string }> {
  const res = await fetch(`${BASE}/tasks/${taskId}/stream?after_id=${afterId}`, { credentials: "include", headers: { accept: "text/event-stream" }, signal });
  if (!res.ok || !res.body) throw new ApiError(res.status, `stream failed (${res.status})`);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const type = frame.match(/^event: (.+)$/m)?.[1];
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("\n");
      if (!data) continue;
      if (type === "end") {
        yield { end: (JSON.parse(data) as { status: string }).status };
        return;
      }
      yield toEvent(JSON.parse(data) as S["EventOut"]);
    }
  }
}

async function createTask(agents: AgentKey[], objective: string, parameters: Record<string, unknown> = {}) {
  const t = await call<S["TaskOut"]>("POST", "/tasks", { objective, agents, parameters });
  return t.id;
}

/** Follow a task until it ends or waits for approval; the stream reconnects with the last id. */
async function* follow(taskId: string, signal?: AbortSignal): AsyncIterable<TaskEvent> {
  let after = 0;
  for (let attempt = 0; attempt < 30; attempt++) {
    let ended = false;
    for await (const e of taskStream(taskId, signal, after)) {
      if ("end" in e) {
        ended = true;
        break;
      }
      after = e.id;
      yield e;
      if (e.type === "execution.status" && e.payload.status === "waiting_approval") return;
    }
    if (ended || signal?.aborted) return;
  }
}

/* ── adapter ─────────────────────────────────────────────────────────────── */

const enc = encodeURIComponent;

export const httpApi: AgentFirmApi = {
  account: {
    catalog: () => call("GET", "/billing/catalog"),
    summary: () => call("GET", "/billing/account"),
    invoices: () => call("GET", "/billing/invoices"),
    invoicePdf: (id) => call("GET", `/billing/invoices/${enc(id)}/pdf`),
    ledger: () => call("GET", "/billing/ledger"),
    checkout: (input) => call("POST", "/billing/checkout", input),
    portal: () => call("POST", "/billing/portal", {}),
    cancel: () => call("POST", "/billing/cancel", {}),
    completeFixtureCheckout: (txn) => call("POST", `/billing/fixture/checkout/${enc(txn)}/complete`, {}),
  },
  standing: {
    list: () => call("GET", "/standing-approvals"),
    tools: () => call("GET", "/standing-approvals/tools"),
    create: (input) => call("POST", "/standing-approvals", input),
    revoke: (id) => call("POST", `/standing-approvals/${enc(id)}/revoke`, {}),
  },
  platform: {
    plans: () => call("GET", "/admin/plans"),
    savePlan: (key, input) => call("PUT", `/admin/plans/${enc(key)}`, input),
    packs: () => call("GET", "/admin/credit-packs"),
    savePack: (key, input) => call("PUT", `/admin/credit-packs/${enc(key)}`, input),
    accounts: () => call("GET", "/admin/accounts"),
    grantCredits: (orgId, credits, note) => call("POST", `/admin/accounts/${enc(orgId)}/credits`, { credits, note }),
    setPlan: (orgId, plan, note) => call("PUT", `/admin/accounts/${enc(orgId)}/plan`, { plan, note }),
    tools: () => call("GET", "/admin/tools"),
    switchTool: (key, disabled, reason) => call("PUT", `/admin/tools/${enc(key)}`, { disabled, reason }),
    agents: () => call("GET", "/admin/agents"),
    setAgentEnabled: (key, enabled, reason) => call("PATCH", `/admin/agents/${enc(key)}`, { enabled, reason }),
    rollbackAgent: (key, version, reason) => call("POST", `/admin/agents/${enc(key)}/rollback`, { version, reason }),
    billingEvents: () => call("GET", "/admin/billing-events"),
  },
  isDemo: false,
  agents: {
    list: async () => (await get<S["AgentOut"][]>("/agents")).map(toAgentSummary),
    profiles: async () => {
      const list = await get<S["AgentOut"][]>("/agents");
      return Promise.all(list.map(async (a) => toProfile(await get<S["AgentOut"]>(`/agents/${a.key}`))));
    },
    get: async (key) => {
      try {
        return toProfile(await get<S["AgentOut"]>(`/agents/${key}`));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  },
  conversations: {
    // Conversations become task threads in Phase 5; until then each message is a task.
    list: async () => [],
    messages: async () => [],
    async *streamReply(agent, prompt, signal): AsyncIterable<ReplyChunk> {
      const id = await createTask([agent], prompt);
      yield { type: "status", text: "Queued — waiting for a worker…" };
      const titles = new Map<string, string>();
      let model = "";
      let executionId = "";
      for await (const e of follow(id, signal)) {
        executionId = e.executionId;
        if (e.type === "plan.created") for (const s of (e.payload.steps as { key: string; title: string }[]) ?? []) titles.set(s.key, s.title);
        if (e.type === "step.started") yield { type: "status", text: `${titles.get(String(e.payload.step)) ?? String(e.payload.step)}…` };
        if (e.type === "model.called") model = `${String(e.payload.model)} · ${String(e.payload.capability)}${e.payload.simulated ? " (simulated)" : ""}`;
        if (e.type === "approval.requested") yield { type: "status", text: `Waiting for approval: ${String(e.payload.title)}` };
      }
      const detail = await get<S["TaskDetailOut"]>(`/tasks/${id}`);
      const ex = root(detail);
      const result = (ex?.result ?? {}) as { summary?: string; error?: { message?: string } };
      const text =
        result.summary ??
        (ex?.status === "waiting_approval" ? `This needs approval before I continue — see [the run](/tasks/${id}).` : (result.error?.message ?? `Finished with status ${ex?.status}. [Open the run](/tasks/${id}).`));
      yield { type: "delta", text };
      yield { type: "done", model: model || "—", executionId: executionId || ex?.id || "" };
    },
  },
  tasks: {
    list: async () => (await get<S["TaskOut"][]>("/tasks")).map(toSummary),
    get: async (id) => {
      try {
        const [t, ev] = await Promise.all([get<S["TaskDetailOut"]>(`/tasks/${id}`), get<S["EventOut"][]>(`/tasks/${id}/events`)]);
        return toDetail(t, ev.map(toEvent));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    create: async ({ agents, objective, parameters }) => ({ id: await createTask(agents, objective, parameters) }),
    events: async (id) => (await get<S["EventOut"][]>(`/tasks/${id}/events`)).map(toEvent),
    reply: async (id, message) => {
      await call("POST", `/tasks/${id}/reply`, { message });
    },
    control: async (id, action) => {
      const t = await call<S["TaskOut"]>("POST", `/tasks/${id}/${action}`);
      return toSummary(t).status;
    },
  },
  approvals: {
    pending: async () => (await get<S["ApprovalOut"][]>("/approvals?status=pending")).map(toApproval),
    decide: async (id, decision, note) => toApproval(await call<S["ApprovalOut"]>("POST", `/approvals/${id}/decision`, { decision, note })).status,
  },
  ideas: {
    list: async () => (await get<S["IdeaOut"][]>("/ideas")).filter((i) => i.column !== "rejected").map(toIdea),
    async *generate(objective, approach, signal) {
      const id = await createTask(["creative"], objective, { approach, intent: approach === "six_hats" || approach === "scamper" || approach === "premortem" || approach === "debate" ? "problem_solving" : "ideate" });
      let executionId = "";
      for await (const e of follow(id, signal)) executionId = e.executionId;
      const ideas = await get<S["IdeaOut"][]>("/ideas");
      for (const i of ideas.filter((x) => x.execution_id === executionId)) yield toIdea(i);
    },
    handoff: async (ideaId, agent) => {
      const idea = (await get<S["IdeaOut"][]>("/ideas")).find((i) => i.id === ideaId);
      const objective = idea ? `Take this idea forward: "${idea.title}" — ${idea.summary}` : `Take idea ${ideaId} forward.`;
      await call("PATCH", `/ideas/${ideaId}`, { column: "developing" });
      return { taskId: await createTask([agent], objective) };
    },
    move: async (ideaId, column) => {
      await call("PATCH", `/ideas/${ideaId}`, { column });
    },
  },
  knowledge: {
    list: async () => (await get<S["DocumentOut"][]>("/knowledge/documents")).map(toDoc),
    add: async (title, content) => toDoc(await call<S["DocumentOut"]>("POST", "/knowledge/documents", { title, content })),
    upload: async (file) => {
      const form = new FormData();
      form.append("file", file);
      return toDoc(await call<S["DocumentOut"]>("POST", "/knowledge/documents/upload", form));
    },
    remove: async (id) => call("DELETE", `/knowledge/documents/${id}`),
  },
  integrations: {
    list: async () => (await get<S["ConnectionOut"][]>("/integrations/connections")).map(toConnection),
    create: async (input) => toConnection(await call<S["ConnectionOut"]>("POST", "/integrations/connections", input)),
    update: async (id, patch) => toConnection(await call<S["ConnectionOut"]>("PATCH", `/integrations/connections/${id}`, patch)),
    remove: async (id) => call("DELETE", `/integrations/connections/${id}`),
  },
  memories: {
    list: async () => (await get<S["MemoryOut"][]>("/memories")).map((m) => ({ key: m.key, value: m.value, updatedAt: m.updated_at })),
    put: async (key, value) => {
      const m = await call<S["MemoryOut"]>("PUT", `/memories/${key}`, { value });
      return { key: m.key, value: m.value, updatedAt: m.updated_at };
    },
  },
  admin: {
    routing: async (): Promise<RoutingData> => {
      const [providers, models, routes] = await Promise.all([get<S["ProviderOut"][]>("/admin/providers"), get<S["ModelOut"][]>("/admin/models"), get<S["RouteOut"][]>("/admin/routes")]);
      return {
        providers: providers.map((p) => ({
          id: p.id,
          key: p.key as ProviderKey,
          name: p.name,
          kind: p.kind,
          enabled: p.enabled,
          // External APIs need a key; in-house services (GN7T, Tea-800) need a base URL.
          status: p.credential_last4 || (p.kind !== "External API" && p.base_url) ? "configured" : "not_configured",
          credentialHint: p.credential_last4 ? `••••${p.credential_last4}` : null,
          baseUrl: p.base_url,
          latencyMs: null,
          models: models
            .filter((m) => m.provider === p.key)
            .map((m) => ({ id: m.id, label: m.label, capabilities: m.capabilities as CapabilityKey[], priceIn: m.price_in_per_1m ? Number(m.price_in_per_1m) : null, priceOut: m.price_out_per_1m ? Number(m.price_out_per_1m) : null })),
        })),
        routes: routes
          .filter((r) => r.primary)
          .map((r) => ({ capability: r.capability as CapabilityKey, primary: r.primary?.id ?? "", fallbacks: r.fallbacks.map((f) => f.id), temperature: Number((r.params as { temperature?: number }).temperature ?? 0.3) })),
      };
    },
    saveRoute: async (r) => {
      await call("PUT", `/admin/routes/${r.capability}`, { primary: r.primary, fallbacks: r.fallbacks, params: { temperature: r.temperature } });
    },
    updateProvider: async (id, patch) => {
      await call("PATCH", `/admin/providers/${id}`, { enabled: patch.enabled, base_url: patch.baseUrl });
    },
    setCredential: async (id, apiKey) => {
      const p = await call<S["ProviderOut"]>("PUT", `/admin/providers/${id}/credential`, { api_key: apiKey });
      return { last4: p.credential_last4 ?? "" };
    },
  },
  usage: { report: async (range) => toUsage(await get<S["UsageReport"]>(`/usage?range=${range}`), range) },
  workspace: {
    members: async () =>
      (await get<S["MemberOut"][]>("/members")).map((m) => ({ id: m.id, name: m.name, email: m.email, role: m.role, lastActiveSecondsAgo: secondsAgo(m.joined_at), status: m.status === "invited" ? "invited" : "active" })),
  },
};
