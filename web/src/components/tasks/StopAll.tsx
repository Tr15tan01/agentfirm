"use client";

import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, OctagonX } from "lucide-react";
import type { AgentKey } from "@/lib/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { api } from "@/data/api";
import { refresh } from "@/lib/live";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/primitives";

/**
 * Stops running and queued work in this workspace: every agent, or just one. The server cancels the
 * executions and the worker interrupts them within a couple of seconds, even mid-model-call.
 */
export function StopAll({ activeCount }: { activeCount: number }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [agent, setAgent] = useState<"" | AgentKey>("");
  const [busy, setBusy] = useState(false);

  const stop = async () => {
    setBusy(true);
    try {
      const r = await api.tasks.stopAll(agent || undefined);
      refresh("tasks:list");
      toast({
        tone: r.executionsStopped ? "warning" : "info",
        title: r.executionsStopped ? `Stopped ${r.executionsStopped} run${r.executionsStopped === 1 ? "" : "s"}` : "Nothing was running",
        description: r.executionsStopped ? `${r.tasksAffected} task${r.tasksAffected === 1 ? "" : "s"} cancelled. You can retry any of them later.` : undefined,
      });
      setOpen(false);
    } catch (e) {
      toast({ tone: "error", title: "Couldn't stop the runs", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="danger" disabled={activeCount === 0} title={activeCount === 0 ? "Nothing is running or queued" : "Stop running agents"}>
          <OctagonX className="size-4" /> Stop running{activeCount ? ` (${activeCount})` : ""}
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/3 z-50 w-[min(460px,calc(100vw-2rem))] -translate-x-1/2 rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow)]">
          <Dialog.Title className="text-[16px] font-semibold">Stop running agents?</Dialog.Title>
          <Dialog.Description className="mt-1.5 text-[13.5px] text-fg-2">
            Running, queued and paused tasks are cancelled and interrupted. Finished tasks are untouched, and any cancelled task can be retried from its checkpoint.
          </Dialog.Description>
          <label className="mt-3 block text-[13px] font-medium">
            Which agents
            <select
              value={agent}
              onChange={(e) => setAgent(e.target.value as "" | AgentKey)}
              className="mt-1 h-9 w-full rounded-[10px] border border-line bg-card-2 px-2 text-[13px] outline-none focus:border-accent"
              aria-label="Which agents to stop"
            >
              <option value="">All agents</option>
              {(Object.keys(AGENT_IDENTITIES) as AgentKey[]).map((k) => (
                <option key={k} value={k}>
                  {AGENT_IDENTITIES[k].name} only
                </option>
              ))}
            </select>
          </label>
          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost">Keep running</Button>
            </Dialog.Close>
            <Button variant="danger" onClick={stop} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <OctagonX className="size-4" />} Stop {agent ? AGENT_IDENTITIES[agent].shortName : "everything"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
