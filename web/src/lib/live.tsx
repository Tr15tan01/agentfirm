"use client";

/**
 * Live-data plumbing (NEXT_PUBLIC_AGENTFIRM_API=http).
 *
 * Live screens load in the browser through the BFF, which owns the session cookies and
 * refreshes tokens; server components can't (the refresh cookie is scoped to /api by
 * design, ADR 0001/0004). `useResource` suspends on a cached promise; `refresh()` drops
 * cached entries and re-renders subscribers. `LiveBoundary` renders nothing data-bound
 * until hydration, then shows a fallback while loading and a recoverable error card.
 */
import { Component, Suspense, use, useSyncExternalStore, type ReactNode } from "react";
import { AlertTriangle, LogIn, RotateCcw } from "lucide-react";
import { ApiError } from "@/lib/api/http";

export { LIVE_DATA } from "./mode";

interface Entry {
  /** What renders read: pending on first load, then an already-fulfilled promise. */
  current: Promise<unknown>;
  load: () => Promise<unknown>;
  loaded: boolean;
}

const cache = new Map<string, Entry>();
const listeners = new Set<() => void>();
let version = 0;

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  version++;
  listeners.forEach((l) => l());
}

/** A promise React reads synchronously (status pre-set), so `use()` never suspends on it. */
function fulfilled<T>(value: T): Promise<T> {
  const p = Promise.resolve(value) as Promise<T> & { status?: string; value?: T };
  p.status = "fulfilled";
  p.value = value;
  return p;
}

function start(key: string, load: () => Promise<unknown>, previous?: Entry): Entry {
  const next = load();
  const entry: Entry = previous ? { ...previous, load } : { current: next, load, loaded: false };
  cache.set(key, entry);
  next.then(
    (v) => {
      entry.current = fulfilled(v);
      entry.loaded = true;
      if (previous) notify(); // background revalidation finished: swap the data in
    },
    () => undefined, // first-load errors surface through use(); revalidation errors keep the old data
  );
  return entry;
}

/**
 * Re-fetch cached data (all of it, or keys starting with `prefix`). Views that already have
 * data keep showing it until the new data arrives (stale-while-revalidate, no skeleton flash).
 */
export function refresh(prefix?: string) {
  for (const [k, e] of [...cache.entries()]) {
    if (prefix && !k.startsWith(prefix)) continue;
    if (e.loaded) start(k, e.load, e);
    else cache.delete(k);
  }
  notify();
}

/** Always calls `use()` exactly once, so the hook order is identical on every render. */
export function useResource<T>(key: string, load: () => Promise<T>): T {
  useSyncExternalStore(subscribe, () => version, () => version);
  const entry = cache.get(key) ?? start(key, load);
  return use(entry.current as Promise<T>);
}

const noop = () => () => {};
export function useHydrated(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}

class Catch extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const signedOut = error instanceof ApiError && error.status === 401;
    const forbidden = error instanceof ApiError && error.status === 403;
    return (
      <div role="alert" className="af-card flex flex-col items-start gap-3 p-6">
        <span className="flex items-center gap-2 text-[15px] font-semibold">
          <AlertTriangle className="size-4 text-[var(--warn)]" />
          {signedOut ? "Your session has ended" : forbidden ? "You don't have access to this" : "Couldn't load this view"}
        </span>
        <p className="max-w-xl text-[13px] text-fg-2">
          {signedOut ? "Sign in again to continue." : forbidden ? "Ask an owner or admin of this workspace for access." : error.message}
        </p>
        {signedOut ? (
          <a href={`/login?next=${encodeURIComponent(typeof window === "undefined" ? "/" : window.location.pathname)}`} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-accent">
            <LogIn className="size-4" /> Sign in
          </a>
        ) : (
          !forbidden && (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-[13px] font-medium text-accent"
              onClick={() => {
                refresh();
                this.setState({ error: null });
              }}
            >
              <RotateCcw className="size-4" /> Try again
            </button>
          )
        )}
      </div>
    );
  }
}

export function Loading({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div aria-busy="true" aria-label={label} className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="af-card h-24 animate-pulse bg-card-2/60" />
      ))}
    </div>
  );
}

export function LiveBoundary({ children, fallback }: { children: ReactNode; fallback?: ReactNode }) {
  const hydrated = useHydrated();
  const fb = fallback ?? <Loading />;
  if (!hydrated) return fb;
  return (
    <Catch>
      <Suspense fallback={fb}>{children}</Suspense>
    </Catch>
  );
}
