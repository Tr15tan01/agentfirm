"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { ArrowUpRight, Clock } from "lucide-react";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import type { AgentSummary } from "@/lib/types";
import { cn } from "@/lib/cn";
import { AGENT_STATUS_META, Badge } from "@/components/ui/primitives";
import { TimeAgo } from "@/components/ui/time";

export function AgentGlyph({ agent, live, size = 44 }: { agent: AgentSummary["key"]; live?: boolean; size?: number }) {
  const id = AGENT_IDENTITIES[agent];
  const Icon = id.icon;
  const color = TONE_VAR[id.tone];
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      {live ? (
        <svg viewBox="0 0 44 44" className="af-spin-med absolute -inset-1 size-[calc(100%+8px)]" aria-hidden>
          <circle cx="22" cy="22" r="20.5" fill="none" stroke={color} strokeWidth="1.2" strokeDasharray="22 10 4 10" strokeLinecap="round" />
        </svg>
      ) : null}
      <div
        className="grid size-full place-items-center rounded-[12px] border"
        style={{
          borderColor: `color-mix(in oklab, ${color} 32%, var(--border))`,
          background: `radial-gradient(120% 120% at 30% 20%, color-mix(in oklab, ${color} 22%, transparent), color-mix(in oklab, ${color} 4%, var(--card)))`,
        }}
      >
        <Icon className="size-[45%]" style={{ color }} strokeWidth={1.7} />
      </div>
    </div>
  );
}

export function AgentCard({ agent, index = 0 }: { agent: AgentSummary; index?: number }) {
  const meta = AGENT_STATUS_META[agent.status];
  const identity = AGENT_IDENTITIES[agent.key];
  const working = agent.status === "working";
  const live = meta.live;

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.04, ease: "easeOut" }}
      className={cn(
        "af-card group relative flex flex-col p-4 transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-line-strong",
        working && (identity.tone === "violet" ? "af-live-violet" : "af-live"),
        working && "af-sweep",
      )}
    >
      <div className="flex items-start gap-3">
        <AgentGlyph agent={agent.key} live={working} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-semibold tracking-tight">{agent.name}</h3>
          <p className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-fg-2">{identity.description}</p>
        </div>
      </div>

      <div className="mt-4 min-h-[52px] rounded-[10px] border border-line bg-card-2 px-3 py-2">
        <div className="af-label !text-[10px]">{agent.currentTask ? "Current task" : "Queue"}</div>
        <p className={cn("mt-1 line-clamp-1 text-[13px]", agent.currentTask ? "text-fg" : "text-fg-3")}>
          {agent.currentTask ?? "Idle — ready for a new task"}
        </p>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <Badge tone={meta.tone} live={live}>
          {meta.label}
        </Badge>
        <span className="flex items-center gap-1 text-[12px] text-fg-3">
          <Clock className="size-3" aria-hidden />
          <TimeAgo secondsAgo={agent.lastActiveSecondsAgo} />
        </span>
      </div>

      <Link
        href={`/agents/${agent.key}`}
        className="mt-3 flex h-8 items-center justify-center gap-1.5 rounded-[9px] border border-line text-[13px] font-medium text-fg-2 transition-colors hover:border-line-strong hover:bg-card-2 hover:text-fg"
      >
        Open agent <ArrowUpRight className="size-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
      </Link>
    </motion.article>
  );
}
