"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as Tabs from "@radix-ui/react-tabs";
import * as Dialog from "@radix-ui/react-dialog";
import { ArrowLeft, Ban, FolderKanban, Loader2, Pause, Play, RotateCcw, Send, Trash, User, GitBranch } from "lucide-react";
import type { ExecutionStatus, TaskDetail, LogLine } from "@/lib/types";
import type { StreamConnection } from "@/lib/events/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { api } from "@/data/api";
import { refresh } from "@/lib/live";
import { AgentActivityCore } from "@/components/agent/AgentActivityCore";
import { AgentCollaborationCore } from "@/components/agent/AgentCollaborationCore";
import { Badge, Button, Card, DemoBadge, EXECUTION_STATUS_META, Progress } from "@/components/ui/primitives";
import { Elapsed, formatDuration } from "@/components/ui/time";
import { CopyButton, Markdown } from "@/components/ui/Markdown";
import { useToast } from "@/components/ui/toast";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { ApprovalCard, ArtifactList, StepList, ToolCallList } from "./ExecutionParts";
import { SubtaskGraph } from "./SubtaskGraph";
import { useCreateTask } from "./useCreateTask";

const LEVEL_COLOR: Record<LogLine["level"], string> = { debug: "var(--fg-3)", info: "var(--accent)", warn: "var(--warn)", error: "var(--err)" };

