"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

export const inputClass =
  "h-9 w-full rounded-[10px] border border-line bg-card px-3 text-[13.5px] outline-none transition-colors placeholder:text-fg-3 focus:border-accent";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12.5px] font-medium text-fg-2">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11.5px] text-fg-3">{hint}</span> : null}
    </label>
  );
}

export function Modal({ title, description, onClose, children, wide }: { title: string; description?: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content
          className={`fixed left-1/2 top-[8vh] z-50 max-h-[84vh] -translate-x-1/2 overflow-y-auto rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow)] ${wide ? "w-[min(720px,calc(100vw-2rem))]" : "w-[min(520px,calc(100vw-2rem))]"}`}
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-[16px] font-semibold">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-1 text-[13px] text-fg-2">{description}</Dialog.Description> : <Dialog.Description className="sr-only">{title}</Dialog.Description>}
            </div>
            <Dialog.Close className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card-2" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="mt-4">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function money(cents: number | null | undefined, currency = "EUR"): string {
  if (cents === null || cents === undefined) return "Price not set";
  return new Intl.NumberFormat(undefined, { style: "currency", currency, minimumFractionDigits: cents % 100 ? 2 : 0 }).format(cents / 100);
}

export function shortDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—";
}
