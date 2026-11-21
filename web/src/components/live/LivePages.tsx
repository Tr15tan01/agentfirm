"use client";

/**
 * Live (backend) versions of the data screens. Each loads through the BFF in the browser
 * (see lib/live.tsx) and renders the same components the demo uses.
 */
import { useEffect, useMemo } from "react";
import Link from "next/link";
import { ArrowRight, Inbox } from "lucide-react";
import { api } from "@/data/api";
import { deriveTask } from "@/lib/events/derive";
import { useTaskStream } from "@/lib/events/useTaskStream";
import { LiveBoundary, Loading, refresh, useResource } from "@/lib/live";
import type { AgentKey, TaskDetail, TaskRunSummary } from "@/lib/types";
import { AGENT_IDENTITIES, agentShortName } from "@/lib/agents";
import { AgentCard } from "@/components/agent/AgentCard";
import { AgentDirectory } from "@/components/agent/AgentDirectory";
import { BillingAccount } from "@/components/billing/BillingAccount";
import { UsageBilling } from "@/components/billing/UsageBilling";
import { CollaborationView } from "@/components/collaboration/CollaborationView";
import { IdeaBoard } from "@/components/creative/IdeaBoard";
import { AgentActivityCore } from "@/components/agent/AgentActivityCore";
import { QuickTask } from "@/components/dashboard/QuickTask";
import { SettingsView } from "@/components/settings/SettingsView";
import { TaskCard } from "@/components/tasks/TaskCard";
import { TaskMonitor } from "@/components/tasks/TaskMonitor";
import { TaskTable } from "@/components/tasks/TaskTable";
import { Card, EXECUTION_STATUS_META, SectionHeader } from "@/components/ui/primitives";
import { TimeAgo } from "@/components/ui/time";
import { AgentWorkspace } from "@/components/workspace/AgentWorkspace";

const ACTIVE = new Set(["queued", "running", "waiting_approval", "paused"]);
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/** Re-fetch `prefix` every `ms` while `active` (cheap list polling; task pages use SSE). */
function usePoll(prefix: string, active: boolean, ms = 5000) {
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => refresh(prefix), ms);
    return () => clearInterval(t);
  }, [prefix, active, ms]);
}

/* ── Tasks ─────────────────────────────────────────────────────────────── */

function TasksInner() {
  const [tasks, approvals] = useResource("tasks:list", () => Promise.all([api.tasks.list(), api.approvals.pending()]));
  usePoll("tasks:list", tasks.some((t) => ACTIVE.has(t.status)));
  return <TaskTable tasks={tasks} approvals={approvals} demo={false} />;
}

export function LiveTasksPage() {
  return (
    <LiveBoundary>
      <TasksInner />
    </LiveBoundary>
  );
}

function TaskInner({ id }: { id: string }) {
  const [detail, initial] = useResource(`task:${id}`, () => Promise.all([api.tasks.get(id), api.tasks.events(id)]));
  const done = !detail || TERMINAL.has(detail.status);
  const stream = useTaskStream(id, initial, !done);
  const last = stream.events.at(-1);

  // Status changes, approvals and artifacts change server-side records the stream doesn't carry
  // (result, approval rows, artifact list): re-fetch the detail when one arrives.
  useEffect(() => {
    if (last && ["execution.status", "approval.requested", "artifact.created"].includes(last.type)) refresh(`task:${id}`);
  }, [last, id]);
  // When the stream ends (run finished), re-fetch once more: the final result and artifacts.
  useEffect(() => {
    if (stream.connection === "closed") refresh(`task:${id}`);
  }, [stream.connection, id]);

  const task = useMemo<TaskDetail | null>(() => {
    if (!detail) return null;
    const d = deriveTask(stream.events, detail.executionId, detail.executionMap ?? { [detail.executionId]: { agent: detail.agents[0] ?? "assistant", key: null, status: detail.status } });
    return {
      ...detail,
      status: d.status ?? detail.status, // persisted events are ordered and authoritative
      plan: d.plan.length ? d.plan : detail.plan,
      events: d.timeline,
      toolCalls: d.toolCalls,
      logs: d.logs,
      progress: detail.status === "completed" ? 1 : (d.progress ?? detail.progress),
      stage: d.stage ?? detail.stage,
      stepsCompleted: d.stepsTotal ? d.stepsCompleted : detail.stepsCompleted,
      stepsTotal: d.stepsTotal ?? detail.stepsTotal,
      models: d.models.length ? d.models : detail.models,
      simulated: d.simulated || detail.simulated,
    };
  }, [detail, stream.events]);

  if (!task) {
    return (
      <Card className="p-6">
        <p className="text-[14px]">This run doesn&apos;t exist, or it belongs to another workspace.</p>
        <Link href="/tasks" className="mt-2 inline-flex items-center gap-1 text-[13px] text-accent">
          All runs <ArrowRight className="size-3.5" />
        </Link>
      </Card>
    );
  }
  return <TaskMonitor task={task} demo={false} connection={done ? "closed" : stream.connection} onChanged={() => refresh(`task:${id}`)} />;
}

