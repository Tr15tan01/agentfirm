"use client";

import { useState } from "react";
import { AgentActivityCore } from "@/components/agent/AgentActivityCore";
import { DemoBadge } from "@/components/ui/primitives";
import type { AgentKey, CoreState } from "@/lib/types";
import { cn } from "@/lib/cn";

type Preview = { key: string; label: string; agent: AgentKey; state: CoreState; task?: string; progress?: number | null; started?: number; error?: string };

const PREVIEWS: Preview[] = [
  { key: "working", label: "Working", agent: "research", state: "working", task: "EdTech market scan — English learning, CEE region", progress: 5 / 9, started: 1_122 },
  { key: "indeterminate", label: "Planning", agent: "creative", state: "working", task: "Name candidates for the tutoring product line", progress: null, started: 38 },
  { key: "idle", label: "Idle", agent: "assistant", state: "idle" },
  { key: "completed", label: "Done", agent: "bi", state: "completed", task: "Q3 revenue cohort report · 3 deliverables" },
  { key: "failed", label: "Failed", agent: "engineer", state: "failed", task: "Deploy preview environment", error: "Tool `deploy.preview` timed out after 120s. Execution history is preserved; retry resumes from step 4/6." },
];

/** Hero instance of the AgentActivityCore with a state preview switcher (demo). */
export function LiveCorePanel() {
  const [active, setActive] = useState(PREVIEWS[0].key);
  const p = PREVIEWS.find((x) => x.key === active) ?? PREVIEWS[0];

  return (
    <section className="af-card relative flex h-full flex-col overflow-hidden rounded-[20px] p-5" aria-label="Live agent activity">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-[radial-gradient(60%_100%_at_50%_0%,color-mix(in_oklab,var(--accent)_12%,transparent),transparent)]" />
      <div className="relative flex items-center justify-between">
        <div>
          <p className="af-label">Live agent core</p>
          <p className="mt-1 font-mono text-[11.5px] text-fg-3">exe_01JD8K4V9R</p>
        </div>
        <DemoBadge />
      </div>

      <div className="relative flex flex-1 items-center justify-center py-4">
        <AgentActivityCore
          key={p.key}
          agent={p.agent}
          state={p.state}
          task={p.task}
          progress={p.progress ?? null}
          startedSecondsAgo={p.started}
          error={p.error}
          size={196}
        />
      </div>

      <div className="relative mt-2 grid grid-cols-5 gap-1 rounded-[10px] border border-line bg-card-2 p-1" role="tablist" aria-label="Preview core states">
        {PREVIEWS.map((x) => (
          <button
            key={x.key}
            role="tab"
            aria-selected={x.key === active}
            type="button"
            onClick={() => setActive(x.key)}
            className={cn(
              "h-7 rounded-[7px] text-[11.5px] font-medium transition-colors",
              x.key === active ? "bg-card text-fg shadow-[var(--shadow)]" : "text-fg-3 hover:text-fg-2",
            )}
          >
            {x.label}
          </button>
        ))}
      </div>
    </section>
  );
}
