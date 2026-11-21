"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { TaskComposer } from "./TaskComposer";
import { useCreateTask } from "./useCreateTask";

export function NewTaskDialog({ trigger }: { trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const create = useCreateTask(() => setOpen(false));
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-[12vh] z-50 w-[min(720px,calc(100vw-2rem))] -translate-x-1/2 rounded-[18px] border border-line bg-card p-5 shadow-[var(--shadow)]">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-[17px] font-semibold tracking-tight">New task</Dialog.Title>
              <Dialog.Description className="mt-0.5 text-[13px] text-fg-2">
                Describe the outcome. Pick agents, or let the orchestrator choose and coordinate them.
              </Dialog.Description>
            </div>
            <Dialog.Close className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card-2 hover:text-fg" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <TaskComposer
                autoFocus
                onSubmit={(d) => void create(d)}
              />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
