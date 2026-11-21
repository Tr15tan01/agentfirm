"use client";

import { useId, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { AlertTriangle, Check, RotateCcw, FolderOpen } from "lucide-react";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import type { AgentKey, CoreState } from "@/lib/types";
import { cn } from "@/lib/cn";
import { Badge, Button, Progress } from "@/components/ui/primitives";
import { Elapsed } from "@/components/ui/time";

export interface AgentActivityCoreProps {
  agent: AgentKey;
  state: CoreState;
  /** Current task title (working / completed / failed). */
  task?: string | null;
  /** 0–1 from backend execution events, or null when unknown → indeterminate. */
  progress?: number | null;
  /** Seconds since the execution started (relative, resolved on mount). */
  startedSecondsAgo?: number;
  /** Error summary for the failed state. */
  error?: string;
  size?: number;
  showDetails?: boolean;
  onRetry?: () => void;
  onOpenDeliverables?: () => void;
  className?: string;
}

const STATE_LABEL: Record<CoreState, { label: string; tone: "muted" | "cyan" | "violet" | "ok" | "err" }> = {
  idle: { label: "Available", tone: "muted" },
  working: { label: "Working", tone: "cyan" },
  collaborating: { label: "Collaborating", tone: "violet" },
  completed: { label: "Completed", tone: "ok" },
  failed: { label: "Failed", tone: "err" },
};

const PARTICLES = Array.from({ length: 10 }, (_, i) => {
  const angle = (i / 10) * Math.PI * 2 + (i % 2) * 0.3;
  const r = 88 + (i % 3) * 8;
  return { dx: Math.cos(angle) * r, dy: Math.sin(angle) * r, delay: (i * 0.29) % 2.8, size: 1.4 + (i % 3) * 0.5 };
});

/**
 * The living representation of an agent's real activity.
 * Never animate progress that did not come from the backend: pass `progress={null}`
 * and the ring switches to an indeterminate comet instead of a number.
 */
export function AgentActivityCore({
  agent,
  state,
  task,
  progress = null,
  startedSecondsAgo,
  error,
  size = 240,
  showDetails = true,
  onRetry,
  onOpenDeliverables,
  className,
}: AgentActivityCoreProps) {
  const uid = useId().replace(/:/g, "");
  const reduce = useReducedMotion();
  const identity = AGENT_IDENTITIES[agent];
  const Icon = identity.icon;

  const tone =
    state === "failed" ? "var(--err)" : state === "completed" ? "var(--ok)" : state === "collaborating" ? "var(--accent-2)" : TONE_VAR[identity.tone];
  const active = state === "working" || state === "collaborating";
  const pct = progress === null ? null : Math.round(Math.min(1, Math.max(0, progress)) * 100);

  const R_PROGRESS = 92;
  const C = 2 * Math.PI * R_PROGRESS;
  const arcFraction = state === "completed" ? 1 : pct === null ? 0 : pct / 100;

  let center: ReactNode;
  if (state === "failed") center = <AlertTriangle className="size-[22%] text-err" strokeWidth={1.75} />;
  else if (state === "completed") center = <Check className="size-[24%] text-ok" strokeWidth={2} />;
  else if (state === "working" && pct !== null)
    center = (
      <span className="font-mono font-medium tabular-nums text-fg" style={{ fontSize: size * 0.11 }}>
        {pct}
        <span className="text-fg-2" style={{ fontSize: size * 0.06 }}>%</span>
      </span>
    );
  else center = <Icon className="size-[20%]" style={{ color: tone }} strokeWidth={1.6} />;

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 240 240" className="absolute inset-0 size-full overflow-visible" aria-hidden>
          <defs>
            <radialGradient id={`core-${uid}`} cx="50%" cy="42%" r="60%">
              <stop offset="0%" stopColor="#ffffff" stopOpacity={state === "failed" ? 0.35 : 0.95} />
              <stop offset="35%" stopColor={tone} stopOpacity="0.9" />
              <stop offset="100%" stopColor={tone} stopOpacity="0.05" />
            </radialGradient>
            <radialGradient id={`halo-${uid}`} cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={tone} stopOpacity="0.35" />
              <stop offset="60%" stopColor={tone} stopOpacity="0.08" />
              <stop offset="100%" stopColor={tone} stopOpacity="0" />
            </radialGradient>
            <linearGradient id={`arc-${uid}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--accent)" />
              <stop offset="55%" stopColor="var(--cyan)" />
              <stop offset="100%" stopColor="var(--accent-2)" />
            </linearGradient>
            <filter id={`blur-${uid}`} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="6" />
            </filter>
          </defs>

          {/* Soft halo */}
          <circle cx="120" cy="120" r="112" fill={`url(#halo-${uid})`} className={cn(state !== "failed" && "af-breathe")} />

          {/* Base ring */}
          <circle cx="120" cy="120" r={R_PROGRESS} fill="none" stroke="var(--border)" strokeWidth="1.5" opacity={0.9} />

          {/* Outer energy ring — rotating dashes when active */}
          <g className={cn(active && "af-spin-slow")} opacity={active ? 0.75 : 0.3}>
            <circle cx="120" cy="120" r="106" fill="none" stroke={tone} strokeWidth="1" strokeDasharray={active ? "2 9" : "1 6"} strokeLinecap="round" />
            {active ? (
              <>
                <circle cx="120" cy="14" r="2.6" fill={tone} />
                <circle cx="226" cy="120" r="1.8" fill="var(--cyan)" />
                <circle cx="45" cy="195" r="2" fill="var(--accent-2)" />
              </>
            ) : null}
          </g>

          {/* Inner counter-rotating ring */}
          {active ? (
            <g className="af-spin-rev" opacity={0.55}>
              <circle cx="120" cy="120" r="76" fill="none" stroke={tone} strokeWidth="1" strokeDasharray="18 10 4 10" />
            </g>
          ) : (
            <circle cx="120" cy="120" r="76" fill="none" stroke="var(--border)" strokeWidth="1" strokeDasharray="2 6" opacity={0.7} />
          )}

          {/* Progress arc — real progress, or indeterminate comet */}
          {state === "working" && pct === null ? (
            <g className="af-spin-med">
              <circle
                cx="120"
                cy="120"
                r={R_PROGRESS}
                fill="none"
                stroke={`url(#arc-${uid})`}
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray={`${C * 0.22} ${C}`}
              />
            </g>
          ) : arcFraction > 0 ? (
            <motion.circle
              cx="120"
              cy="120"
              r={R_PROGRESS}
              fill="none"
              stroke={state === "completed" ? "var(--ok)" : `url(#arc-${uid})`}
              strokeWidth="3"
              strokeLinecap="round"
              transform="rotate(-90 120 120)"
              strokeDasharray={C}
              initial={{ strokeDashoffset: C }}
              animate={{ strokeDashoffset: C * (1 - arcFraction) }}
              transition={{ duration: reduce ? 0 : 0.9, ease: [0.22, 1, 0.36, 1] }}
            />
          ) : null}

          {/* Failed: broken ring */}
          {state === "failed" ? (
            <circle cx="120" cy="120" r={R_PROGRESS} fill="none" stroke="var(--err)" strokeWidth="2" strokeDasharray="26 8" opacity={0.85} />
          ) : null}

          {/* Particles flowing into the core while working */}
          {active
            ? PARTICLES.map((p, i) => (
                <circle
                  key={i}
                  cx="120"
                  cy="120"
                  r={p.size}
                  fill={i % 3 === 0 ? "var(--cyan)" : tone}
                  className="af-particle"
                  style={{ ["--dx" as string]: `${p.dx}px`, ["--dy" as string]: `${p.dy}px`, animationDelay: `${p.delay}s` }}
                />
              ))
            : null}

          {/* Core glow + orb */}
          <circle cx="120" cy="120" r="44" fill={tone} opacity={state === "failed" ? 0.12 : 0.28} filter={`url(#blur-${uid})`} className={cn(state !== "failed" && "af-breathe")} />
          <circle
            cx="120"
            cy="120"
            r="40"
            fill={`url(#core-${uid})`}
            opacity={state === "failed" ? 0.35 : state === "idle" ? 0.55 : 0.75}
            className={cn(state !== "failed" && "af-breathe")}
          />
          <circle cx="120" cy="120" r="40" fill="var(--card)" opacity={state === "working" && pct !== null ? 0.72 : 0.5} />
          <circle cx="120" cy="120" r="40" fill="none" stroke={tone} strokeOpacity="0.5" strokeWidth="1" />
        </svg>

        {/* Center content */}
        <div className="absolute inset-0 grid place-items-center">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={`${state}-${pct === null ? "i" : "p"}`}
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.85 }}
              transition={{ duration: reduce ? 0 : 0.25 }}
              className="grid size-full place-items-center"
            >
              {center}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {showDetails ? (
        <div className="mt-4 flex w-full max-w-[300px] flex-col items-center text-center">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold tracking-tight">{identity.name}</span>
          </div>
          <div className="mt-2">
            <Badge tone={STATE_LABEL[state].tone} live={active}>
              {STATE_LABEL[state].label}
            </Badge>
          </div>
          {task ? <p className="mt-3 line-clamp-2 text-[13px] leading-snug text-fg-2">{task}</p> : null}
          {state === "idle" ? <p className="mt-3 text-[13px] text-fg-2">Ready for a new task.</p> : null}

          {state === "working" ? (
            <div className="mt-4 w-full">
              <Progress value={progress} label={`${identity.name} progress`} />
              <div className="mt-2 flex items-center justify-between text-[12px] text-fg-3">
                <span className="font-mono">{pct === null ? "Estimating…" : `${pct}% · from plan`}</span>
                {startedSecondsAgo !== undefined ? (
                  <span>
                    Elapsed <Elapsed startedSecondsAgo={startedSecondsAgo} />
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}

          {state === "failed" ? (
            <div className="mt-3 w-full">
              {error ? <p className="rounded-lg border border-[color-mix(in_oklab,var(--err)_30%,transparent)] bg-[color-mix(in_oklab,var(--err)_8%,transparent)] px-3 py-2 text-left text-[12.5px] text-fg-2">{error}</p> : null}
              <div className="mt-3 flex justify-center gap-2">
                <Button size="sm" variant="danger" onClick={onRetry}>
                  <RotateCcw className="size-3.5" /> Retry from last step
                </Button>
                <Button size="sm" variant="ghost">View history</Button>
              </div>
            </div>
          ) : null}

          {state === "completed" ? (
            <Button size="sm" variant="secondary" className="mt-4" onClick={onOpenDeliverables}>
              <FolderOpen className="size-3.5" /> Open deliverables
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
