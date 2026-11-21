"use client";

import Link from "next/link";
import { ArrowUpRight, Radio } from "lucide-react";
import { AgentCollaborationCore, type CollaborationParticipant } from "@/components/agent/AgentCollaborationCore";
import { ExecutionTimeline } from "@/components/tasks/ExecutionTimeline";
import { DemoBadge, Progress } from "@/components/ui/primitives";
import { AGENT_IDENTITIES } from "@/lib/agents";
import type { AgentKey, TimelineEvent } from "@/lib/types";
import { useDemoExecutionStream } from "@/mocks/useDemoExecutionStream";

const PARTICIPANTS: AgentKey[] = ["research", "bi", "creative", "marketing"];
const PLAN_STEPS = 9;

/** Participant state is derived from the event stream, never set by hand. */
function deriveParticipants(events: TimelineEvent[]): CollaborationParticipant[] {
  const latestAgent = [...events].reverse().find((e) => e.agent !== "orchestrator")?.agent;
  const seen = new Set(events.map((e) => e.agent));
  return PARTICIPANTS.map((agent) => ({
    agent,
    subtask: "",
    state: agent === latestAgent ? "active" : seen.has(agent) ? "done" : "pending",
  }));
}

export function ExecutionPanel() {
  const stream = useDemoExecutionStream(1);
  const participants = deriveParticipants(stream.events);
  const completedSteps = 3 +stream.events.filter((e) => e.kind === "step_completed" || e.kind === "artifact").length;
  const active = participants.find((p) => p.state === "active");

  return (
    <section className="af-card flex h-full flex-col p-5" aria-label="Live execution">
      <div className="flex flex-col-reverse items-start justify-between gap-3 sm:flex-row">
        <div className="min-w-0">
          <p className="af-label">Agent collaboration · live execution</p>
          <h3 className="mt-1 truncate text-[14px] font-semibold">English-learning market strategy</h3>
          <p className="mt-0.5 font-mono text-[11.5px] text-fg-3">exe_01JD8K4V9R · seq {stream.lastSeq}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-end sm:gap-1.5">
          <DemoBadge />
          <span className="flex items-center gap-1 text-[11px] text-fg-3">
            <Radio className="size-3 text-cyan" /> Scripted replay (SSE in Phase 4)
          </span>
        </div>
      </div>

      <div className="mt-3 rounded-[12px] border border-line bg-card-2 px-2 pb-2 pt-3">
        <AgentCollaborationCore participants={participants} size={320} />
        <div className="mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[11.5px] text-fg-3">
          {participants.map((p) => (
            <span key={p.agent} className="flex items-center gap-1">
              <span
                className="size-1.5 rounded-full"
                style={{ background: p.state === "active" ? "var(--cyan)" : p.state === "done" ? "var(--ok)" : "var(--fg-3)" }}
              />
              <span className={p.state === "active" ? "text-fg" : undefined}>{AGENT_IDENTITIES[p.agent].shortName}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-[12px]">
          <span className="text-fg-2">
            {active ? `${AGENT_IDENTITIES[active.agent].shortName} is working` : "Orchestrator planning"}
          </span>
          <span className="font-mono text-fg">
            {completedSteps}/{PLAN_STEPS} steps
          </span>
        </div>
        <Progress className="mt-2" value={completedSteps / PLAN_STEPS} label="Collaboration progress" />
      </div>

      <div className="mt-5 max-h-[340px] flex-1 overflow-y-auto pr-1">
        <ExecutionTimeline stream={stream} />
      </div>

      <Link href="/tasks/tsk_7Q2M" className="mt-4 flex items-center gap-1 self-end text-[12.5px] font-medium text-accent hover:underline">
        Open execution <ArrowUpRight className="size-3.5" />
      </Link>
    </section>
  );
}
