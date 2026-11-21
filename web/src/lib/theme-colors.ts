"use client";

import { useMemo } from "react";
import { useThemeAttr } from "./stores";

export interface ThemeColors {
  accent: string;
  accent2: string;
  cyan: string;
  fg: string;
  fg2: string;
  fg3: string;
  border: string;
  card: string;
  grid: string;
}

const FALLBACK: ThemeColors = {
  accent: "#648bff",
  accent2: "#a77bff",
  cyan: "#48d9e8",
  fg: "#f1f4fc",
  fg2: "#929cb2",
  fg3: "#6b7590",
  border: "#252d40",
  card: "#141a29",
  grid: "rgba(146,156,178,0.12)",
};

function read(): ThemeColors {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string, f: string) => s.getPropertyValue(n).trim() || f;
  return {
    accent: v("--accent", FALLBACK.accent),
    accent2: v("--accent-2", FALLBACK.accent2),
    cyan: v("--cyan", FALLBACK.cyan),
    fg: v("--fg", FALLBACK.fg),
    fg2: v("--fg-2", FALLBACK.fg2),
    fg3: v("--fg-3", FALLBACK.fg3),
    border: v("--border", FALLBACK.border),
    card: v("--card", FALLBACK.card),
    grid: v("--grid", FALLBACK.grid),
  };
}

/** Resolved token values for libraries (Recharts) that need literal colors. Re-reads on theme change. */
export function useThemeColors(): ThemeColors {
  const theme = useThemeAttr();
  return useMemo(() => (theme === null ? FALLBACK : read()), [theme]);
}
