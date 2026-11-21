"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "motion/react";
import { ArrowUpRight, Cpu, Lock, Plus, Search, Wrench } from "lucide-react";
import type { AgentProfile, AgentStatus } from "@/lib/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { AGENT_STATUS_META, Badge, DemoBadge, EXECUTION_STATUS_META, StatusDot } from "@/components/ui/primitives";
import { AgentGlyph } from "@/components/agent/AgentCard";
import { formatDuration, TimeAgo } from "@/components/ui/time";
import { NewTaskDialog } from "@/components/tasks/NewTaskDialog";

const FILTERS: { key: "all" | AgentStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "working", label: "Working" },
  { key: "waiting_approval", label: "Needs approval" },
  { key: "available", label: "Available" },
  { key: "completed", label: "Completed" },
];

const nf = new Intl.NumberFormat("en-US");

export function AgentDirectory({ profiles, demo }: { profiles: AgentProfile[]; demo: boolean }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return profiles.filter(
      (p) =>
        (filter === "all" || p.status === filter) &&
        (!needle || [p.name, p.mission, ...p.capabilities, ...p.tools.map((t) => t.label)].join(" ").toLowerCase().includes(needle)),
    );
  }, [profiles, q, filter]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[22px] font-semibold tracking-tight">Agent directory</h2>
            {demo ? <DemoBadge /> : null}
          </div>
          <p className="mt-1 max-w-2xl text-[14px] text-fg-2">
            Specialised agents share one execution engine, model gateway and tool registry — each with its own mission, tools, permissions and limits.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex h-9 w-full items-center gap-2 rounded-[10px] border border-line bg-card-2 px-3 text-[13px] focus-within:border-accent sm:w-64">
            <Search className="size-4 text-fg-3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search capabilities, tools…" className="w-full bg-transparent outline-none placeholder:text-fg-3" aria-label="Search agents" />
          </label>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter agents by status">
        {FILTERS.map((f) => {
          const count = f.key === "all" ? profiles.length : profiles.filter((p) => p.status === f.key).length;
          return (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition-colors",
                filter === f.key ? "border-[color-mix(in_oklab,var(--accent)_50%,transparent)] bg-[color-mix(in_oklab,var(--accent)_12%,transparent)] text-fg" : "border-line text-fg-2 hover:text-fg",
              )}
            >
              {f.label}
              <span className="font-mono text-[11px] text-fg-3">{count}</span>
            </button>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <div className="af-card grid place-items-center px-6 py-16 text-center">
          <Search className="size-6 text-fg-3" />
          <p className="mt-3 text-[14px] font-medium">No agents match “{q}”</p>
          <button type="button" onClick={() => { setQ(""); setFilter("all"); }} className="mt-2 text-[13px] text-accent hover:underline">
            Clear filters
          </button>
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-2">
          {shown.map((p, i) => (
            <AgentProfileCard key={p.key} p={p} index={i} />
          ))}
          <div className="af-card flex min-h-[200px] flex-col items-center justify-center border-dashed p-6 text-center">
            <span className="grid size-11 place-items-center rounded-[12px] border border-dashed border-line-strong">
              <Plus className="size-5 text-fg-3" />
            </span>
            <p className="mt-3 text-[14px] font-medium">Custom agents</p>
            <p className="mt-1 max-w-sm text-[12.5px] text-fg-2">
              Admins publish new agents from the registry — manifest, tools, model capabilities and approval policy. No redesign required.
            </p>
            <Badge className="mt-3">Phase 6 · Admin</Badge>
          </div>
        </div>
      )}
    </div>
  );
}

