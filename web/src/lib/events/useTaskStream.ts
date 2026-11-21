"use client";

/**
 * Live execution events for one task over SSE (GET /api/v1/tasks/{id}/stream via the BFF).
 * Resumes after the last event id on reconnect (the server ends each stream after ~5 min
 * to re-authorise), backs off on errors, and stops when the task ends or the view unmounts.
 */
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { taskStream } from "@/lib/api/http";
import type { TaskEvent } from "@/lib/types";
import type { StreamConnection } from "./types";

interface StreamState {
  events: TaskEvent[];
  connection: StreamConnection;
}

class TaskStreamStore {
  private state: StreamState;
  private listeners = new Set<() => void>();

  constructor(initial: TaskEvent[]) {
    this.state = { events: [...initial].sort((a, b) => a.id - b.id), connection: "connecting" };
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  get = () => this.state;

  private set(next: Partial<StreamState>) {
    this.state = { ...this.state, ...next };
    this.listeners.forEach((l) => l());
  }

  push(e: TaskEvent) {
    if (this.state.events.some((x) => x.id === e.id)) return;
    this.set({ events: [...this.state.events, e] });
  }

  async run(taskId: string, signal: AbortSignal) {
    let backoff = 1000;
    while (!signal.aborted) {
      const after = this.state.events.at(-1)?.id ?? 0;
      try {
        this.set({ connection: this.state.events.length ? "live" : "connecting" });
        let ended = false;
        for await (const e of taskStream(taskId, signal, after)) {
          if ("end" in e) {
            ended = true;
            break;
          }
          this.push(e);
          this.set({ connection: "live" });
          backoff = 1000;
        }
        if (ended) {
          this.set({ connection: "closed" });
          return;
        }
      } catch {
        if (signal.aborted) return;
        this.set({ connection: "reconnecting" });
        await new Promise((r) => setTimeout(r, backoff));
        backoff = Math.min(backoff * 2, 15_000);
      }
    }
  }
}

export function useTaskStream(taskId: string, initial: TaskEvent[], enabled: boolean): StreamState {
  // One store per task id; `initial` only seeds it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const store = useMemo(() => new TaskStreamStore(initial), [taskId]);
  useEffect(() => {
    if (!enabled) return;
    const ctrl = new AbortController();
    void store.run(taskId, ctrl.signal);
    return () => ctrl.abort();
  }, [store, taskId, enabled]);
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
