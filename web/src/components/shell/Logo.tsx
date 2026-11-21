import { useId } from "react";
import { cn } from "@/lib/cn";

/** AgentFirm mark: three coordinated agent nodes around an orchestrator core. */
export function LogoMark({ className }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <defs>
        <linearGradient id={`lg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--accent)" />
          <stop offset="100%" stopColor="var(--accent-2)" />
        </linearGradient>
      </defs>
      <rect x="0.5" y="0.5" width="31" height="31" rx="9" fill="var(--card-2)" stroke={`url(#lg-${id})`} strokeOpacity="0.9" />
      <g stroke={`url(#lg-${id})`} strokeWidth="1.4" strokeLinecap="round">
        <line x1="16" y1="16" x2="16" y2="8.5" />
        <line x1="16" y1="16" x2="9.5" y2="20.5" />
        <line x1="16" y1="16" x2="22.5" y2="20.5" />
      </g>
      <circle cx="16" cy="8.5" r="2.3" fill="var(--accent)" />
      <circle cx="9.5" cy="20.5" r="2.3" fill="var(--cyan)" />
      <circle cx="22.5" cy="20.5" r="2.3" fill="var(--accent-2)" />
      <circle cx="16" cy="16" r="3.2" fill="var(--fg)" />
    </svg>
  );
}

export function Wordmark({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {collapsed ? null : (
        <div className="leading-none">
          <div className="text-[15px] font-semibold tracking-tight">AgentFirm</div>
          <div className="mt-1 text-[11px] text-fg-3">Your AI team. Ready to work.</div>
        </div>
      )}
    </div>
  );
}