export function LiveTaskPage({ id }: { id: string }) {
  return (
    <LiveBoundary fallback={<Loading rows={4} />}>
      <TaskInner id={id} />
    </LiveBoundary>
  );
}

/* ── Agents ────────────────────────────────────────────────────────────── */

function AgentsInner() {
  const profiles = useResource("agents:profiles", () => api.agents.profiles());
  return <AgentDirectory profiles={profiles} demo={false} />;
}

export function LiveAgentsPage() {
  return (
    <LiveBoundary>
      <AgentsInner />
    </LiveBoundary>
  );
}

function WorkspaceInner({ agent }: { agent: AgentKey }) {
  const [profile, ideas] = useResource(`agents:${agent}`, () => Promise.all([api.agents.get(agent), agent === "creative" ? api.ideas.list() : Promise.resolve(null)]));
  const liveRun = profile?.recentExecutions.find((e) => ACTIVE.has(e.status));
  const execution = useResource(`task:${liveRun?.taskId ?? "none"}:workspace`, () => (liveRun ? api.tasks.get(liveRun.taskId) : Promise.resolve(null)));
  if (!profile) return <Card className="p-6 text-[14px]">This agent isn&apos;t available in your workspace.</Card>;
  return (
    <AgentWorkspace
      profile={profile}
      conversations={[]}
      initialConversationId={null}
      initialMessages={[]}
      execution={execution}
      demo={false}
      board={ideas ? <IdeaBoard initialIdeas={ideas} /> : undefined}
    />
  );
}

export function LiveAgentWorkspacePage({ agent }: { agent: AgentKey }) {
  return (
    <LiveBoundary fallback={<Loading rows={3} />}>
      <WorkspaceInner agent={agent} />
    </LiveBoundary>
  );
}

/* ── Billing, settings, collaboration ──────────────────────────────────── */

function BillingInner() {
  const report = useResource("usage:30d", () => api.usage.report("30d"));
  return (
    <div className="space-y-6">
      <BillingAccount />
      <UsageBilling initial={report} demo={false} />
    </div>
  );
}

export function LiveBillingPage() {
  return (
    <LiveBoundary>
      <BillingInner />
    </LiveBoundary>
  );
}

function SettingsInner() {
  const members = useResource("members", () => api.workspace.members());
  return <SettingsView members={members} demo={false} />;
}

export function LiveSettingsPage() {
  return (
    <LiveBoundary>
      <SettingsInner />
    </LiveBoundary>
  );
}

function CollaborationInner() {
  const tasks = useResource("tasks:list:collab", () => api.tasks.list());
  usePoll("tasks:list:collab", tasks.some((t) => ACTIVE.has(t.status)));
  const collabs = tasks.filter((t) => t.orchestrated || t.agents.length > 1);
  const current = collabs.find((t) => ACTIVE.has(t.status)) ?? collabs[0] ?? null;
  return current ? <ActiveCollaboration id={current.id} others={collabs.filter((t) => t.id !== current.id)} /> : <CollaborationView active={null} others={[]} demo={false} />;
}

