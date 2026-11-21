import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, API_URL, REFRESH_COOKIE, clearSessionCookies, forwardHeaders, isSameOrigin, problem, refreshSession, setSessionCookies } from "@/lib/server/session";

/**
 * Authenticated proxy: /api/v1/* → FastAPI /v1/*.
 * Attaches the bearer token from the httpOnly cookie, refreshes once on 401,
 * and never forwards browser cookies upstream. Auth endpoints that mint tokens
 * are not reachable through here (they have dedicated routes under /api/auth).
 */
const BLOCKED = new Set(["auth/login", "auth/register", "auth/refresh"]);

async function handle(req: NextRequest, ctx: RouteContext<"/api/v1/[...path]">) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (BLOCKED.has(joined)) return problem(404, "not_found", "Not found.");
  if (!isSameOrigin(req)) return problem(403, "csrf", "Cross-site request blocked.");

  const target = `${API_URL}/v1/${joined}${req.nextUrl.search}`;
  const body = ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer();
  const send = (access?: string) => fetch(target, { method: req.method, headers: forwardHeaders(req, access), body, cache: "no-store", redirect: "manual" });

  let access = req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  let refreshed: Awaited<ReturnType<typeof refreshSession>> = null;

  if (!access && refresh) {
    refreshed = await refreshSession(refresh, req);
    access = refreshed?.access_token;
  }
  let upstream = await send(access);
  if (upstream.status === 401 && refresh && !refreshed) {
    refreshed = await refreshSession(refresh, req);
    if (refreshed) upstream = await send(refreshed.access_token);
  }

  const headers: Record<string, string> = { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" };
  // Headers that keep downloaded agent output safe (and the request id for support) pass through.
  // x-accel-buffering: "no" on event streams tells Nginx not to buffer them (live task updates).
  for (const h of ["content-disposition", "content-security-policy", "x-content-type-options", "x-request-id", "x-accel-buffering"]) {
    const v = upstream.headers.get(h);
    if (v) headers[h] = v;
  }
  const res = new NextResponse(upstream.body, { status: upstream.status, headers });
  if (refreshed) setSessionCookies(res, refreshed);
  else if (upstream.status === 401 && refresh) clearSessionCookies(res);
  return res;
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
