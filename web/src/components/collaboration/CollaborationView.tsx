"use client";

import Link from "next/link";
import { ArrowUpRight, Check, CircleDot, Combine, GitFork, ListChecks, Network, Radar, ShieldCheck, Sparkles, Split, Users, type LucideIcon } from "lucide-react";
import type { TaskDetail, TaskRunSummary } from "@/lib/types";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { AgentCollaborationCore, type ParticipantState } from "@/components/agent/AgentCollaborationCore";
import { Badge, Card, DemoBadge, EXECUTION_STATUS_META, Progress } from "@/components/ui/primitives";
import { Elapsed } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { TaskComposer } from "@/components/tasks/TaskComposer";
import { SubtaskGraph } from "@/components/tasks/SubtaskGraph";
import { ApprovalCard, StepIcon } from "@/components/tasks/ExecutionParts";
import { useCreateTask } from "@/components/tasks/useCreateTask";

const STAGES: { label: string; icon: LucideIcon; hint: string }[] = [
  { label: "Analyse", icon: Radar, hint: "Understand intent & constraints" },
  { label: "Plan", icon: ListChecks, hint: "Build a subtask DAG" },
  { label: "Select agents", icon: Users, hint: "Match capabilities" },
  { label: "Assign", icon: Split, hint: "Dispatch subtasks" },
  { label: "Coordinate", icon: GitFork, hint: "Run in parallel, pass context" },
  { label: "Collect", icon: Combine, hint: "Gather outputs" },
  { label: "Verify", icon: ShieldCheck, hint: "Report failed or skipped work" },
  { label: "Deliver", icon: Sparkles, hint: "One unified result" },
];

const FINISHED = new Set(["done", "skipped", "failed"]);

/** Derive the orchestrator stage from real subtask states (never a guess: unknown → planning). */
function currentStage(task: TaskDetail): number {
  const s = task.subtasks;
  if (["completed", "failed", "cancelled"].includes(task.status)) return STAGES.length; // delivered (or stopped)
  if (!s.length) return task.status === "queued" ? 0 : 1;
  if (s.every((x) => FINISHED.has(x.status))) return 6;
  if (s.some((x) => FINISHED.has(x.status))) return 4;
  if (s.some((x) => x.status === "running" || x.status === "waiting")) return 3;
  return 2;
}

