"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

type ToastTone = "success" | "info" | "warning" | "error";
interface Toast {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}

const ToastCtx = createContext<((t: Omit<Toast, "id">) => void) | null>(null);

const ICON = { success: CheckCircle2, info: Info, warning: AlertTriangle, error: AlertTriangle } as const;
const COLOR = { success: "var(--ok)", info: "var(--accent)", warning: "var(--warn)", error: "var(--err)" } as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = Date.now() + Math.random();
      setToasts((ts) => [...ts.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), 4500);
    },
    [dismiss],
  );
  const value = useMemo(() => push, [push]);

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" role="region" aria-label="Notifications" aria-live="polite">
        <AnimatePresence initial={false}>
          {toasts.map((t) => {
            const Icon = ICON[t.tone];
            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, y: 12, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 24 }}
                className="pointer-events-auto flex items-start gap-3 rounded-[12px] border border-line bg-card p-3.5 shadow-[var(--shadow)]"
              >
                <Icon className="mt-0.5 size-4 shrink-0" style={{ color: COLOR[t.tone] }} />
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-medium text-fg">{t.title}</p>
                  {t.description ? <p className="mt-0.5 text-[12.5px] text-fg-2">{t.description}</p> : null}
                </div>
                <button type="button" onClick={() => dismiss(t.id)} className="rounded p-0.5 text-fg-3 hover:text-fg" aria-label="Dismiss notification">
                  <X className="size-3.5" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
