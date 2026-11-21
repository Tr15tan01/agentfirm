"use client";

import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { cn } from "@/lib/cn";
import { useStoredFlag } from "@/lib/stores";
import { ToastProvider } from "@/components/ui/toast";
import { AUTH_LIVE, useSession } from "@/lib/session-client";

const COLLAPSE_KEY = "af-sidebar-collapsed";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useStoredFlag(COLLAPSE_KEY);
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggleCollapsed = () => setCollapsed(!collapsed);

  const me = useSession();
  // Demo builds show the admin section; with live auth it follows the server-side flag
  // (and the API enforces it regardless of what the UI shows).
  const isSuperAdmin = AUTH_LIVE ? Boolean(me?.user.is_super_admin) : true;

  return (
    <ToastProvider>
    <div className="relative min-h-dvh" style={{ backgroundImage: "var(--canvas-wash)", backgroundAttachment: "fixed" }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 hidden border-r border-line bg-bg-2/80 backdrop-blur-xl transition-[width] duration-200 ease-out lg:block",
          collapsed ? "w-[72px]" : "w-[264px]",
        )}
      >
        <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} isSuperAdmin={isSuperAdmin} me={me} />
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileOpen ? (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
            />
            <motion.aside
              className="fixed inset-y-0 left-0 z-50 w-[280px] border-r border-line bg-bg-2 lg:hidden"
              initial={{ x: -300 }}
              animate={{ x: 0 }}
              exit={{ x: -300 }}
              transition={{ type: "spring", stiffness: 420, damping: 40 }}
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
            >
              <button
                type="button"
                className="absolute right-3 top-4 z-10 grid size-8 place-items-center rounded-md text-fg-2 hover:bg-card-2"
                onClick={() => setMobileOpen(false)}
                aria-label="Close navigation"
              >
                <X className="size-4" />
              </button>
              <Sidebar collapsed={false} onToggleCollapsed={() => undefined} onNavigate={() => setMobileOpen(false)} isSuperAdmin={isSuperAdmin} me={me} />
            </motion.aside>
          </>
        ) : null}
      </AnimatePresence>

      <div className={cn("transition-[padding] duration-200 ease-out", collapsed ? "lg:pl-[72px]" : "lg:pl-[264px]")}>
        <Topbar onOpenMobileNav={() => setMobileOpen(true)} me={me} />
        <main id="main" className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:py-8">
          {children}
        </main>
      </div>
    </div>
    </ToastProvider>
  );
}
