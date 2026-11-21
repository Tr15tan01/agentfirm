import type { NextConfig } from "next";

const dev = process.env.NODE_ENV === "development";

/**
 * Security headers (Phase 7, security review F-02). HSTS is set by Caddy, which terminates TLS.
 * script-src keeps 'unsafe-inline': Next.js partial prerendering emits inline bootstrap scripts that
 * can't carry per-request nonces from static shells. Residual XSS risk is limited by React escaping,
 * Markdown rendered without raw HTML, and every other directive below (no plugins, no framing, no
 * foreign forms, connections only to ourselves and Paddle). Paddle hosts are a wildcard because
 * Paddle.js loads from cdn.paddle.com and frames its (sandbox-)buy.paddle.com checkout.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' https://cdn.paddle.com${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline' https://cdn.paddle.com",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  `connect-src 'self' https://*.paddle.com${dev ? " ws:" : ""}`,
  "frame-src https://*.paddle.com",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  ...(dev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(self \"https://buy.paddle.com\" \"https://sandbox-buy.paddle.com\")" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
        ],
      },
    ];
  },
};

export default nextConfig;
