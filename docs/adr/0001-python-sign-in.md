# ADR 0001 — Sign-in is owned by the Python API (no Auth.js)

- **Status:** Accepted (Phase 3), 2026-11-16
- **Decision maker:** Product owner

## Context
The brief named Auth.js. During Phase 3 we found that Auth.js has been maintained by the
Better Auth team in security-patch-only mode since September 2025, and that v5 is still
in beta. The product owner decided that **sign-in should be implemented in the Python
backend only**.

## Decision
- FastAPI is the only identity authority. It handles registration, password sign-in
  (argon2id), sessions, refresh-token rotation, organisation switching, invitations and
  RBAC.
- Access tokens are EdDSA (Ed25519) JWTs that live for 10 minutes. Each access token
  references a server-side session, and the API checks that session on every request, so
  signing out or revoking a session takes effect immediately.
- Refresh tokens are opaque, 14-day, rotated on every use, and stored only as SHA-256
  hashes. If an already-rotated secret is presented again, the API revokes the whole
  session (theft detection).
- The Next.js server acts only as a backend-for-frontend (BFF). It relays credentials to the API and
  stores tokens in **httpOnly** cookies: the access token at path `/`, the refresh token
  only at path `/api` (SameSite=Strict). It attaches `Authorization: Bearer` when proxying,
  checks the Origin header on every state-changing request, serialises concurrent refreshes, and
  never lets the token-minting endpoints through its generic proxy.

## Consequences
- ➕ No beta dependency; one place to audit authentication; tokens never reach browser
  JavaScript; other internal services (workers) can verify tokens with the published JWKS.
- ➖ We now own flows that a library would provide: **email verification, password reset,
  MFA (TOTP/WebAuthn) and social/SSO login** (Phase 7 backlog, see Risks R-11–R-13). Until
  email delivery exists, invitation tokens are returned in the API response outside production.
- Security-sensitive bookkeeping (failed-login counters, revocation after refresh-token reuse) is
  committed in an independent transaction, so a rejected request can't roll it back.