/** The newest collaboration, followed live (same stream and derivation as the run page). */
function ActiveCollaboration({ id, others }: { id: string; others: TaskRunSummary[] }) {
  const [detail, initial] = useResource(`task:${id}`, () => Promise.all([api.tasks.get(id), api.tasks.events(id)]));
  const done = !detail || TERMINAL.has(detail.status);
  const stream = useTaskStream(id, initial, !done);
  const last = stream.events.at(-1);
  useEffect(() => {
    if (last && ["execution.status", "approval.requested", "subtask.spawned", "subtask.completed"].includes(last.type)) refresh(`task:${id}`);
  }, [last, id]);
  useEffect(() => {
    if (stream.connection === "closed") {
      refresh(`task:${id}`);
      refresh("tasks:list:collab");
    }
  }, [stream.connection, id]);
  const active = useMemo<TaskDetail | null>(() => {
    if (!detail) return null;
    const d = deriveTask(stream.events, detail.executionId, detail.executionMap ?? {});
    return { ...detail, status: d.status ?? detail.status, plan: d.plan.length ? d.plan : detail.plan, stage: d.stage ?? detail.stage };
  }, [detail, stream.events]);
  return <CollaborationView active={active} others={others} demo={false} onChanged={() => refresh(`task:${id}`)} />;
}

export function LiveCollaborationPage() {
  return (
    <LiveBoundary>
      <CollaborationInner />
    </LiveBoundary>
  );
}

/* ── Overview ──────────────────────────────────────────────────────────── */

function statsLine(tasks: TaskRunSummary[], working: number) {
  const waiting = tasks.filter((t) => t.status === "waiting_approval").length;
  const done = tasks.filter((t) => t.status === "completed").length;
  const parts = [`${working} ${working === 1 ? "agent" : "agents"} working`, `${waiting} ${waiting === 1 ? "approval" : "approvals"} waiting`, `${done} ${done === 1 ? "run" : "runs"} completed`];
  return parts.join(" · ") + ".";
}

