import { NextResponse, type NextRequest } from "next/server";
import { API_URL, clientIp } from "@/lib/server/session";

/**
 * Paddle notification destination: https://<domain>/api/paddle/webhook → API /v1/billing/paddle/webhook.
 *
 * On hosts where the public domain points only at the web app (e.g. VPS Control Center), this keeps
 * the API private. The body is forwarded byte-for-byte with the Paddle-Signature header, because the
 * API verifies the HMAC over the exact raw body. No cookies, no session, no same-origin check (Paddle
 * calls from its servers); the signature is the only authentication, and it is checked by the API.
 */
const MAX_BYTES = 1_000_000;

export async function POST(req: NextRequest) {
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (declared > MAX_BYTES) return NextResponse.json({ title: "Payload too large" }, { status: 413 });
  const body = await req.arrayBuffer();
  if (body.byteLength > MAX_BYTES) return NextResponse.json({ title: "Payload too large" }, { status: 413 });

  const headers = new Headers({ "content-type": req.headers.get("content-type") ?? "application/json" });
  const signature = req.headers.get("paddle-signature");
  if (signature) headers.set("paddle-signature", signature);
  const ip = clientIp(req);
  if (ip) headers.set("x-forwarded-for", ip);

  const upstream = await fetch(`${API_URL}/v1/billing/paddle/webhook`, { method: "POST", headers, body, cache: "no-store", redirect: "manual" });
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
  });
}
