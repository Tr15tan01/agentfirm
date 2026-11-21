export type Theme = "dark" | "light";
export const THEME_STORAGE_KEY = "af-theme";

/** Runs synchronously in <head>: saved preference → system preference → dark. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t!=="dark"&&t!=="light"){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

export function readTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage unavailable — theme still applies for this session */
  }
}

export type ThemePreference = Theme | "system";

/** Apply an explicit theme, or follow the OS ("system") by clearing the saved choice. */
export function applyThemePreference(pref: ThemePreference): void {
  if (pref === "system") {
    try {
      localStorage.removeItem(THEME_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    const t: Theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
  } else {
    applyTheme(pref);
  }
  window.dispatchEvent(new Event("af-theme-pref"));
}
