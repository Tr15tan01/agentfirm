"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Search, ShieldAlert } from "lucide-react";
import type { ApprovalRequest, ExecutionStatus, TaskRunSummary } from "@/lib/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { Badge, DemoBadge, EXECUTION_STATUS_META, Progress } from "@/components/ui/primitives";
import { Elapsed } from "@/components/ui/time";
import { AgentGlyph } from "@/components/agent/AgentCard";
import { ApprovalCard } from "./ExecutionParts";

const TABS: { key: "all" | ExecutionStatus; label: string }[] = [
  { key: "all", label: "All runs" },
  { key: "running", label: "Running" },
  { key: "waiting_approval", label: "Needs approval" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
];

export function TaskTable({ tasks, approvals, demo }: { tasks: TaskRunSummary[]; approvals: ApprovalRequest[]; demo: boolean }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("all");
  const [q, setQ] = useState("");

  const rows = useMemo(
    () =>
      tasks.filter(
        (t) => (tab === "all" || t.status === tab) && (!q || `${t.title} ${t.executionId} ${t.id}`.toLowerCase().includes(q.toLowerCase())),
      ),
    [tasks, tab, q],
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[22px] font-semibold tracking-tight">Tasks & runs</h2>
            {demo ? <DemoBadge /> : null}
          </div>
          <p className="mt-1 text-[14px] text-fg-2">Every execution keeps running when you close the browser. State and progress come from backend events.</p>
        </div>
        <label className="flex h-9 w-full items-center gap-2 rounded-[10px] border border-line bg-card-2 px-3 text-[13px] focus-within:border-accent sm:w-72">
          <Search className="size-4 text-fg-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title or execution ID" className="w-full bg-transparent outline-none placeholder:text-fg-3" aria-label="Search tasks" />
        </label>
      </div>

      {approvals.length ? (
        <section aria-label="Approval queue" className="space-y-2">
          <h3 className="flex items-center gap-2 text-[13px] font-semibold text-warn">
            <ShieldAlert className="size-4" /> {approvals.length} approval{approvals.length > 1 ? "s" : ""} waiting
          </h3>
          <div className="grid gap-3 lg:grid-cols-2">
            {approvals.map((a) => (
              <ApprovalCard key={a.id} approval={a} />
            ))}
          </div>
        </section>
      ) : null}

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by status">
        {TABS.map((t) => {
          const count = t.key === "all" ? tasks.length : tasks.filter((x) => x.status === t.key).length;
          return (
            <button
              key={t.key}
              role="tab"
              type="button"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px]",
                tab === t.key ? "border-[color-mix(in_oklab,var(--accent)_50%,transparent)] bg-[color-mix(in_oklab,var(--accent)_12%,transparent)] text-fg" : "border-line text-fg-2 hover:text-fg",
              )}
            >
              {t.label} <span className="font-mono text-[11px] text-fg-3">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="af-card overflow-hidden">
        <div className="hidden grid-cols-[minmax(0,2.2fr)_120px_150px_minmax(140px,1fr)_90px_40px] items-center gap-4 border-b border-line bg-card-2 px-4 py-2.5 md:grid">
          {["Task", "Agents", "Status", "Progress", "Duration", ""].map((h, i) => (
            <div key={i} className="af-label !text-[10.5px]">
              {h}
            </div>
          ))}
        </div>
        {rows.length === 0 ? (
          <div className="px-6 py-14 text-center">
            <p className="text-[14px] font-medium">No runs here</p>
            <p className="mt-1 text-[13px] text-fg-2">Try another filter, or start a task with New Task.</p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {rows.map((t) => {
              const m = EXECUTION_STATUS_META[t.status];
              const pct = t.progress === null ? null : Math.round(t.progress * 100);
              return (
                <li key={t.id}>
                  <Link href={`/tasks/${t.id}`} className="grid gap-3 px-4 py-3.5 transition-colors hover:bg-card-2/60 md:grid-cols-[minmax(0,2.2fr)_120px_150px_minmax(140px,1fr)_90px_40px] md:items-center md:gap-4">
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium text-fg">{t.title}</p>
                      <p className="mt-0.5 truncate text-[12px] text-fg-3">
                        <span className="font-mono">{t.executionId}</span> · {t.stage}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 md:block">
                      <div className="flex -space-x-2">
                        {t.agents.map((a) => (
                          <div key={a} className="rounded-[12px] ring-2 ring-[var(--card)]" title={AGENT_IDENTITIES[a].name}>
                            <AgentGlyph agent={a} size={24} />
                          </div>
                        ))}
                      </div>
                      <span className="md:hidden">
                        <Badge tone={m.tone} live={m.live}>
                          {m.label}
                        </Badge>
                      </span>
                    </div>
                    <div className="hidden md:block">
                      <Badge tone={m.tone} live={m.live}>
                        {m.label}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2">
                      <Progress value={t.progress} tone={t.status === "waiting_approval" ? "warn" : t.status === "failed" ? "err" : t.status === "completed" ? "ok" : "accent"} label={`${t.title} progress`} />
                      <span className="w-9 shrink-0 text-right font-mono text-[12px] text-fg-2">{pct === null ? "—" : `${pct}%`}</span>
                    </div>
                    <div className="hidden text-[12.5px] text-fg-2 md:block">
                      <Elapsed startedSecondsAgo={t.startedSecondsAgo} running={t.status === "running"} />
                    </div>
                    <ArrowRight className="hidden size-4 text-fg-3 md:block" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
