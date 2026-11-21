import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/cn";
import type { AgentStatus, ExecutionStatus } from "@/lib/types";

/* ── Button ─────────────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "text-white bg-[linear-gradient(135deg,var(--accent),color-mix(in_oklab,var(--accent)_60%,var(--accent-2)))] shadow-[0_6px_20px_-8px_var(--accent)] hover:brightness-110",
  secondary: "bg-card-2 text-fg border border-line hover:border-line-strong hover:bg-card",
  ghost: "text-fg-2 hover:text-fg hover:bg-card-2",
  danger: "bg-[color-mix(in_oklab,var(--err)_14%,transparent)] text-err border border-[color-mix(in_oklab,var(--err)_35%,transparent)] hover:bg-[color-mix(in_oklab,var(--err)_22%,transparent)]",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[10px] font-medium whitespace-nowrap transition-[background,color,border-color,filter,box-shadow] duration-150 disabled:opacity-50 disabled:pointer-events-none",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-3.5 text-sm",
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

/* ── Card ───────────────────────────────────────────────────── */

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("af-card", className)} {...props} />;
}

export function SectionHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-[13px] text-fg-2">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/* ── Status ─────────────────────────────────────────────────── */

type Tone = "ok" | "warn" | "err" | "accent" | "violet" | "muted" | "cyan";

const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
  accent: "var(--accent)",
  violet: "var(--accent-2)",
  cyan: "var(--cyan)",
  muted: "var(--fg-3)",
};

export const AGENT_STATUS_META: Record<AgentStatus, { label: string; tone: Tone; live: boolean }> = {
  available: { label: "Available", tone: "muted", live: false },
  working: { label: "Working", tone: "cyan", live: true },
  waiting_approval: { label: "Waiting for approval", tone: "warn", live: true },
  paused: { label: "Paused", tone: "muted", live: false },
  completed: { label: "Completed", tone: "ok", live: false },
  failed: { label: "Failed", tone: "err", live: false },
};

export const EXECUTION_STATUS_META: Record<ExecutionStatus, { label: string; tone: Tone; live: boolean }> = {
  queued: { label: "Queued", tone: "muted", live: false },
  running: { label: "Running", tone: "cyan", live: true },
  waiting_approval: { label: "Needs approval", tone: "warn", live: true },
  paused: { label: "Paused", tone: "muted", live: false },
  completed: { label: "Completed", tone: "ok", live: false },
  failed: { label: "Failed", tone: "err", live: false },
  cancelled: { label: "Cancelled", tone: "muted", live: false },
};

export function StatusDot({ tone, live }: { tone: Tone; live?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-1.5 shrink-0 rounded-full", live && "af-pulse-dot")}
      style={{ background: TONE_COLOR[tone], color: TONE_COLOR[tone] }}
    />
  );
}

export function Badge({ tone = "muted", live, children, className }: { tone?: Tone; live?: boolean; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-[12px] font-medium whitespace-nowrap",
        className,
      )}
      style={{
        color: tone === "muted" ? "var(--fg-2)" : TONE_COLOR[tone],
        borderColor: `color-mix(in oklab, ${TONE_COLOR[tone]} 30%, transparent)`,
        background: `color-mix(in oklab, ${TONE_COLOR[tone]} 9%, transparent)`,
      }}
    >
      <StatusDot tone={tone} live={live} />
      {children}
    </span>
  );
}

export function DemoBadge({ className }: { className?: string }) {
  return (
    <span
      title="Demonstration data — not connected to the execution engine yet"
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-md border border-dashed border-line-strong px-1.5 font-mono text-[10.5px] uppercase tracking-wider text-fg-3",
        className,
      )}
    >
      <FlaskConical className="size-3" aria-hidden />
      Demo data
    </span>
  );
}

/* ── Progress ───────────────────────────────────────────────── */

/**
 * Progress bar. Pass `value={null}` when the backend cannot determine progress:
 * it renders an indeterminate animation instead of a misleading percentage.
 */
export function Progress({
  value,
  tone = "accent",
  className,
  label,
}: {
  value: number | null;
  tone?: "accent" | "warn" | "ok" | "err";
  className?: string;
  label?: string;
}) {
  const color = TONE_COLOR[tone];
  const pct = value === null ? null : Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct ?? undefined}
      aria-valuetext={pct === null ? "In progress, completion unknown" : `${pct}%`}
      className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]", className)}
    >
      {pct === null ? (
        <div
          className="af-indeterminate absolute inset-y-0 left-0 w-2/5 rounded-full"
          style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }}
        />
      ) : (
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out"
          style={{
            width: `${pct}%`,
            background: tone === "accent" ? "linear-gradient(90deg, var(--accent), var(--cyan))" : color,
          }}
        />
      )}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line bg-card-2 px-1 font-mono text-[10.5px] text-fg-3">
      {children}
    </kbd>
  );
}
