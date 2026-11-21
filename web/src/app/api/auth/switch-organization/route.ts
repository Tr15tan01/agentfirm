import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, API_URL, forwardHeaders, isSameOrigin, problem } from "@/lib/server/session";
import type { components } from "@/lib/api/schema";

type AccessToken = components["schemas"]["AccessToken"];

/** Switch workspace: the API mints an org-scoped access token; we store it in the httpOnly cookie. */
export async function POST(req: NextRequest) {
  if (!isSameOrigin(req)) return problem(403, "csrf", "Cross-site request blocked.");
  const access = req.cookies.get(ACCESS_COOKIE)?.value;
  if (!access) return problem(401, "unauthorized", "Sign in again.");
  const upstream = await fetch(`${API_URL}/v1/auth/switch-organization`, { method: "POST", headers: forwardHeaders(req, access), body: await req.text(), cache: "no-store" });
  if (!upstream.ok) return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "content-type": "application/problem+json" } });
  const tok = (await upstream.json()) as AccessToken;
  const res = NextResponse.json({ organization: tok.organization, role: tok.role });
  res.cookies.set(ACCESS_COOKIE, tok.access_token, { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", expires: new Date(tok.access_expires_at) });
  return res;
}
