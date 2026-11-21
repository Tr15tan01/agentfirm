"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  ListTree,
  PlayCircle,
  CheckCircle2,
  Wrench,
  Cpu,
  ShieldAlert,
  FileOutput,
  GitBranch,
  Flag,
  type LucideIcon,
} from "lucide-react";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import type { TimelineEvent, TimelineEventKind } from "@/lib/types";
import type { ExecutionStream } from "@/lib/events/types";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/components/ui/time";

const KIND: Record<TimelineEventKind, { icon: LucideIcon; color: string }> = {
  plan: { icon: ListTree, color: "var(--accent-2)" },
  step_started: { icon: PlayCircle, color: "var(--cyan)" },
  step_completed: { icon: CheckCircle2, color: "var(--ok)" },
  tool_call: { icon: Wrench, color: "var(--accent)" },
  model_call: { icon: Cpu, color: "var(--accent)" },
  approval: { icon: ShieldAlert, color: "var(--warn)" },
  artifact: { icon: FileOutput, color: "var(--cyan)" },
  subtask: { icon: GitBranch, color: "var(--accent-2)" },
  completed: { icon: Flag, color: "var(--ok)" },
};

function agentLabel(e: TimelineEvent): { label: string; color: string } {
  if (e.agent === "orchestrator") return { label: "Orchestrator", color: "var(--accent-2)" };
  const id = AGENT_IDENTITIES[e.agent];
  return { label: id.shortName, color: TONE_VAR[id.tone] };
}

export function ExecutionTimeline({ stream, className }: { stream: ExecutionStream; className?: string }) {
  const events = stream.events;
  const latest = events.at(-1)?.seq;

  return (
    <ol className={cn("relative", className)} aria-live="polite" aria-relevant="additions">
      <AnimatePresence initial={false}>
        {events.map((e, i) => {
          const k = KIND[e.kind];
          const Icon = k.icon;
          const who = agentLabel(e);
          const isLatest = e.seq === latest;
          const isLast = i === events.length - 1;
          return (
            <motion.li
              key={e.seq}
              layout="position"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
              className="relative flex gap-3 pb-4 last:pb-0"
            >
              {!isLast ? <span aria-hidden className="absolute left-[13px] top-7 bottom-0 w-px bg-line" /> : null}
              <span
                className={cn("relative z-10 mt-0.5 grid size-[27px] shrink-0 place-items-center rounded-full border bg-card", isLatest && "af-pulse-dot")}
                style={{ borderColor: `color-mix(in oklab, ${k.color} 45%, var(--border))`, color: k.color }}
              >
                <Icon className="size-3.5" strokeWidth={2} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className={cn("truncate text-[13px] font-medium", isLatest ? "text-fg" : "text-fg/90")}>{e.title}</p>
                  <span className="shrink-0 font-mono text-[11px] text-fg-3">+{formatDuration(e.atMs / 1000)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-fg-3">
                  <span className="size-1.5 rounded-full" style={{ background: who.color }} aria-hidden />
                  <span>{who.label}</span>
                  {e.detail ? (
                    <>
                      <span aria-hidden>·</span>
                      <span className="truncate font-mono text-[11.5px]">{e.detail}</span>
                    </>
                  ) : null}
                </div>
              </div>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