function OverviewInner() {
  const [agents, tasks, usage] = useResource("tasks:overview", () => Promise.all([api.agents.list(), api.tasks.list(), api.usage.report("30d")]));
  const active = tasks.filter((t) => ACTIVE.has(t.status));
  usePoll("tasks:overview", active.length > 0);
  const busy = new Map<AgentKey, TaskRunSummary>();
  for (const t of active) for (const a of t.agents) if (!busy.has(a)) busy.set(a, t);
  const roster = agents.map((a) => {
    const t = busy.get(a.key);
    return t ? { ...a, status: (t.status === "waiting_approval" ? "waiting_approval" : "working") as typeof a.status, currentTask: t.title, lastActiveSecondsAgo: t.startedSecondsAgo } : a;
  });
  const recent = tasks.filter((t) => TERMINAL.has(t.status)).slice(0, 6);
  const maxCredits = Math.max(1, ...usage.byAgent.map((a) => a.credits));

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-12 [&>*]:min-w-0">
        <div className="xl:col-span-8">
          <QuickTask stats={statsLine(tasks, busy.size)} />
        </div>
        <div className="xl:col-span-4">
          <LiveRunCore task={active[0] ?? null} />
        </div>
      </div>

      <section aria-labelledby="workforce">
        <SectionHeader title="Active workforce" subtitle={`${roster.length} specialised agents · ${busy.size} working now`} action={<Link href="/agents" className="flex items-center gap-1 text-[13px] font-medium text-fg-2 hover:text-fg">All agents <ArrowRight className="size-3.5" /></Link>} />
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3 min-[1920px]:grid-cols-6">
          {roster.map((a, i) => (
            <AgentCard key={a.key} agent={a} index={i} />
          ))}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-12 [&>*]:min-w-0">
        <section className="xl:col-span-7" aria-labelledby="active-tasks">
          <SectionHeader title="Active tasks" subtitle="Progress comes from completed plan steps; unknown progress is shown as indeterminate." action={<Link href="/tasks" className="flex items-center gap-1 text-[13px] font-medium text-fg-2 hover:text-fg">All runs <ArrowRight className="size-3.5" /></Link>} />
          {active.length ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              {active.map((t) => (
                <TaskCard key={t.id} task={t} />
              ))}
            </div>
          ) : (
            <Card className="mt-4 flex items-center gap-3 p-5 text-[13.5px] text-fg-2">
              <Inbox className="size-5 text-fg-3" /> Nothing running. Describe an outcome above to start a task.
            </Card>
          )}
        </section>
        <section className="af-card flex flex-col p-5 xl:col-span-5" aria-label="Recent activity">
          <SectionHeader title="Recent activity" subtitle="Finished runs" />
          <ul className="mt-4 divide-y divide-[var(--border)]">
            {recent.length ? (
              recent.map((t) => {
                const meta = EXECUTION_STATUS_META[t.status];
                return (
                  <li key={t.id} className="py-3 first:pt-0 last:pb-0">
                    <Link href={`/tasks/${t.id}`} className="flex items-center gap-3 hover:text-fg">
                      <span className="size-2 shrink-0 rounded-full" style={{ background: meta.tone === "ok" ? "var(--ok)" : meta.tone === "err" ? "var(--err)" : "var(--fg-3)" }} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">{t.title}</span>
                        <span className="block truncate text-[12px] text-fg-3">
                          {t.agents.length ? t.agents.map((a) => AGENT_IDENTITIES[a].shortName).join(", ") : "Orchestrator"} · {meta.label}
                        </span>
                      </span>
                      <span className="shrink-0 text-[11.5px] text-fg-3">
                        <TimeAgo secondsAgo={t.startedSecondsAgo} />
                      </span>
                    </Link>
                  </li>
                );
              })
            ) : (
              <li className="py-2 text-[13px] text-fg-3">No finished runs yet.</li>
            )}
          </ul>
        </section>
      </div>

      <Card className="p-5">
        <SectionHeader title="Usage · last 30 days" subtitle={`${usage.totals.requests.toLocaleString()} model calls · ${usage.totals.credits.toLocaleString()} credits`} action={<Link href="/billing" className="flex items-center gap-1 text-[13px] font-medium text-fg-2 hover:text-fg">Usage & billing <ArrowRight className="size-3.5" /></Link>} />
        <ul className="mt-4 space-y-2.5">
          {usage.byAgent.length ? (
            usage.byAgent.map((a) => (
              <li key={a.agent} className="grid grid-cols-[120px_1fr_80px] items-center gap-3 text-[13px]">
                <span className="truncate text-fg-2">{agentShortName(a.agent)}</span>
                <span className="h-2 overflow-hidden rounded-full bg-card-2">
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(a.credits / maxCredits) * 100}%` }} />
                </span>
                <span className="text-right font-mono text-fg">{a.credits.toLocaleString()}</span>
              </li>
            ))
          ) : (
            <li className="text-[13px] text-fg-3">No usage yet.</li>
          )}
        </ul>
      </Card>
    </div>
  );
}

/** The most recent active run, or an honest idle state — never a demo animation. */
function LiveRunCore({ task }: { task: TaskRunSummary | null }) {
  const agent = task?.agents[0] ?? "assistant";
  const state = !task ? "idle" : task.status === "running" || task.status === "queued" ? "working" : "idle";
  return (
    <Card className="flex h-full flex-col p-5">
      <p className="af-label">Live agent core</p>
      <div className="flex flex-1 items-center justify-center py-4">
        <AgentActivityCore agent={agent} state={state} progress={task?.progress ?? null} startedSecondsAgo={task?.startedSecondsAgo ?? 0} task={task?.stage || task?.title || "Waiting for a task"} size={200} showDetails={false} />
      </div>
      {task ? (
        <Link href={`/tasks/${task.id}`} className="truncate text-center text-[13px] font-medium hover:text-accent">
          {AGENT_IDENTITIES[agent].shortName} · {task.title}
        </Link>
      ) : (
        <p className="text-center text-[13px] text-fg-3">No agent is working right now.</p>
      )}
    </Card>
  );
}

export function LiveOverviewPage() {
  return (
    <LiveBoundary fallback={<Loading rows={4} />}>
      <OverviewInner />
    </LiveBoundary>
  );
}
