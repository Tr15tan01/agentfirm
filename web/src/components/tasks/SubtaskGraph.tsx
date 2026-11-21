"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Subtask } from "@/lib/types";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { StepIcon } from "./ExecutionParts";

const NODE_H = 74;
const ROW_GAP = 16;
const MIN_W = 128;
const MAX_W = 210;

/** Layered DAG of subtasks: columns = dependency depth, edges = dependencies. */
export function SubtaskGraph({ subtasks, className }: { subtasks: Subtask[]; className?: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(900);
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setAvail(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => {
    const byId = new Map(subtasks.map((s) => [s.id, s]));
    const depth = new Map<string, number>();
    const visit = (id: string, seen: Set<string>): number => {
      if (depth.has(id)) return depth.get(id)!;
      if (seen.has(id)) return 0; // cycle guard — orchestrator plans are DAGs
      seen.add(id);
      const s = byId.get(id);
      const d = s && s.dependsOn.length ? 1 + Math.max(...s.dependsOn.map((p) => visit(p, seen))) : 0;
      depth.set(id, d);
      return d;
    };
    subtasks.forEach((s) => visit(s.id, new Set()));
    const cols: Subtask[][] = [];
    subtasks.forEach((s) => {
      const d = depth.get(s.id) ?? 0;
      (cols[d] ??= []).push(s);
    });
    // Fit the container when possible; otherwise fall back to horizontal scroll.
    const n = cols.length;
    const COL_GAP = n > 1 ? Math.max(20, Math.min(64, (avail - n * MIN_W) / (n - 1))) : 0;
    const NODE_W = Math.max(MIN_W, Math.min(MAX_W, (avail - (n - 1) * COL_GAP) / n));
    const maxRows = Math.max(1, ...cols.map((c) => c.length)); // ≥1: an empty plan still lays out
    const height = maxRows * NODE_H + (maxRows - 1) * ROW_GAP;
    const pos = new Map<string, { x: number; y: number }>();
    cols.forEach((col, ci) => {
      const colH = col.length * NODE_H + (col.length - 1) * ROW_GAP;
      const offset = (height - colH) / 2;
      col.forEach((s, ri) => pos.set(s.id, { x: ci * (NODE_W + COL_GAP), y: offset + ri * (NODE_H + ROW_GAP) }));
    });
    return { pos, width: n * NODE_W + (n - 1) * COL_GAP, height, byId, NODE_W };
  }, [subtasks, avail]);
  const NODE_W = layout.NODE_W;

  return (
    <div ref={boxRef} className={cn("overflow-x-auto pb-2", className)}>
      <div className="relative mx-auto" style={{ width: layout.width, height: layout.height }} role="list" aria-label="Subtask dependency graph">
        <svg className="absolute inset-0 overflow-visible" width={layout.width} height={layout.height} aria-hidden>
          {subtasks.flatMap((s) =>
            s.dependsOn.map((dep) => {
              const a = layout.pos.get(dep);
              const b = layout.pos.get(s.id);
              if (!a || !b) return null;
              const x1 = a.x + NODE_W;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const mx = (x1 + x2) / 2;
              const d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
              const parent = layout.byId.get(dep);
              const flowing = s.status === "running" && parent?.status === "done";
              return (
                <g key={`${dep}-${s.id}`}>
                  <path d={d} fill="none" stroke={parent?.status === "done" ? "var(--border-strong)" : "var(--border)"} strokeWidth="1.5" />
                  {flowing ? <path d={d} fill="none" stroke="var(--cyan)" strokeWidth="2" strokeDasharray="3 9" strokeLinecap="round" className="af-flow" /> : null}
                </g>
              );
            }),
          )}
        </svg>
        {subtasks.map((s) => {
          const p = layout.pos.get(s.id)!;
          const id = AGENT_IDENTITIES[s.agent];
          const Icon = id.icon;
          const active = s.status === "running";
          return (
            <div
              key={s.id}
              role="listitem"
              className={cn(
                "absolute flex flex-col justify-center rounded-[12px] border bg-card px-3 shadow-[var(--shadow)]",
                active && "af-live",
                s.status === "waiting" && "border-[color-mix(in_oklab,var(--warn)_50%,var(--border))]",
                s.status === "pending" && "opacity-75",
                !active && s.status !== "waiting" && "border-line",
              )}
              style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H }}
              title={[s.stage, s.origin && s.origin !== "orchestrator" ? `Handed off by ${s.origin}` : ""].filter(Boolean).join(" · ") || undefined}
            >
              <div className="flex items-start gap-2">
                <StepIcon status={s.status} className="mt-px size-3.5" />
                <span className="line-clamp-2 text-[12.5px] font-medium leading-tight">{s.title}</span>
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <Icon className="size-3.5 shrink-0" style={{ color: TONE_VAR[id.tone] }} />
                {NODE_W >= 170 ? <span className="truncate text-[11.5px] text-fg-3">{id.shortName}</span> : <span className="sr-only">{id.shortName}</span>}
                <div className="ml-auto h-1 w-12 shrink-0 overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]">
                  {s.status === "done" ? (
                    <div className="h-full w-full rounded-full" style={{ background: "var(--ok)" }} />
                  ) : s.progress === null ? (
                    s.status === "running" ? <div className="af-indeterminate h-full w-2/5 rounded-full bg-cyan" /> : null
                  ) : (
                    <div className="h-full rounded-full" style={{ width: `${s.progress * 100}%`, background: s.status === "waiting" ? "var(--warn)" : "var(--accent)" }} />
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
