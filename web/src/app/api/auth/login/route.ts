import { NextResponse, type NextRequest } from "next/server";
import { API_URL, forwardHeaders, isSameOrigin, problem, setSessionCookies } from "@/lib/server/session";
import type { components } from "@/lib/api/schema";

type TokenPair = components["schemas"]["TokenPair"];

export async function POST(req: NextRequest) {
  if (!isSameOrigin(req)) return problem(403, "csrf", "Cross-site request blocked.");
  const body = await req.text();
  const upstream = await fetch(`${API_URL}/v1/auth/login`, { method: "POST", headers: forwardHeaders(req), body, cache: "no-store" });
  if (!upstream.ok) {
    return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "content-type": "application/problem+json" } });
  }
  const pair = (await upstream.json()) as TokenPair;
  const res = NextResponse.json({ user: pair.user, organization: pair.organization, role: pair.role });
  setSessionCookies(res, pair);
  return res;
}
