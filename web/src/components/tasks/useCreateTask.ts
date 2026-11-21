"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { api } from "@/data/api";
import { LIVE_DATA, refresh } from "@/lib/live";
import { useToast } from "@/components/ui/toast";
import type { TaskDraft } from "./TaskComposer";

/**
 * Create a real task from the composer (live mode) and open its run page.
 * One selected agent runs directly; several — or none — go to the orchestrator, which plans
 * subtasks across them (or chooses the agents itself).
 */
export function useCreateTask(after?: () => void) {
  const router = useRouter();
  const toast = useToast();
  return useCallback(
    async (d: TaskDraft) => {
      if (!LIVE_DATA) {
        toast({ tone: "info", title: "Demo mode — task not created", description: "Set NEXT_PUBLIC_AGENTFIRM_API=http to run tasks on the backend." });
        after?.();
        return;
      }
      try {
        const { id } = await api.tasks.create({ agents: d.agents, objective: d.instruction });
        refresh("tasks");
        after?.();
        if (d.files.length) {
          toast({ tone: "info", title: "Attachments weren't uploaded", description: "Add documents in Knowledge & Files — agents retrieve from there." });
        }
        router.push(`/tasks/${id}`);
      } catch (e) {
        toast({ tone: "error", title: "Couldn't start the task", description: e instanceof Error ? e.message : String(e) });
      }
    },
    [after, router, toast],
  );
}
