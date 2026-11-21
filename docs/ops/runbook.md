# AgentFirm production runbook

Single Contabo VPS (Ubuntu 24.04) running `deploy/docker-compose.prod.yml`:
Caddy (TLS, edge) → web (Next.js) / api (FastAPI) → Postgres 16 + Redis; one or more workers;
backup sidecar → Cloudflare R2; Prometheus + Alertmanager + Grafana + exporters (private).

| Target | Value | Where it's measured |
|---|---|---|
| Availability | 99.5 % monthly (single host; ~3.6 h/month budget) | `ApiDown`, external uptime check on `/healthz` |
| Read latency | p95 < 300 ms | `SlowReads`, dashboard "API p95 latency" |
| Write latency | p95 < 500 ms | dashboard |
| Errors | 5xx < 0.5 % (alert at 2 %) | `High5xxRate` |
| Task start | queued < 5 min | `QueueBacklog` |
| RPO / RTO | 6 h / 1 h | backups every 6 h; restore drill (docs/ops/restore-drill-2026-11-17.md) |

## Golden rules

1. **Never** `SET session_replication_role = replica` (or disable triggers/FKs) on production. It
   skips foreign-key checks and left orphan rows in staging that the restore drill caught.
2. **Never** edit `.env.production` values in a running container; change the file, then redeploy.
3. Migrations are **expand → contract**: a release may only add columns/tables/nullable fields or
   backfill. Drops/renames ship one release later, so rolling the app back never needs a down-migration.
