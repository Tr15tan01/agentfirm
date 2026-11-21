"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeOut"];

export const AUTH_LIVE = process.env.NEXT_PUBLIC_AGENTFIRM_AUTH === "api";

/** Current signed-in user via the BFF (cookie → bearer). `null` in demo mode or while loading. */
export function useSession(): Me | null {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    if (!AUTH_LIVE) return;
    let alive = true;
    fetch("/api/v1/auth/me", { cache: "no-store" })
      .then(async (r) => {
        if (r.status === 401) {
          window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
          return;
        }
        if (r.ok && alive) setMe((await r.json()) as Me);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return me;
}

export async function switchOrganization(organizationId: string): Promise<boolean> {
  const r = await fetch("/api/auth/switch-organization", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ organization_id: organizationId }),
  });
  return r.ok;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
