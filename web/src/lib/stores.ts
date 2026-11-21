"use client";

import { useSyncExternalStore } from "react";

/* ── Shared 1s clock (one interval for the whole page) ───────── */
let clockNow = 0;
let clockTimer: number | undefined;
const clockListeners = new Set<() => void>();

function subscribeClock(cb: () => void) {
  clockListeners.add(cb);
  if (clockTimer === undefined) {
    clockNow = Date.now();
    clockTimer = window.setInterval(() => {
      clockNow = Date.now();
      clockListeners.forEach((l) => l());
    }, 1000);
  }
  return () => {
    clockListeners.delete(cb);
    if (clockListeners.size === 0 && clockTimer !== undefined) {
      window.clearInterval(clockTimer);
      clockTimer = undefined;
    }
  };
}

/** Current time on the client (ticks every second); `null` during SSR/prerender. */
export function useNow(): number | null {
  return useSyncExternalStore(
    subscribeClock,
    () => clockNow || (clockNow = Date.now()),
    () => null,
  );
}

/** Time origin for relative demo offsets: when the page module first loaded in the browser. */
export const CLIENT_ORIGIN = typeof window === "undefined" ? 0 : Date.now();

/* ── Boolean flag persisted in localStorage ─────────────────── */
const FLAG_EVENT = "af-flag-change";

export function useStoredFlag(key: string): [boolean, (v: boolean) => void] {
  const value = useSyncExternalStore(
    (cb) => {
      window.addEventListener("storage", cb);
      window.addEventListener(FLAG_EVENT, cb);
      return () => {
        window.removeEventListener("storage", cb);
        window.removeEventListener(FLAG_EVENT, cb);
      };
    },
    () => {
      try {
        return localStorage.getItem(key) === "1";
      } catch {
        return false;
      }
    },
    () => false,
  );
  const set = (v: boolean) => {
    try {
      localStorage.setItem(key, v ? "1" : "0");
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(FLAG_EVENT));
  };
  return [value, set];
}

/* ── Current theme attribute ─────────────────────────────────── */
export function useThemeAttr(): "dark" | "light" | null {
  return useSyncExternalStore(
    (cb) => {
      const obs = new MutationObserver(cb);
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      return () => obs.disconnect();
    },
    () => (document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark"),
    () => null,
  );
}

/* ── Saved theme preference (null = follow system) ──────────── */
export function useThemePreference(): "dark" | "light" | "system" | null {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener("af-theme-pref", cb);
      window.addEventListener("storage", cb);
      return () => {
        window.removeEventListener("af-theme-pref", cb);
        window.removeEventListener("storage", cb);
      };
    },
    () => {
      try {
        const v = localStorage.getItem("af-theme");
        return v === "dark" || v === "light" ? v : "system";
      } catch {
        return "system";
      }
    },
    () => null,
  );
}
