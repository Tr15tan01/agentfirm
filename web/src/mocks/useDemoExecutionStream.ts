"use client";

/**
 * ⚠ DEMONSTRATION ONLY. Replays scripted events with the same shape the
 * real `useExecutionStream` (SSE + Last-Event-ID replay, Phase 4) will return.
 */
import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import type { TimelineEvent } from "@/lib/types";
import type { ExecutionStream } from "@/lib/events/types";
import { DEMO_TIMELINE } from "./demo-data";

export function useDemoExecutionStream(speed = 1): ExecutionStream {
  const [count, setCount] = useState(3);
  const [cycle, setCycle] = useState(0);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce) return; // reduced motion: show the full script statically
    const timers: number[] = [];
    const base = DEMO_TIMELINE[2].atMs;
    DEMO_TIMELINE.slice(3).forEach((e, i) => {
      timers.push(window.setTimeout(() => setCount(4 + i), ((e.atMs - base) / speed) * 0.9));
    });
    // Restart the demo loop after a pause so the dashboard stays alive.
    const total = (DEMO_TIMELINE[DEMO_TIMELINE.length - 1].atMs - base) / speed;
    timers.push(
      window.setTimeout(() => {
        setCount(3);
        setCycle((c) => c + 1);
      }, total + 9000),
    );
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [speed, cycle, reduce]);

  const events: TimelineEvent[] = reduce ? DEMO_TIMELINE : DEMO_TIMELINE.slice(0, count);
  return {
    events,
    connection: "demo",
    lastSeq: events.at(-1)?.seq ?? 0,
  };
}
