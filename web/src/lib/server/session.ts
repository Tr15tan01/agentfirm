import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import type { components } from "@/lib/api/schema";

/**
 * Backend-for-frontend session handling.
 *
 * Sign-in is performed by the Python API. The browser never sees a token: the BFF
 * keeps the short-lived access token and the rotating refresh token in httpOnly
 * cookies and attaches `Authorization: Bearer …` when proxying to FastAPI.
 */

export const API_URL = process.env.AGENTFIRM_API_URL ?? "http://localhost:8000";
export const ACCESS_COOKIE = "af_at";
export const REFRESH_COOKIE = "af_rt";
/** Non-secret marker visible to page routes (the refresh cookie is scoped to /api). */
export const SESSION_HINT_COOKIE = "af_s";

type TokenPair = components["schemas"]["TokenPair"];

const secure = process.env.NODE_ENV === "production";

export function setSessionCookies(res: NextResponse, pair: Pick<TokenPair, "access_token" | "access_expires_at" | "refresh_token" | "refresh_expires_at">) {
  res.cookies.set(ACCESS_COOKIE, pair.access_token, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    expires: new Date(pair.access_expires_at),
  });
  res.cookies.set(REFRESH_COOKIE, pair.refresh_token, {
    httpOnly: true,
    secure,
    sameSite: "strict",
    // Only sent to the BFF — never to pages or static assets.
    path: "/api",
    expires: new Date(pair.refresh_expires_at),
  });
  res.cookies.set(SESSION_HINT_COOKIE, "1", { httpOnly: true, secure, sameSite: "lax", path: "/", expires: new Date(pair.refresh_expires_at) });
}

export function clearSessionCookies(res: NextResponse) {
  res.cookies.set(ACCESS_COOKIE, "", { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { httpOnly: true, secure, sameSite: "strict", path: "/api", maxAge: 0 });
  res.cookies.set(SESSION_HINT_COOKIE, "", { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 0 });
}

/** CSRF defence for cookie-authenticated, state-changing requests: same-origin only. */
export function isSameOrigin(req: NextRequest): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(req.method)) return true;
  const origin = req.headers.get("origin");
  if (!origin) return false;
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * The visitor's address, as seen by the reverse proxy directly in front of this app.
 * Nginx appends the connecting address to any X-Forwarded-For the visitor sent
 * (`$proxy_add_x_forwarded_for`), so only the LAST entry is trustworthy; the first one is
 * whatever the visitor chose to write. Caddy replaces the header with one entry, so the last
 * entry is right there too. The API uses this for login rate limits and audit logs.
 */
export function clientIp(req: Pick<NextRequest, "headers">): string | null {
  const last = req.headers.get("x-forwarded-for")?.split(",").map((p) => p.trim()).filter(Boolean).pop();
  return last ?? req.headers.get("x-real-ip");
}

export function forwardHeaders(req: NextRequest, access?: string): Headers {
  const h = new Headers();
  for (const name of ["content-type", "accept", "idempotency-key", "user-agent"]) {
    const v = req.headers.get(name);
    if (v) h.set(name, v);
  }
  const ip = clientIp(req);
  if (ip) h.set("x-forwarded-for", ip);
  if (access) h.set("authorization", `Bearer ${access}`);
  return h;
}

/**
 * Refresh is serialised per refresh token: concurrent requests share one rotation,
 * because the API treats a replayed (already-rotated) refresh token as theft.
 */
const inflight = new Map<string, Promise<TokenPair | null>>();

export function refreshSession(refreshToken: string, req: NextRequest): Promise<TokenPair | null> {
  const existing = inflight.get(refreshToken);
  if (existing) return existing;
  const p = (async () => {
    try {
      const headers = forwardHeaders(req);
      headers.set("content-type", "application/json");
      const r = await fetch(`${API_URL}/v1/auth/refresh`, {
        method: "POST",
        headers,
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      if (!r.ok) return null;
      return (await r.json()) as TokenPair;
    } catch {
      return null;
    } finally {
      setTimeout(() => inflight.delete(refreshToken), 5_000);
    }
  })();
  inflight.set(refreshToken, p);
  return p;
}

export function problem(status: number, title: string, detail: string) {
  return NextResponse.json({ type: `https://agentfirm.app/errors/${title}`, title, status, detail }, { status, headers: { "content-type": "application/problem+json" } });
}
