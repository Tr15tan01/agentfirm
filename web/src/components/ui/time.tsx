"use client";


import { CLIENT_ORIGIN, useNow } from "@/lib/stores";

/*
 * Time is client-only: rendering clocks on the server would be wrong for the
 * user's time zone and break static prerendering (Next 16 cacheComponents).
 * Until hydrated we render a stable placeholder.
 */

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatAgo(seconds: number): string {
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

/** Live elapsed timer. `startedSecondsAgo` is relative to mount time. */
export function Elapsed({ startedSecondsAgo, running = true }: { startedSecondsAgo: number; running?: boolean }) {
  const now = useNow();
  if (now === null) return <span className="font-mono tabular-nums">--:--</span>;
  const seconds = startedSecondsAgo + (running ? (now - CLIENT_ORIGIN) / 1000 : 0);
  return <span className="font-mono tabular-nums">{formatDuration(seconds)}</span>;
}

export function TimeAgo({ secondsAgo }: { secondsAgo: number }) {
  const now = useNow();
  if (now === null) return <span>—</span>;
  return <span>{formatAgo(secondsAgo + (now - CLIENT_ORIGIN) / 1000)}</span>;
}

export function Greeting() {
  const now = useNow();
  const h = now === null ? 9 : new Date(now).getHours();
  return <>Good {h < 12 ? "morning" : h < 18 ? "afternoon" : "evening"}.</>;
}
