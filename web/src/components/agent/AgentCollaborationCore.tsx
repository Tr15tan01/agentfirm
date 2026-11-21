"use client";

import { useId } from "react";
import { Network } from "lucide-react";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import type { AgentKey } from "@/lib/types";
import { cn } from "@/lib/cn";

export type ParticipantState = "pending" | "active" | "done";

export interface CollaborationParticipant {
  agent: AgentKey;
  state: ParticipantState;
  subtask: string;
}

/**
 * Collaboration variant of the activity core: the orchestrator at the centre,
 * participating agents around it. Edge animation only flows to the agent that
 * the backend reports as currently active.
 */
export function AgentCollaborationCore({
  participants,
  size = 300,
  className,
}: {
  participants: CollaborationParticipant[];
  size?: number;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const W = 300;
  const H = 240;
  const cx = W / 2;
  const cy = H / 2;
  const R = 92;

  const nodes = participants.map((p, i) => {
    const angle = -Math.PI / 2 + (i / participants.length) * Math.PI * 2;
    return { ...p, x: cx + Math.cos(angle) * R * 1.25, y: cy + Math.sin(angle) * R * 0.92 };
  });

  return (
    <div className={cn("relative mx-auto", className)} style={{ width: "100%", maxWidth: size, aspectRatio: `${W} / ${H}` }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 size-full overflow-visible" aria-hidden>
        <defs>
          <radialGradient id={`hub-${uid}`} cx="50%" cy="45%" r="60%">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.9" />
            <stop offset="40%" stopColor="var(--accent-2)" stopOpacity="0.85" />
            <stop offset="100%" stopColor="var(--accent-2)" stopOpacity="0.05" />
          </radialGradient>
          <filter id={`b-${uid}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="8" />
          </filter>
        </defs>

        {/* Peer-to-peer ring (dependencies flow around the ring) */}
        {nodes.map((n, i) => {
          const next = nodes[(i + 1) % nodes.length];
          return (
            <line key={`r${i}`} x1={n.x} y1={n.y} x2={next.x} y2={next.y} stroke="var(--border)" strokeWidth="1" strokeDasharray="2 5" />
          );
        })}

        {/* Hub edges */}
        {nodes.map((n) => {
          const color = TONE_VAR[AGENT_IDENTITIES[n.agent].tone];
          return (
            <g key={`e${n.agent}`}>
              <line x1={cx} y1={cy} x2={n.x} y2={n.y} stroke={n.state === "pending" ? "var(--border)" : color} strokeOpacity={n.state === "done" ? 0.45 : 0.9} strokeWidth={n.state === "active" ? 1.6 : 1} />
              {n.state === "active" ? (
                <line x1={cx} y1={cy} x2={n.x} y2={n.y} stroke="var(--cyan)" strokeWidth="2.2" strokeDasharray="3 9" strokeLinecap="round" className="af-flow" />
              ) : null}
            </g>
          );
        })}

        {/* Hub (orchestrator) */}
        <circle cx={cx} cy={cy} r="30" fill="var(--accent-2)" opacity="0.3" filter={`url(#b-${uid})`} className="af-breathe" />
        <circle cx={cx} cy={cy} r="24" fill={`url(#hub-${uid})`} opacity="0.75" className="af-breathe" />
        <circle cx={cx} cy={cy} r="24" fill="var(--card)" opacity="0.55" />
        <circle cx={cx} cy={cy} r="24" fill="none" stroke="var(--accent-2)" strokeOpacity="0.6" />
        <g className="af-spin-slow">
          <circle cx={cx} cy={cy} r="34" fill="none" stroke="var(--accent-2)" strokeOpacity="0.5" strokeDasharray="2 7" />
        </g>

        {/* Agent nodes */}
        {nodes.map((n) => {
          const color = TONE_VAR[AGENT_IDENTITIES[n.agent].tone];
          const r = n.state === "active" ? 19 : 15;
          return (
            <g key={`n${n.agent}`}>
              {n.state === "active" ? (
                <>
                  <circle cx={n.x} cy={n.y} r={r + 8} fill={color} opacity="0.25" filter={`url(#b-${uid})`} className="af-breathe" />
                  <g className="af-spin-med">
                    <circle cx={n.x} cy={n.y} r={r + 5} fill="none" stroke={color} strokeOpacity="0.8" strokeDasharray="10 6" />
                  </g>
                </>
              ) : null}
              <circle cx={n.x} cy={n.y} r={r} fill="var(--card)" stroke={n.state === "pending" ? "var(--border-strong)" : color} strokeWidth={n.state === "active" ? 1.6 : 1} />
              {n.state === "done" ? <circle cx={n.x + r * 0.72} cy={n.y - r * 0.72} r="4.5" fill="var(--ok)" stroke="var(--card)" strokeWidth="1.5" /> : null}
            </g>
          );
        })}
      </svg>

      {/* Icons layered as HTML for crisp rendering */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute grid place-items-center" style={{ left: `${(cx / W) * 100}%`, top: `${(cy / H) * 100}%`, transform: "translate(-50%,-50%)" }}>
          <Network className="size-4 text-accent-2" strokeWidth={1.8} />
        </div>
        {nodes.map((n) => {
          const id = AGENT_IDENTITIES[n.agent];
          const Icon = id.icon;
          return (
            <div
              key={`i${n.agent}`}
              className="absolute flex flex-col items-center"
              style={{ left: `${(n.x / W) * 100}%`, top: `${(n.y / H) * 100}%`, transform: "translate(-50%,-50%)" }}
            >
              <Icon
                className={cn(n.state === "active" ? "size-4" : "size-3.5")}
                style={{ color: n.state === "pending" ? "var(--fg-3)" : TONE_VAR[id.tone] }}
                strokeWidth={1.8}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
