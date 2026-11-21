/**
 * Derive what the task screens show (plan, timeline, tool calls, logs, progress) from the
 * persisted execution events — the same events the SSE stream delivers. Pure and
 * deterministic: nothing here invents progress; it only reflects what the engine recorded.
 */
import { agentShortName } from "@/lib/agents";
import type { AgentKey, ExecMeta, ExecutionStatus, LogLine, PlanStep, SideEffect, StepStatus, TaskEvent, TimelineEvent, ToolCall } from "@/lib/types";

export interface DerivedExecution {
  plan: PlanStep[];
  timeline: TimelineEvent[];
  toolCalls: ToolCall[];
  logs: LogLine[];
  /** completed weight ÷ total weight, or null until a plan exists. */
  progress: number | null;
  stage: string | null;
  status: ExecutionStatus | null;
  stepsCompleted: number;
  stepsTotal: number | null;
  models: string[];
  simulated: boolean;
}

const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Subtask outcome (AgentResult status or execution status) → plan step status. */
export function outcomeStep(status: string): StepStatus {
  if (status === "completed" || status === "partial") return "done";
  if (status === "failed") return "failed";
  if (status === "skipped" || status === "cancelled") return "skipped";
  if (status === "needs_input" || status === "waiting_approval") return "waiting";
  if (status === "running") return "running";
  return "pending";
}