export function CollaborationView({ active, others, demo, onChanged }: { active: TaskDetail | null; others: TaskRunSummary[]; demo: boolean; onChanged?: () => void }) {
  const toast = useToast();
  const create = useCreateTask();
  const stage = active ? currentStage(active) : -1;

  const participants = active
    ? active.agents.map((a) => {
        const subs = active.subtasks.filter((s) => s.agent === a);
        const state: ParticipantState = subs.some((s) => s.status === "running" || s.status === "waiting") ? "active" : subs.length && subs.every((s) => FINISHED.has(s.status)) ? "done" : "pending";
        return { agent: a, state, subtask: subs.map((s) => s.title).join(" · ") };
      })
    : [];

  return (
    <div className="space-y-6">
      <section className="af-card af-glass relative overflow-hidden rounded-[20px] p-5 sm:p-7">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 size-80 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-2)_22%,transparent),transparent)]" />
        <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-center">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="af-label">Agent collaboration</p>
              {demo ? <DemoBadge /> : null}
            </div>
            <h2 className="mt-2 text-[24px] font-semibold tracking-tight sm:text-[28px]">One request. A coordinated team.</h2>
            <p className="mt-2 max-w-2xl text-[14px] text-fg-2">
              The orchestrator breaks complex work into subtasks, assigns the right specialists, runs independent work in parallel, pauses for your approval before sensitive actions,
              then verifies and merges everything into one answer.
            </p>
            <div className="mt-5">
              <TaskComposer
                showSuggestions={false}
                onSubmit={(d) =>
                  demo
                    ? toast({ tone: "info", title: "Demo mode — collaboration not started", description: `The orchestrator would plan “${d.instruction.slice(0, 50)}…”.` })
                    : void create(d)
                }
              />
              {!demo ? <p className="mt-2 text-[12px] text-fg-3">Pick no agents to let the orchestrator choose, or pick several to make it plan across them.</p> : null}
            </div>
          </div>
          <div className="hidden lg:block">
            <AgentCollaborationCore
              size={300}
              participants={
                demo
                  ? [
                      { agent: "research", state: "done", subtask: "" },
                      { agent: "bi", state: "done", subtask: "" },
                      { agent: "creative", state: "active", subtask: "" },
                      { agent: "marketing", state: "pending", subtask: "" },
                      { agent: "engineer", state: "pending", subtask: "" },
                      { agent: "assistant", state: "pending", subtask: "" },
                    ]
                  : participants // live: only the agents actually working on the current collaboration
              }
            />
          </div>
        </div>
      </section>

      {/* Orchestrator pipeline */}
      <Card className="p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-[15px] font-semibold">Orchestrator pipeline</h3>
            <p className="text-[12.5px] text-fg-2">{active ? <>Stage for <span className="text-fg">{active.title}</span>, derived from subtask states.</> : "No active collaboration."}</p>
          </div>
        </div>
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          {STAGES.map((s, i) => {
            const done = i < stage;
            const current = i === stage;
            const Icon = s.icon;
            return (
              <li
                key={s.label}
                className={cn(
                  "relative rounded-[12px] border px-3 py-3",
                  current ? "af-live bg-[color-mix(in_oklab,var(--accent)_7%,var(--card))]" : done ? "border-line bg-card-2" : "border-dashed border-line",
                )}
                aria-current={current ? "step" : undefined}
              >
                <div className="flex items-center justify-between">
                  <Icon className={cn("size-4", current ? "text-accent" : done ? "text-ok" : "text-fg-3")} />
                  {done ? <Check className="size-3.5 text-ok" /> : current ? <CircleDot className="size-3.5 animate-pulse text-cyan motion-reduce:animate-none" /> : <span className="font-mono text-[10.5px] text-fg-3">{i + 1}</span>}
                </div>
                <p className={cn("mt-2 text-[13px] font-medium", !done && !current && "text-fg-2")}>{s.label}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-fg-3">{s.hint}</p>
              </li>
            );
          })}
        </ol>
      </Card>

      {active ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px] [&>*]:min-w-0">
          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={EXECUTION_STATUS_META[active.status].tone} live>
                    {EXECUTION_STATUS_META[active.status].label}
                  </Badge>
                  <span className="font-mono text-[11.5px] text-fg-3">{active.executionId}</span>
                </div>
                <h3 className="mt-2 text-[16px] font-semibold">{active.title}</h3>
                <p className="mt-1 text-[13px] text-fg-2">{active.objective}</p>
              </div>
              <Link href={`/tasks/${active.id}`} className="flex items-center gap-1 text-[13px] font-medium text-accent hover:underline">
                Full monitor <ArrowUpRight className="size-3.5" />
              </Link>
            </div>
            <div className="mt-4">
              <div className="mb-1.5 flex justify-between text-[12px] text-fg-2">
                <span>
                  {active.stepsCompleted}/{active.stepsTotal} plan steps · <Elapsed startedSecondsAgo={active.startedSecondsAgo} />
                </span>
                <span className="font-mono text-fg">{active.progress === null ? "—" : `${Math.round(active.progress * 100)}%`}</span>
              </div>
              <Progress value={active.progress} label="Collaboration progress" />
            </div>
            <div className="mt-5 rounded-[12px] border border-line bg-card-2 p-4">
              <div className="af-label mb-3">Subtasks & dependencies</div>
              <SubtaskGraph subtasks={active.subtasks} />
            </div>
          </Card>

          <div className="space-y-6">
            <Card className="p-5">
              <h3 className="mb-3 text-[15px] font-semibold">Participating agents</h3>
              <ul className="space-y-2">
                {participants.map((p) => {
                  const id = AGENT_IDENTITIES[p.agent];
                  const Icon = id.icon;
                  return (
                    <li key={p.agent} className={cn("flex items-start gap-3 rounded-[10px] border px-3 py-2.5", p.state === "active" ? "af-live" : "border-line")}>
                      <Icon className="mt-0.5 size-4 shrink-0" style={{ color: TONE_VAR[id.tone] }} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-medium">{id.shortName}</span>
                          <StepIcon status={p.state === "active" ? "running" : p.state === "done" ? "done" : "pending"} className="size-3.5" />
                        </div>
                        <p className="mt-0.5 truncate text-[12px] text-fg-3">{p.subtask || "Waiting for inputs"}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>

            {active.approvals.length ? (
              <Card className="p-5">
                <h3 className="mb-1 text-[15px] font-semibold">Human approval gates</h3>
                <p className="mb-3 text-[12.5px] text-fg-2">Sensitive or external actions pause the plan until someone with permission decides.</p>
                <div className="space-y-2">
                  {active.approvals.map((a) => (
                    <ApprovalCard key={a.id} approval={a} onDecided={onChanged} />
                  ))}
                </div>
              </Card>
            ) : null}
          </div>
        </div>
      ) : (
        <Card className="grid place-items-center px-6 py-16 text-center">
          <Network className="size-6 text-fg-3" />
          <p className="mt-3 text-[14px] font-medium">No collaborations running</p>
          <p className="mt-1 text-[13px] text-fg-2">Describe a complex outcome above and the orchestrator will assemble a team.</p>
        </Card>
      )}

      {others.length ? (
        <Card className="p-5">
          <h3 className="mb-3 text-[15px] font-semibold">Recent collaborations</h3>
          <ul className="divide-y divide-[var(--border)]">
            {others.map((t) => (
              <li key={t.id}>
                <Link href={`/tasks/${t.id}`} className="flex items-center justify-between gap-3 py-2.5 text-[13px] hover:text-fg">
                  <span className="truncate text-fg-2">{t.title}</span>
                  <Badge tone={EXECUTION_STATUS_META[t.status].tone}>{EXECUTION_STATUS_META[t.status].label}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
