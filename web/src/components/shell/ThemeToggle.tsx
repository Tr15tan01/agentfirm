"use client";

import { Moon, Sun } from "lucide-react";
import { applyThemePreference, readTheme } from "@/lib/theme";
import { cn } from "@/lib/cn";

/** Visual state is driven purely by CSS (`dark:` = [data-theme=dark]) so it never flashes. */
export function ThemeToggle({ className }: { className?: string }) {
  const toggle = () => applyThemePreference(readTheme() === "dark" ? "light" : "dark");

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle light / dark theme"
      title="Toggle theme"
      className={cn(
        "relative flex h-9 w-[68px] shrink-0 items-center rounded-[10px] border border-line bg-card-2 p-1 transition-colors hover:border-line-strong",
        className,
      )}
    >
      <span
        aria-hidden
        className="absolute top-1 h-7 w-[30px] translate-x-0 rounded-[7px] bg-card shadow-[var(--shadow)] ring-1 ring-line transition-transform duration-200 dark:translate-x-[30px]"
      />
      <Sun className="relative z-10 mx-[7px] size-4 text-warn dark:text-fg-3" />
      <Moon className="relative z-10 mx-[7px] size-4 text-fg-3 dark:text-accent" />
    </button>
  );
}