export function deriveExecution(events: TaskEvent[], agent: AgentKey | "orchestrator", opts: { t0?: number } = {}): DerivedExecution {
  const ordered = [...events].sort((a, b) => a.id - b.id);
  const t0 = opts.t0 ?? (ordered.length ? Date.parse(ordered[0].createdAt) : 0);
  const at = (e: TaskEvent) => Math.max(0, Date.parse(e.createdAt) - t0);

  let plan: PlanStep[] = [];
  const started = new Map<string, number>();
  const timeline: TimelineEvent[] = [];
  const calls = new Map<string, ToolCall>();
  const logs: LogLine[] = [];
  const models = new Set<string>();
  let progress: number | null = null;
  let status: ExecutionStatus | null = null;
  let simulated = false;

  const setStep = (key: string, patch: Partial<PlanStep>) => {
    plan = plan.map((s) => (s.id === key ? { ...s, ...patch } : s));
  };

  for (const e of ordered) {
    const p = e.payload;
    switch (e.type) {
      case "plan.created": {
        const steps = Array.isArray(p.steps) ? (p.steps as Record<string, unknown>[]) : [];
        plan = steps.map((s) => ({ id: str(s.key), title: str(s.title, str(s.key)), agent: (str(s.agent) || agent) as PlanStep["agent"], status: "pending" as StepStatus }));
        progress = plan.length ? 0 : null;
        if (p.kind === "orchestration") {
          timeline.push({ seq: e.id, kind: "plan", agent, title: `Plan: ${plan.length} subtask${plan.length === 1 ? "" : "s"} across ${new Set(plan.map((s) => s.agent)).size} agent(s)`, detail: str(p.rationale).slice(0, 200), atMs: at(e) });
        } else {
          timeline.push({ seq: e.id, kind: "plan", agent, title: `Plan: ${str(p.workflow).replace(/_/g, " ")}`, detail: `${plan.length} steps · intent ${str(p.intent)} (${Math.round((num(p.confidence) ?? 0) * 100)}%)`, atMs: at(e) });
        }
        break;
      }
      case "subtask.spawned": {
        const key = str(p.key);
        const who = str(p.agent) as PlanStep["agent"];
        if (!plan.some((s) => s.id === key)) plan = [...plan, { id: key, title: `${agentShortName(who)}: ${str(p.objective).slice(0, 120)}`, agent: who, status: "pending" }];
        const via = str(p.origin) && str(p.origin) !== "orchestrator" ? ` · handed off by ${agentShortName(str(p.origin))}` : "";
        timeline.push({ seq: e.id, kind: "subtask", agent, title: `Subtask for ${agentShortName(who)}`, detail: str(p.objective).slice(0, 160) + via, atMs: at(e) });
        break;
      }
      case "subtask.completed": {
        const st = str(p.result_status, str(p.status));
        setStep(str(p.key), { status: outcomeStep(st) });
        timeline.push({ seq: e.id, kind: "subtask", agent, title: `${agentShortName(str(p.agent))} finished: ${st.replace(/_/g, " ")}`, atMs: at(e) });
        break;
      }
      case "handoff": {
        const from = agentShortName(str(p.from_agent));
        const to = agentShortName(str(p.to_agent));
        timeline.push({
          seq: e.id,
          kind: "subtask",
          agent,
          title: p.accepted ? `Handoff: ${from} → ${to}` : `Handoff not run: ${from} → ${to}`,
          detail: p.accepted ? (p.kind === "delegation" ? str(p.objective).slice(0, 160) : "Results passed on as input data") : str(p.declined_because),
          atMs: at(e),
        });
        break;
      }
      case "step.started": {
        const key = str(p.step);
        const again = started.has(key); // a step re-entered after an approval, a pause or a crash
        started.set(key, at(e));
        setStep(key, { status: "running" });
        const title = plan.find((s) => s.id === key)?.title ?? key;
        timeline.push({ seq: e.id, kind: "step_started", agent, title: again ? `${title} (resumed)` : title, atMs: at(e) });
        break;
      }
      case "step.completed": {
        const key = str(p.step);
        const dur = started.has(key) ? Math.round((at(e) - (started.get(key) ?? 0)) / 1000) : undefined;
        setStep(key, { status: p.skipped ? "skipped" : "done", durationSec: dur });
        const title = plan.find((s) => s.id === key)?.title ?? key;
        timeline.push({ seq: e.id, kind: "step_completed", agent, title: p.skipped ? `${title} (skipped)` : title, atMs: at(e) });
        break;
      }
      case "step.failed": {
        const err = (p.error ?? {}) as Record<string, unknown>;
        setStep(str(p.step), { status: "failed", detail: str(err.message) });
        logs.push({ atMs: at(e), level: "error", source: str(p.step, "engine"), message: str(err.message) });
        break;
      }
      case "tool.called": {
        const id = str(p.call_id, String(e.id));
        calls.set(id, { id, tool: str(p.tool), agent: agent as AgentKey, input: str(p.input_summary), status: "running", durationMs: null, sideEffect: str(p.side_effect, "none") as SideEffect, atMs: at(e) });
        timeline.push({ seq: e.id, kind: "tool_call", agent, title: str(p.tool), detail: str(p.input_summary).slice(0, 160), atMs: at(e) });
        break;
      }
      case "tool.result": {
        const c = calls.get(str(p.call_id));
        if (c) {
          const s = str(p.status);
          calls.set(c.id, { ...c, status: s === "ok" ? "ok" : s === "blocked" ? "blocked" : "error", durationMs: num(p.duration_ms) });
        }
        break;
      }
      case "model.called": {
        const label = `${str(p.model)} · ${str(p.capability)}`;
        models.add(label);
        simulated ||= Boolean(p.simulated);
        timeline.push({ seq: e.id, kind: "model_call", agent, title: label + (p.simulated ? " (simulated)" : ""), detail: `${num(p.tokens_in) ?? 0} → ${num(p.tokens_out) ?? 0} tokens`, atMs: at(e) });
        break;
      }
      case "approval.requested":
        setStep(plan.find((s) => s.status === "running")?.id ?? "", { status: "waiting" });
        timeline.push({ seq: e.id, kind: "approval", agent, title: `Approval requested: ${str(p.title)}`, detail: str(p.tool), atMs: at(e) });
        break;
      case "artifact.created": {
        const a = (p.artifact ?? {}) as Record<string, unknown>;
        timeline.push({ seq: e.id, kind: "artifact", agent, title: str(a.name), detail: str(p.deliverable), atMs: at(e) });
        break;
      }
      case "progress": {
        const done = num(p.completed_weight);
        const total = num(p.total_weight);
        if (done !== null && total) progress = done / total;
        break;
      }
      case "log":
        logs.push({ atMs: at(e), level: (["debug", "info", "warn", "error"].includes(str(p.level)) ? str(p.level) : "info") as LogLine["level"], source: agentShortName(agent), message: str(p.message) });
        break;
      case "execution.status": {
        status = str(p.status) as ExecutionStatus;
        if (status === "completed") timeline.push({ seq: e.id, kind: "completed", agent, title: p.result_status && p.result_status !== "completed" ? `Finished (${str(p.result_status).replace("_", " ")})` : "Completed", atMs: at(e) });
        if (status === "failed") {
          const err = (p.error ?? {}) as Record<string, unknown>;
          logs.push({ atMs: at(e), level: "error", source: "engine", message: str(err.message, "Execution failed") });
        }
        break;
      }
    }
  }

  const running = plan.find((s) => s.status === "running" || s.status === "waiting");
  return {
    plan,
    timeline,
    toolCalls: [...calls.values()],
    logs,
    progress,
    stage: running?.title ?? null,
    status,
    stepsCompleted: plan.filter((s) => s.status === "done" || s.status === "skipped").length,
    stepsTotal: plan.length || null,
    models: [...models],
    simulated,
  };
}

