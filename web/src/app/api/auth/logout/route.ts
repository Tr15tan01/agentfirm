import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, API_URL, clearSessionCookies, forwardHeaders, isSameOrigin, problem } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  if (!isSameOrigin(req)) return problem(403, "csrf", "Cross-site request blocked.");
  const access = req.cookies.get(ACCESS_COOKIE)?.value;
  if (access) {
    // Revoke server-side; ignore failures (cookies are cleared regardless).
    await fetch(`${API_URL}/v1/auth/logout`, { method: "POST", headers: forwardHeaders(req, access), cache: "no-store" }).catch(() => undefined);
  }
  const res = NextResponse.json({ ok: true });
  clearSessionCookies(res);
  return res;
}
