"use client";

import { TaskComposer } from "@/components/tasks/TaskComposer";
import { Greeting } from "@/components/ui/time";
import { useCreateTask } from "@/components/tasks/useCreateTask";

/** `stats` is the line under the greeting; demo mode shows illustrative numbers. */
export function QuickTask({ stats = "3 agents working · 1 approval waiting · 1,284 tasks completed this quarter." }: { stats?: string }) {
  const create = useCreateTask();
  return (
    <section className="af-card af-glass relative flex h-full flex-col justify-center overflow-hidden rounded-[20px] p-5 sm:p-7">
      {/* Ambient light */}
      <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent)_28%,transparent),transparent)]" />
      <div aria-hidden className="pointer-events-none absolute -bottom-28 left-1/3 size-72 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-2)_18%,transparent),transparent)]" />

      <div className="relative">
        <p className="af-label">Command center</p>
        <h2 className="mt-2 text-[26px] font-semibold leading-tight tracking-tight sm:text-[32px]">
          <span className="af-gradient-text">
            <Greeting />
          </span>{" "}
          <span className="text-fg">Your AI workforce is ready.</span>
        </h2>
        <p className="mt-2 max-w-xl text-[14px] text-fg-2">
          {stats}
        </p>

        <div className="mt-6">
          <TaskComposer onSubmit={(d) => void create(d)} />
        </div>

      </div>
    </section>
  );
}