/**
 * A whole task: one agent's run, or an orchestrated task. For an orchestrated task the plan is the
 * orchestrator's subtask plan; each subtask's live status, tool calls, model calls and logs come from
 * that subtask's own events, attributed to its agent, on one shared clock.
 */
export function deriveTask(events: TaskEvent[], rootId: string, execs: Record<string, ExecMeta>): DerivedExecution {
  const root = execs[rootId];
  if (!root || root.agent !== "orchestrator") return deriveExecution(events.filter((e) => e.executionId === rootId), root?.agent ?? "assistant");
  const ordered = [...events].sort((a, b) => a.id - b.id);
  const t0 = ordered.length ? Date.parse(ordered[0].createdAt) : 0;
  const groups = new Map<string, TaskEvent[]>();
  for (const e of ordered) {
    if (!groups.has(e.executionId)) groups.set(e.executionId, []);
    groups.get(e.executionId)!.push(e);
  }
  const top = deriveExecution(groups.get(rootId) ?? [], "orchestrator", { t0 });
  const kids = [...groups.entries()].filter(([id]) => id !== rootId && execs[id]).map(([id, evs]) => ({ meta: execs[id], d: deriveExecution(evs, execs[id].agent, { t0 }) }));
  const byKey = new Map(Object.values(execs).filter((m) => m.key).map((m) => [m.key as string, m]));
  const live = new Map(kids.filter((k) => k.meta.key).map((k) => [k.meta.key as string, k.d]));
  const plan = top.plan.map((step) => {
    if (step.status !== "pending" && step.status !== "running" && step.status !== "waiting") return step; // finished per the orchestrator
    const d = live.get(step.id);
    const st = d?.status ?? byKey.get(step.id)?.status;
    return st ? { ...step, status: outcomeStep(st), detail: d?.stage ?? undefined } : step;
  });
  const running = plan.find((s) => s.status === "running" || s.status === "waiting");
  // The orchestrator idles in "waiting_subtasks"; to the user the task is running, or waiting for
  // approval whenever one of its subtasks is.
  let status = top.status as string | null;
  if (status === "waiting_subtasks" || status === "running" || status === "queued") {
    if (kids.some((k) => k.d.status === "waiting_approval")) status = "waiting_approval";
    else if (status === "waiting_subtasks") status = "running";
  }
  return {
    ...top,
    status: status as ExecutionStatus | null,
    plan,
    timeline: [...top.timeline, ...kids.flatMap((k) => k.d.timeline)].sort((a, b) => a.seq - b.seq),
    toolCalls: kids.flatMap((k) => k.d.toolCalls).sort((a, b) => a.atMs - b.atMs),
    logs: [...top.logs, ...kids.flatMap((k) => k.d.logs)].sort((a, b) => a.atMs - b.atMs),
    stage: running ? `${agentShortName(running.agent)}: ${kids.find((k) => k.meta.key === running.id)?.d.stage ?? running.title}` : top.stage,
    stepsCompleted: plan.filter((s) => s.status === "done" || s.status === "skipped" || s.status === "failed").length,
    stepsTotal: plan.length || null,
    models: [...new Set([...top.models, ...kids.flatMap((k) => k.d.models)])],
    simulated: top.simulated || kids.some((k) => k.d.simulated),
  };
}