function AgentProfileCard({ p, index }: { p: AgentProfile; index: number }) {
  const meta = AGENT_STATUS_META[p.status];
  const id = AGENT_IDENTITIES[p.key];
  const live = p.status === "working";

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.04 }}
      className={cn("af-card flex flex-col p-5", live && (id.tone === "violet" ? "af-live-violet" : "af-live"))}
    >
      <div className="flex items-start gap-4">
        <AgentGlyph agent={p.key} live={live} size={52} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[16px] font-semibold tracking-tight">{p.name}</h3>
            <span className="rounded-md border border-line px-1.5 font-mono text-[11px] text-fg-3">{p.version}</span>
          </div>
          <p className="mt-1 text-[13px] leading-snug text-fg-2">{p.mission}</p>
        </div>
        <Badge tone={meta.tone} live={meta.live} className="hidden sm:inline-flex">
          {meta.label}
        </Badge>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {p.capabilities.map((c) => (
          <span key={c} className="rounded-md border border-line bg-card-2 px-2 py-0.5 text-[12px] text-fg-2">
            {c}
          </span>
        ))}
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div>
          <div className="af-label mb-2 flex items-center gap-1.5 !text-[10.5px]">
            <Wrench className="size-3" /> Tools
          </div>
          <ul className="space-y-1">
            {p.tools.map((t) => (
              <li key={t.key} className="flex items-center justify-between gap-2 text-[12.5px]">
                <span className="truncate text-fg-2">{t.label}</span>
                {t.approval === "require_approval" ? (
                  <span className="flex shrink-0 items-center gap-1 text-[11px] text-warn" title="Requires human approval">
                    <Lock className="size-3" /> Approval
                  </span>
                ) : (
                  <span className="shrink-0 font-mono text-[11px] text-fg-3">{t.key}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="af-label mb-2 flex items-center gap-1.5 !text-[10.5px]">
            <Cpu className="size-3" /> Models (via gateway)
          </div>
          <ul className="space-y-1">
            {p.models.map((m) => (
              <li key={m.capability} className="flex items-center justify-between gap-2 text-[12.5px]">
                <span className="capitalize text-fg-2">{m.capability.replace("_", " ")}</span>
                <span className="truncate font-mono text-[11.5px] text-fg">{m.model}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { k: "Requests / mo", v: nf.format(p.usage.requestsMonth) },
          { k: "Success rate", v: `${Math.round(p.usage.successRate * 100)}%` },
          { k: "Avg duration", v: formatDuration(p.usage.avgDurationSec) },
          { k: "Credits / mo", v: nf.format(p.usage.creditsMonth) },
        ].map((s) => (
          <div key={s.k} className="rounded-[10px] border border-line bg-card-2 px-3 py-2">
            <dt className="text-[11px] text-fg-3">{s.k}</dt>
            <dd className="mt-0.5 font-mono text-[15px] text-fg">{s.v}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-4">
        <div className="af-label mb-1.5 !text-[10.5px]">Recent executions</div>
        <ul className="divide-y divide-[var(--border)]">
          {p.recentExecutions.slice(0, 3).map((e) => {
            const em = EXECUTION_STATUS_META[e.status];
            return (
              <li key={e.id}>
                <Link href={`/tasks/${e.taskId}`} className="flex items-center gap-2 py-1.5 text-[12.5px] hover:text-fg">
                  <StatusDot tone={em.tone} live={em.live} />
                  <span className="min-w-0 flex-1 truncate text-fg-2 hover:text-fg">{e.title}</span>
                  <span className="shrink-0 text-[11.5px] text-fg-3">{e.finishedSecondsAgo === 0 ? em.label : <TimeAgo secondsAgo={e.finishedSecondsAgo} />}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="mt-auto flex gap-2 pt-4">
        <Link
          href={`/agents/${p.key}`}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-[10px] bg-[linear-gradient(135deg,var(--accent),color-mix(in_oklab,var(--accent)_60%,var(--accent-2)))] text-[13px] font-medium text-white hover:brightness-110"
        >
          Open workspace <ArrowUpRight className="size-3.5" />
        </Link>
        <NewTaskDialog
          trigger={
            <button type="button" className="flex h-9 items-center gap-1.5 rounded-[10px] border border-line px-3 text-[13px] font-medium text-fg-2 hover:border-line-strong hover:text-fg">
              <Plus className="size-3.5" /> Task
            </button>
          }
        />
      </div>
    </motion.article>
  );
}