4. Every deploy takes a backup before migrating (deploy.sh does this; don't skip it by hand).
5. Use `docker compose … exec` and SQL as `agentfirm_owner` only for incidents; write what you did
   in the incident log.

## First-time setup

1. Create the VPS, then as root: `DEPLOY_SSH_KEY=… ADMIN_SSH_KEY=… bash deploy/provision.sh`.
2. DNS: `A app.example.com → VPS IP` with the Cloudflare proxy **off** (DNS only). If you later turn
   the proxy on (SSL mode "Full (strict)"), first put Cloudflare's IP ranges in `trusted_proxies` in
   `deploy/Caddyfile`; otherwise the `/admin` allowlist and per-IP rate limits see Cloudflare's address.
3. Generate secrets on your laptop (not the server's shell history):
   `openssl rand -hex 32` for each password/token; the JWT signing key and master key with the two
   one-liners at the top of `.env.example`; `age-keygen -o backup.key` (store `backup.key` **offline**; only its public
   `age1…` line goes in `BACKUP_AGE_RECIPIENT`).
4. Copy `deploy/` and `infra/` to `/opt/agentfirm/`, write `/opt/agentfirm/deploy/.env.production`
   (`chmod 600`), from the Production section of `.env.example`.
5. GitHub: environment `production` with required reviewers; secrets `VPS_HOST`, `VPS_SSH_KEY`
   (the deploy user's private key), `VPS_KNOWN_HOSTS` (`ssh-keyscan -t ed25519 <host>`); variables
   `PADDLE_CLIENT_TOKEN`, `PADDLE_ENV`. On the server, `docker login ghcr.io` as deploy with a
   read-only package token.
6. Run the Deploy workflow (or `./deploy.sh <tag>` on the server). Sign up normally in the app,
   then grant super-admin (no HTTP endpoint can do this):
   `docker compose … run --rm -e AGENTFIRM_MIGRATIONS_DATABASE_URL=postgresql+asyncpg://agentfirm_owner:$AGENTFIRM_OWNER_PASSWORD@postgres:5432/agentfirm api python -m scripts.create_superadmin <email>`.
7. Paddle: follow the "Paddle go-live checklist" in README (webhook URL
   `https://APP_DOMAIN/v1/billing/paddle/webhook`; `/api/paddle/webhook` also works).
8. Alerts: replace the placeholder receiver in `deploy/observability/alertmanager.yml`, set
   `BACKUP_PING_URL`, add an external uptime check on `https://APP_DOMAIN/healthz`.

## Deploy

Merges to `main` → CI → Deploy workflow builds `agentfirm-{api,web,backup}:<sha>` and runs
`deploy.sh <sha>` on the server: pull → backup → migrate → roll out → wait for `/readyz`, the web
healthcheck and public `/healthz` (2 min) → on failure, roll back web/api/worker to the previous tag.
Deploys are serialized (`concurrency: deploy-production`).

## Rollback

- Automatic: deploy.sh rolls back when health checks fail.
- By hand (bad behaviour that passes health checks):
  `cd /opt/agentfirm/deploy && ./deploy.sh "$(cat .previous_tag)" --no-migrate`, or run the Deploy
  workflow with `tag=<sha>`. Migrations are not reverted (rule 3); if a migration itself is the problem,
  restore (below) is the last resort.
- Agents: Platform → Agents → roll back a single agent version without a deploy.
- Tools: Platform → Tools kill-switch disables a misbehaving tool for every tenant immediately.

## Restore

Practised in `docs/ops/restore-drill-2026-11-17.md` (restore of the test dataset took < 1 s; a real
database takes longer, so budget against the 1 h RTO).

1. Pick the dump: `rclone lsf r2:$BACKUP_R2_BUCKET/postgres/daily/`.
2. Bring the app down: `docker compose … stop web api worker`.
3. On a machine holding `backup.key`: `deploy/backup/restore.sh <object> <target DSN>` (decrypts,
   checks the sha256, restores with `--clean --if-exists`, runs `verify.sql`: row counts, orphan check,
   every RLS table has a policy).
4. Start the app; check `/readyz`, sign in, open a task. Announce that work since the dump
   (≤ 6 h) is lost; Paddle replays webhooks it still has, so billing reconciles itself.

## Secret rotation

| Secret | How | Impact |
|---|---|---|
| `AGENTFIRM_JWT_PRIVATE_KEY` | new key → redeploy | outstanding access tokens (≤ 10 min) stop verifying; refresh tokens are opaque server sessions, so clients refresh silently. To force everyone out (suspected compromise): `UPDATE auth_sessions SET revoked_at = now(), revoke_reason = 'key_rotation' WHERE revoked_at IS NULL` |
| `AGENTFIRM_MASTER_KEY` | `… api python -m scripts.rotate_master_key` with `AGENTFIRM_NEW_MASTER_KEY` set (dry run), then again with `--commit`; set the new key in `.env.production` and redeploy at once | provider/connector calls fail between commit and redeploy (seconds) |
| DB passwords | `ALTER ROLE … PASSWORD`, update env, redeploy | seconds of reconnects |
| Paddle API key / webhook secret | create the new one in Paddle, update env, redeploy, then delete the old one | none |
| R2 tokens | create new scoped token, update env, redeploy, revoke old | none |
| Metrics token | update env, redeploy (deploy.sh rewrites Prometheus' token file) | a scrape gap |
| Provider API keys | Platform → Model routing (stored encrypted) | none |

## Alerts

<a id="api-down"></a>**ApiDown** — `docker compose … ps`; `logs --tail 200 api`. Common causes:
DB unreachable (`/readyz` lists the failing check), OOM (`dmesg | grep -i oom`), a bad deploy
(roll back).

<a id="worker-down"></a>**WorkerDown / WorkerCrashes** — `logs worker`. Leases expire and tasks are
retried by the next worker, so restarting is safe: `docker compose … restart worker`.

<a id="errors"></a>**High5xxRate** — logs are JSON with `request_id`; users see the same id in the
`x-request-id` header and error pages. `logs api | grep '"level":"ERROR"'`.

<a id="latency"></a>**SlowReads** — check CPU (dashboard), Postgres connections, slow queries
(`pg_stat_statements` if enabled). Scale workers down before the API if CPU-bound.

<a id="queue"></a>**QueueBacklog** — workers down or saturated: check WorkerDown, then raise
`AGENTFIRM_WORKER_CONCURRENCY` or `docker compose … up -d --scale worker=2`.

<a id="providers"></a>**ModelCallsFailing** — a provider outage or a revoked key. Platform →
Model routing: switch the task type to another provider.

<a id="billing"></a>**PaddleWebhookErrors** — Platform → Billing events shows the payload and error.
`bad_signature` means the webhook secret is wrong (or someone is probing). Fix, then replay from
Paddle's dashboard; handling is idempotent by event id.

<a id="disk"></a>**DiskFilling** — `docker system df`; `docker image prune -a --filter until=168h`;
logs are capped at 5×20 MB per container by provision.sh.

<a id="database"></a>**PostgresConnectionsHigh** — each API/worker process can hold up to pool 20 + overflow 5 = 25 connections;
`max_connections` is 150 (deploy/docker-compose.prod.yml). Count processes × 25 (+ exporter, backups, psql) before scaling out.

## Observability access

Grafana and Prometheus are not public: `ssh -L 3001:127.0.0.1:3001 admin@<host>` then open
`http://localhost:3001` (dashboard "AgentFirm — production").
