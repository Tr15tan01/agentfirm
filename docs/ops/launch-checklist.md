# Launch checklist

Tick each item on the real server before inviting customers. "Done here" items were verified in the
build sandbox. The rest need the VPS, real accounts or a decision only the owner can make.

## Done here (Phase 7)
- [x] Security review, with findings fixed or accepted (`docs/security/review-2026-11.md`); bandit, pip-audit and npm audit clean
- [x] Tenancy/RLS, RBAC, billing and hardening tests: 234 passing
- [x] Restore drill from an encrypted backup (`docs/ops/restore-drill-2026-11-17.md`)
- [x] Load test meets the SLOs on a 2-vCPU sandbox (`docs/ops/load-test-2026-11-17.md`)
- [x] Caddy routing checked with real Caddy:
  - `/metrics`, `/openapi.json` and `/docs` return 404
  - the admin allowlist blocks other addresses and passes allowed ones
  - a 30 MB body returns 413
  - an unsigned webhook returns 401
  - HSTS and request IDs are present
- [x] Prometheus config and alert rules (promtool), Alertmanager config (amtool), compose config, shellcheck
- [x] Master-key rotation script, tested

## Server and accounts (owner)
- [ ] Contabo VPS created (recommended: at least 4 vCPU / 8 GB); `deploy/provision.sh` run; root SSH disabled
- [ ] DNS A record, DNS-only (see runbook step 2)
- [ ] R2: separate buckets and scoped tokens for artifacts and backups
- [ ] `age-keygen`: the private key stored offline in two places; only the public key on the server
- [ ] `.env.production` written on the server (chmod 600). Every secret freshly generated; none reused from dev
- [ ] GitHub: `production` environment with required reviewers; `VPS_HOST`, `VPS_SSH_KEY` and `VPS_KNOWN_HOSTS` secrets; a GHCR read token on the server
- [ ] First deploy succeeds; `/readyz` is green; super-admin granted with `scripts.create_superadmin`
- [ ] Model providers: keys entered in Platform → Model routing; one real task per agent succeeds
- [ ] `--judge` evals run with live models (rubric items, orchestrator planning quality: R-25)

## Billing (owner)
- [ ] Paddle sandbox checklist in README passes end to end (R-26)
- [ ] Prices and Paddle price IDs set; checkout domain approved in Paddle (R-27)
- [ ] Switch to live Paddle keys; webhook URL `https://<domain>/v1/billing/paddle/webhook`

## Operations
- [ ] Alertmanager receiver set (it is a placeholder now); send a test alert
- [ ] External uptime check on `https://<domain>/healthz` (from outside the VPS)
- [ ] `BACKUP_PING_URL` dead-man switch set; first scheduled backup visible in R2
- [ ] **Restore drill repeated on the real server**, from an R2 object, timed against the 1 h RTO
- [ ] Run the load test against the real server with `deploy/loadtest` (a staging copy, never production data)
- [ ] Rollback rehearsed: deploy a known-bad tag and watch `deploy.sh` roll back

## Security before customers
- [ ] **External penetration test** against the staging stack; findings closed
- [ ] `ADMIN_ALLOW_CIDRS` restricted to your office or VPN
- [ ] Decide on 2FA for super-admins (R-12); until it exists, rely on the IP allowlist and strong passwords
- [ ] Privacy policy, terms and DPA published (Paddle requires the policies for live checkout)
