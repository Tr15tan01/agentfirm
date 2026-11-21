# ADR 0007: Production readiness on a single Contabo VPS

- **Status:** Accepted (Phase 7)
- **Date:** 2026-11-17
- **Context:** AgentFirm must go live on one Contabo VPS, with Cloudflare R2 for storage. Before that it needs a security review, monitoring, backups we have actually restored, measured performance targets and a repeatable deploy with rollback. Budget and operational simplicity favour one host over a cluster.

## Decisions

### 1. One host, Docker Compose, Caddy at the edge
- **What runs:** `deploy/docker-compose.prod.yml` runs Caddy, web, api, worker, Postgres 16, Redis, a backup sidecar and the monitoring stack.
- **What is public:** only Caddy publishes ports (80/443). The API port is not published, and Grafana binds to `127.0.0.1` (reached by SSH tunnel).
- **Why not Kubernetes:** on one VPS it adds moving parts without adding availability.
- **Consequence: the host is a single point of failure** (R-3). The availability target is set honestly at 99.5 %/month. Backups bound the data loss.
- **Caddy's jobs:** TLS (Let's Encrypt), HSTS and a 26 MB body cap. It also returns 404 for `/metrics`, `/openapi.json` and `/docs`. The Paddle webhook goes straight to the API.
- **Admin IP allowlist:** an optional allowlist (`ADMIN_ALLOW_CIDRS`) covers `/admin/*` and `/api/v1/admin/*`. It is defence in depth: the API checks super-admin on every call anyway.

### 2. Security baseline enforced in code, not only at the proxy
- **Middleware:** a pure-ASGI middleware sets request IDs and security headers (`nosniff`, framing, `no-store`) on every response. It also enforces body limits: 1 MB, or 25 MB for uploads, counting chunked bodies too.
- **Why in the app:** the API stays safe if Caddy is misconfigured or bypassed.
- **Proxy trust:** the API trusts forwarded headers only from `FORWARDED_ALLOW_IPS`.
- **Production hardening:** OpenAPI is off in production. Argon2 runs off the event loop.
- **Artifacts:** model-written files are served through an org-scoped endpoint with a sandbox CSP and `attachment`, never inline HTML.
- **Web app:** sends a CSP and the standard headers. The remaining gap is `script-src 'unsafe-inline'` (R-29).
- **Review record:** the findings and their fixes are in `docs/security/review-2026-11.md`.

### 3. Observability: Prometheus metrics, JSON logs, alert rules tied to SLOs
- **Metrics:** HTTP, model calls, credits, tools, worker turns and heartbeat, webhooks, execution counts and queue age.
  - Counts come from a `SECURITY DEFINER` function that returns totals only, so no tenant data leaves RLS.
  - `/metrics` needs a bearer token and returns 404 without one.
- **Logs:** JSON, carrying the same `request_id` the user sees in `x-request-id`.
- **Alerts:** ten rules in `deploy/observability/alerts.yml`, each linked to a runbook section. They are validated with `promtool`, and every metric they use was checked against a live scrape.
- **Self-hosted:** Prometheus, Alertmanager and Grafana run on the VPS; no SaaS dependency.
  - The catch is that they die with the host. That is why an **external** uptime check and a backup dead-man switch are launch requirements.

### 4. Backups: encrypted logical dumps to R2, restore drilled
- **What runs:** `pg_dump` is piped through `age` (public-key encryption) and uploaded to R2 every 6 h.
- **Retention:** 35 days of dailies and about 13 monthlies.
- **Key handling:** the server only holds the public key, so a stolen server or bucket can't read backups.
- **Before migrations:** every deploy takes a backup first.
- **The drill:** a full restore into an empty database, followed by `verify.sql` (row counts, orphan check, every RLS table has a policy). It caught real orphan rows (`docs/ops/restore-drill-2026-11-17.md`).
- **RPO 6 h / RTO 1 h.** WAL archiving (point-in-time recovery) is *not* in this phase. It would cut the RPO to minutes, and it is the first thing to add once paying customers rely on the service.

### 5. Performance targets measured, not assumed
- **Targets:** reads p95 < 300 ms, writes p95 < 500 ms, 5xx < 0.5 %.
- **Load test:** Locust, 100 users on a 2-vCPU sandbox with one API process. Results are in `docs/ops/load-test-2026-11-17.md`.
- **Bugs it found and fixed:**
  - A sign-up race that returned 500.
  - Argon2 blocking the event loop.

### 6. Deploy: immutable images, health-gated rollout, automatic rollback
- **CI** runs on every PR: ruff, bandit, pip-audit, pytest (including the RLS/tenancy suites), web tsc/lint/build/audit, shellcheck, compose/Caddy/Prometheus config checks.
- **Deploy** (`main`, after CI, behind the GitHub `production` environment):
  - Builds `agentfirm-{api,web,backup}:<git-sha>` and pushes to GHCR.
  - On the server, `deploy.sh <sha>` pulls the images, takes a backup, migrates, rolls out, then waits for three checks: `/readyz`, the web healthcheck and public `/healthz`.
  - If any check fails, it rolls web/api/worker back to the previous tag.
- **Migrations are expand → contract:** a release never breaks the previous release's code, so rollback never needs a down-migration.
- **Secrets:** they live only in `.env.production` on the server (mode 600). CI holds just an SSH key and the host fingerprint.
- **Server hardening (`provision.sh`):** key-only SSH, no root login, ufw (22/80/443), fail2ban, unattended security upgrades, Docker log caps, swap.

### 7. Master-key rotation is a supported operation
- `scripts/rotate_master_key.py` re-wraps every stored data key in one transaction.
- It is a dry run by default.
- It verifies that each secret decrypts with the new key before committing, and it is audit-logged.
- It is tested, including the wrong-key abort.

## Consequences
- **Verified in the sandbox:**
  - Tests, scans and configs, with real Caddy and promtool.
  - The restore drill and the load test.
- **Not yet verified on the VPS itself:** there was no Docker daemon or server here, so the first real deploy is a launch step (`docs/ops/launch-checklist.md`).
- **Still open:**
  - An external penetration test.
  - 2FA for super-admins (R-12).
  - The DNS-rebinding egress proxy (R-15/R-21).
  - CSP `unsafe-inline` (R-29).
  - PITR (R-30).
