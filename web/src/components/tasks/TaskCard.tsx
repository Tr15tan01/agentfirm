import Link from "next/link";
import { ArrowRight, Timer } from "lucide-react";
import { AGENT_IDENTITIES } from "@/lib/agents";
import type { TaskRunSummary } from "@/lib/types";
import { cn } from "@/lib/cn";
import { Badge, EXECUTION_STATUS_META, Progress } from "@/components/ui/primitives";
import { AgentGlyph } from "@/components/agent/AgentCard";
import { Elapsed } from "@/components/ui/time";

export function TaskCard({ task }: { task: TaskRunSummary }) {
  const meta = EXECUTION_STATUS_META[task.status];
  const pct = task.progress === null ? null : Math.round(task.progress * 100);
  const needsApproval = task.status === "waiting_approval";
  const running = task.status === "running";

  return (
    <article className={cn("af-card p-4 transition-colors hover:border-line-strong", needsApproval && "border-[color-mix(in_oklab,var(--warn)_40%,var(--border))]")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="line-clamp-1 text-[14px] font-semibold tracking-tight">{task.title}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-3">
            <span className="font-mono">{task.executionId}</span>
            <span aria-hidden>·</span>
            <span>{task.agents.length > 1 ? `${task.agents.length} agents` : task.agents.length ? AGENT_IDENTITIES[task.agents[0]].shortName : "Orchestrator · planning"}</span>
          </div>
        </div>
        <Badge tone={meta.tone} live={meta.live}>
          {meta.label}
        </Badge>
      </div>

      <div className="mt-4 flex items-center justify-between gap-3 text-[12.5px]">
        <span className="line-clamp-1 text-fg-2">{task.stage}</span>
        <span className="shrink-0 font-mono text-fg">
          {pct === null ? <span className="text-fg-3">— %</span> : `${pct}%`}
        </span>
      </div>
      <Progress
        className="mt-2"
        value={task.progress}
        tone={needsApproval ? "warn" : "accent"}
        label={`${task.title} progress`}
      />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex shrink-0 -space-x-2">
            {task.agents.map((a) => (
              <div key={a} className="rounded-[12px] ring-2 ring-[var(--card)]">
                <AgentGlyph agent={a} size={26} />
              </div>
            ))}
          </div>
          <span className="flex items-center gap-1 text-[12px] text-fg-3">
            <Timer className="size-3.5" aria-hidden />
            <Elapsed startedSecondsAgo={task.startedSecondsAgo} running={running} />
            {task.stepsTotal !== null ? (
              <span className="ml-1 whitespace-nowrap font-mono">
                · {task.stepsCompleted}/{task.stepsTotal} steps
              </span>
            ) : (
              <span className="ml-1">· planning</span>
            )}
          </span>
        </div>
        <Link
          href={`/tasks/${task.id}`}
          className={cn(
            "flex h-8 shrink-0 items-center gap-1 rounded-[9px] px-2.5 text-[12.5px] font-medium transition-colors",
            needsApproval ? "bg-[color-mix(in_oklab,var(--warn)_14%,transparent)] text-warn hover:bg-[color-mix(in_oklab,var(--warn)_22%,transparent)]" : "text-fg-2 hover:bg-card-2 hover:text-fg",
          )}
        >
          {needsApproval ? "Review" : "View details"} <ArrowRight className="size-3.5" />
        </Link>
      </div>
    </article>
  );
}
