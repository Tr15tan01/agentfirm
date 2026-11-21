import type { TimelineEvent } from "@/lib/types";

/**
 * Contract for execution event streams. The production implementation
 * (Phase 4) subscribes to `GET /v1/executions/{id}/events` via SSE, resumes
 * with `Last-Event-ID`, and replays persisted events after reconnects.
 */
export type StreamConnection = "connecting" | "live" | "reconnecting" | "closed" | "demo";

export interface ExecutionStream {
  events: TimelineEvent[];
  connection: StreamConnection;
  lastSeq: number;
}