export function TaskMonitor({ task, demo, connection, onChanged }: { task: TaskDetail; demo: boolean; connection?: StreamConnection; onChanged?: () => void }) {
  const toast = useToast();
  // The server's status wins as soon as it changes; a local override only bridges the gap
  // between a control action and the engine's execution.status event.
  const [override, setOverride] = useState<{ from: ExecutionStatus; to: ExecutionStatus } | null>(null);
  const status = override && override.from === task.status ? override.to : task.status;
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const router = useRouter();
  const [levels, setLevels] = useState<LogLine["level"][]>(["debug", "info", "warn", "error"]);

  const m = EXECUTION_STATUS_META[status];
  const multi = task.agents.length > 1;
  const lead = task.agents[0] ?? "assistant"; // an orchestrated task has no agents until it is planned
  const startTask = useCreateTask();
  const coreState = status === "failed" ? "failed" : status === "completed" ? "completed" : status === "cancelled" || status === "paused" ? "idle" : multi ? "collaborating" : "working";

  const control = async (action: "pause" | "resume" | "cancel" | "retry") => {
    setBusy(action);
    try {
      const next = await api.tasks.control(task.id, action);
      setOverride({ from: task.status, to: next });
      onChanged?.();
      toast({ tone: action === "cancel" ? "warning" : "success", title: `Execution ${next.replace("_", " ")}`, description: `${task.executionId} · ${action} accepted by the engine` });
    } catch (e) {
      toast({ tone: "error", title: `Couldn't ${action} this run`, description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
      setConfirmCancel(false);
    }
  };

  const canPause = task.controls.pause && status === "running";
  const canResume = status === "paused";
  const remove = async () => {
    setBusy("delete");
    try {
      await api.tasks.remove(task.id);
      toast({ tone: "warning", title: "Task deleted", description: "Anything still running was stopped first." });
      refresh("tasks:list");
      router.push("/tasks");
    } catch (e) {
      toast({ tone: "error", title: "Couldn't delete this task", description: e instanceof Error ? e.message : String(e) });
      setBusy(null);
      setConfirmDelete(false);
    }
  };

  const canCancel = task.controls.cancel && !["completed", "failed", "cancelled"].includes(status);
  const canRetry = task.controls.retry && (status === "failed" || status === "cancelled" || status === "completed");

  return (
    <div className="space-y-5">
      <Link href="/tasks" className="inline-flex items-center gap-1.5 text-[13px] text-fg-2 hover:text-fg">
        <ArrowLeft className="size-3.5" /> All runs
      </Link>

      {/* Header */}
      <Card className={cn("p-5", m.live && "af-sweep")}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={m.tone} live={m.live}>
                {m.label}
              </Badge>
              {multi ? <Badge tone="violet">Multi-agent · {task.agents.length}</Badge> : null}
              {task.orchestrated ? (
                <span title="Planned and coordinated by the orchestrator: each subtask runs as its own agent run, with its own approvals.">
                  <Badge tone="muted">Orchestrated</Badge>
                </span>
              ) : null}
              {demo ? <DemoBadge /> : null}
              {task.simulated ? (
                <span title="Model calls came from the offline simulator (development/CI), not a real provider.">
                  <Badge tone="warn">Simulated models</Badge>
                </span>
              ) : null}
            </div>
            <h2 className="mt-3 text-[21px] font-semibold tracking-tight">{task.title}</h2>
            <p className="mt-1 max-w-3xl text-[14px] text-fg-2">{task.objective}</p>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-fg-3">
              <span className="flex items-center gap-1">
                <span className="font-mono text-fg-2">{task.executionId}</span>
                <CopyButton text={task.executionId} label="" />
              </span>
              {task.project ? (
                <span className="flex items-center gap-1">
                  <FolderKanban className="size-3.5" /> {task.project}
                </span>
              ) : null}
              <span className="flex items-center gap-1">
                <User className="size-3.5" /> {task.createdBy}
              </span>
              <span className="flex items-center gap-1" title="Agent versions pinned for this execution">
                <GitBranch className="size-3.5" /> <span className="font-mono">{task.agentVersion}</span>
              </span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {canPause ? (
              <Button onClick={() => control("pause")} disabled={!!busy}>
                {busy === "pause" ? <Loader2 className="size-4 animate-spin" /> : <Pause className="size-4" />} Pause
              </Button>
            ) : null}
            {canResume ? (
              <Button variant="primary" onClick={() => control("resume")} disabled={!!busy}>
                {busy === "resume" ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Resume
              </Button>
            ) : null}
            {canRetry ? (
              <Button variant="primary" onClick={() => control("retry")} disabled={!!busy}>
                {busy === "retry" ? <Loader2 className="size-4 animate-spin" /> : <RotateCcw className="size-4" />} {status === "completed" ? "Run again" : "Retry from checkpoint"}
              </Button>
            ) : null}
            {canCancel ? (
              <Button variant="danger" onClick={() => setConfirmCancel(true)} disabled={!!busy}>
                <Ban className="size-4" /> Cancel
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => setConfirmDelete(true)} disabled={!!busy} title="Stop and delete this task">
              <Trash className="size-4" /> Delete
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px] [&>*]:min-w-0">
        <div className="space-y-5">
          {task.subtasks.length ? (
            <Card className="p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h3 className="text-[15px] font-semibold">Collaboration graph</h3>
                  <p className="text-[12.5px] text-fg-2">Which agent works on which subtask, and what each one waits for.</p>
                </div>
              </div>
              <SubtaskGraph subtasks={task.subtasks} />
            </Card>
          ) : null}

          {task.result ? (
            <Card className="p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-[15px] font-semibold">Result</h3>
                <CopyButton text={task.result} />
              </div>
              <div className="af-prose max-w-none text-[14px]">
                <Markdown>{task.result}</Markdown>
              </div>
              {task.models?.length ? <p className="mt-3 text-[11.5px] text-fg-3">Models: {task.models.join(" · ")}</p> : null}
              {task.resultStatus === "needs_input" && !demo ? <ReplyBox taskId={task.id} questions={task.questions ?? []} onSent={() => onChanged?.()} /> : null}
            </Card>
          ) : null}

          <Card className="p-0">
            <Tabs.Root defaultValue="timeline">
              <Tabs.List className="flex gap-1 overflow-x-auto border-b border-line px-3 pt-2" aria-label="Execution details">
                {[
                  { v: "timeline", l: "Timeline", n: task.events.length },
                  { v: "tools", l: "Tool calls", n: task.toolCalls.length },
                  { v: "logs", l: "Logs", n: task.logs.length },
                  { v: "artifacts", l: "Artifacts", n: task.artifacts.length },
                ].map((t) => (
                  <Tabs.Trigger
                    key={t.v}
                    value={t.v}
                    className="relative flex h-10 shrink-0 items-center gap-1.5 px-3 text-[13px] text-fg-2 outline-none hover:text-fg data-[state=active]:text-fg data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:bottom-0 data-[state=active]:after:h-0.5 data-[state=active]:after:rounded-full data-[state=active]:after:bg-accent"
                  >
                    {t.l} <span className="font-mono text-[11px] text-fg-3">{t.n}</span>
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
              <div className="p-5">
                <Tabs.Content value="timeline">
                  <ExecutionTimeline stream={{ events: task.events, connection: connection ?? (demo ? "demo" : "closed"), lastSeq: task.events.at(-1)?.seq ?? 0 }} />
                </Tabs.Content>
                <Tabs.Content value="tools">
                  <ToolCallList calls={task.toolCalls} />
                </Tabs.Content>
                <Tabs.Content value="logs">
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {(["debug", "info", "warn", "error"] as const).map((l) => {
                      const on = levels.includes(l);
                      return (
                        <button
                          key={l}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setLevels((x) => (on ? x.filter((y) => y !== l) : [...x, l]))}
                          className={cn("h-7 rounded-full border px-2.5 font-mono text-[11.5px]", on ? "border-line-strong text-fg" : "border-line text-fg-3 line-through")}
                        >
                          {l}
                        </button>
                      );
                    })}
                  </div>
                  <div className="overflow-x-auto rounded-[10px] border border-line bg-[var(--bg)] p-3 font-mono text-[12px] leading-relaxed">
                    {task.logs
                      .filter((l) => levels.includes(l.level))
                      .map((l, i) => (
                        <div key={i} className="flex gap-3 whitespace-nowrap">
                          <span className="text-fg-3">+{formatDuration(l.atMs / 1000)}</span>
                          <span className="w-12 uppercase" style={{ color: LEVEL_COLOR[l.level] }}>
                            {l.level}
                          </span>
                          <span className="w-24 text-fg-2">{l.source}</span>
                          <span className="text-fg">{l.message}</span>
                        </div>
                      ))}
                  </div>
                </Tabs.Content>
                <Tabs.Content value="artifacts">
                  <ArtifactList artifacts={task.artifacts} />
                </Tabs.Content>
              </div>
            </Tabs.Root>
          </Card>
        </div>

        <div className="space-y-5">
          <Card className="p-5">
            <div className="flex justify-center">
              {multi ? (
                <AgentCollaborationCore
                  size={300}
                  participants={task.agents.map((a) => {
                    const subs = task.subtasks.filter((s) => s.agent === a);
                    const state = subs.some((s) => s.status === "running") ? "active" : subs.length && subs.every((s) => s.status === "done") ? "done" : subs.some((s) => s.status === "done") ? "done" : "pending";
                    return { agent: a, state, subtask: subs.map((s) => s.title).join(", ") };
                  })}
                />
              ) : (
                <AgentActivityCore agent={lead} state={coreState} progress={task.progress} startedSecondsAgo={task.startedSecondsAgo} task={task.stage} size={170} showDetails={false} />
              )}
            </div>
            <div className="mt-4">
              <div className="mb-1.5 flex items-center justify-between text-[12.5px]">
                <span className="truncate text-fg-2">{task.stage}</span>
                <span className="font-mono text-fg">{task.progress === null ? "—" : `${Math.round(task.progress * 100)}%`}</span>
              </div>
              <Progress value={status === "completed" ? 1 : task.progress} tone={status === "failed" ? "err" : status === "waiting_approval" ? "warn" : status === "completed" ? "ok" : "accent"} label="Execution progress" />
              <dl className="mt-4 grid grid-cols-2 gap-2 text-[12px]">
                <div className="rounded-[10px] border border-line bg-card-2 px-3 py-2">
                  <dt className="text-fg-3">Steps</dt>
                  <dd className="mt-0.5 font-mono text-[14px]">{task.stepsTotal === null ? "planning" : `${task.stepsCompleted}/${task.stepsTotal}`}</dd>
                </div>
                <div className="rounded-[10px] border border-line bg-card-2 px-3 py-2">
                  <dt className="text-fg-3">Elapsed</dt>
                  <dd className="mt-0.5 text-[14px]">
                    <Elapsed startedSecondsAgo={task.startedSecondsAgo} running={status === "running"} />
                  </dd>
                </div>
              </dl>
              <p className="mt-3 text-[11.5px] text-fg-3">
                {task.progress === null ? "Progress is unknown until the plan is finalised — shown as indeterminate." : "Progress = completed plan steps ÷ total, emitted by the engine."}
              </p>
            </div>
          </Card>

          {task.suggestions?.length ? (
            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">Suggested next steps</h3>
              <p className="mb-3 mt-0.5 text-[12.5px] text-fg-2">An agent proposed these, but they weren&apos;t run automatically (policy, budget or depth limits). Start one as its own task.</p>
              <ul className="space-y-2">
                {task.suggestions.map((sg, i) => (
                  <li key={i} className="rounded-[10px] border border-line px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium">{AGENT_IDENTITIES[sg.agent].shortName}</span>
                      {!demo ? (
                        <Button size="sm" onClick={() => void startTask({ agents: [sg.agent], instruction: sg.objective, files: [] })}>
                          <Play className="size-3.5" /> Start
                        </Button>
                      ) : null}
                    </div>
                    <p className="mt-1 line-clamp-3 text-[12.5px] text-fg-2">{sg.objective}</p>
                    {sg.reason ? <p className="mt-1 text-[11.5px] text-fg-3">Why: {sg.reason}</p> : null}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {task.approvals.length ? (
            <Card className="p-5">
              <h3 className="mb-3 text-[15px] font-semibold">Approvals</h3>
              <div className="space-y-2">
                {task.approvals.map((a) => (
                  <ApprovalCard key={a.id} approval={a} onDecided={() => onChanged?.()} />
                ))}
              </div>
            </Card>
          ) : null}

          <Card className="p-5">
            <h3 className="mb-3 text-[15px] font-semibold">Execution plan</h3>
            <StepList steps={task.plan} />
          </Card>

          <Card className="p-5">
            <h3 className="mb-2 text-[15px] font-semibold">Agents</h3>
            <ul className="space-y-1.5">
              {task.agents.map((a) => (
                <li key={a}>
                  <Link href={`/agents/${a}`} className="flex items-center justify-between rounded-md px-2 py-1.5 text-[13px] text-fg-2 hover:bg-card-2 hover:text-fg">
                    {AGENT_IDENTITIES[a].name}
                    <span className="text-[11.5px] text-fg-3">{task.plan.filter((p) => p.agent === a).length} {task.plan.filter((p) => p.agent === a).length === 1 ? "step" : "steps"}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <Dialog.Root open={confirmDelete} onOpenChange={setConfirmDelete}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
          <Dialog.Content className="fixed left-1/2 top-1/3 z-50 w-[min(440px,calc(100vw-2rem))] -translate-x-1/2 rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow)]">
            <Dialog.Title className="text-[16px] font-semibold">Delete this task?</Dialog.Title>
            <Dialog.Description className="mt-1.5 text-[13.5px] text-fg-2">
              If it is still running it is stopped first. The task, its history, approvals and files are then removed for good. This can&apos;t be undone.
            </Dialog.Description>
            <div className="mt-4 flex justify-end gap-2">
              <Dialog.Close asChild>
                <Button variant="ghost">Keep it</Button>
              </Dialog.Close>
              <Button variant="danger" onClick={remove} disabled={busy === "delete"}>
                {busy === "delete" ? <Loader2 className="size-4 animate-spin" /> : <Trash className="size-4" />} Stop and delete
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <Dialog.Root open={confirmCancel} onOpenChange={setConfirmCancel}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
          <Dialog.Content className="fixed left-1/2 top-1/3 z-50 w-[min(440px,calc(100vw-2rem))] -translate-x-1/2 rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow)]">
            <Dialog.Title className="text-[16px] font-semibold">Cancel this execution?</Dialog.Title>
            <Dialog.Description className="mt-1.5 text-[13.5px] text-fg-2">
              In-flight model and tool calls are aborted. Completed steps, logs and artifacts are kept in history. This can&apos;t be undone.
            </Dialog.Description>
            <div className="mt-5 flex justify-end gap-2">
              <Dialog.Close asChild>
                <Button variant="ghost">Keep running</Button>
              </Dialog.Close>
              <Button variant="danger" onClick={() => control("cancel")} disabled={busy === "cancel"}>
                {busy === "cancel" ? <Loader2 className="size-4 animate-spin" /> : <Ban className="size-4" />} Cancel execution
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

/** Answer the agent's question(s): a new attempt continues where the task stopped (finished
 * subtasks of an orchestrated task are reused, not re-run). */
function ReplyBox({ taskId, questions, onSent }: { taskId: string; questions: string[]; onSent: () => void }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="mt-4 rounded-[12px] border border-accent/40 bg-accent/5 p-3.5"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!text.trim()) return;
        setBusy(true);
        try {
          await api.tasks.reply(taskId, text.trim());
          setText("");
          onSent();
        } catch (err) {
          toast({ tone: "error", title: "Couldn't send your answer", description: err instanceof Error ? err.message : String(err) });
        } finally {
          setBusy(false);
        }
      }}
    >
      <p className="text-[13px] font-medium">The agent needs your answer to continue</p>
      {questions.length ? (
        <ul className="mt-1 list-disc pl-5 text-[13px] text-fg-2">
          {questions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      ) : null}
      <textarea
        className="mt-2.5 min-h-[72px] w-full rounded-[10px] border border-line bg-card px-3 py-2 text-[13.5px] outline-none focus:border-accent"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Your answer"
        aria-label="Your answer"
        maxLength={4000}
      />
      <Button variant="primary" type="submit" className="mt-2" disabled={busy || !text.trim()}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Send and continue
      </Button>
    </form>
  );
}
