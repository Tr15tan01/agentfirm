import { NextResponse, type NextRequest } from "next/server";

/**
 * Optimistic route protection (Next.js 16 "proxy", formerly middleware).
 * Only checks for the presence of a session cookie to avoid flashing protected
 * pages; real authentication and authorization happen in the Python API on every call.
 * In demo mode (no backend configured) everything stays open.
 */
const LIVE = process.env.NEXT_PUBLIC_AGENTFIRM_AUTH === "api";

export function proxy(req: NextRequest) {
  if (!LIVE) return NextResponse.next();
  const hasSession = req.cookies.has("af_at") || req.cookies.has("af_s");
  const { pathname, search } = req.nextUrl;
  if (pathname === "/login") return hasSession ? NextResponse.redirect(new URL("/", req.url)) : NextResponse.next();
  if (hasSession) return NextResponse.next();
  const url = new URL("/login", req.url);
  url.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except API routes, Next internals and static files.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
