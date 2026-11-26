# AgentFirm

**Your AI team. Ready to work.** A multi-tenant SaaS platform where specialised AI agents work
alone or together, coordinated by a central orchestrator.

| Path | What |
|---|---|
| `docs/ARCHITECTURE.md` | Architecture, design system, ERD, execution model, tenancy security, roadmap, risks |
| `docs/screens/` | Phase-1 screenshots (dark, light, mobile, admin routing) |
| `web/` | Next.js 16 · React 19 · Tailwind CSS 4 · Motion · Recharts · Radix · Lucide |
| `api/` | FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 (RLS) · Redis · argon2id · EdDSA JWT |
| `docs/agents/` | Agent Interface spec + six agent specifications (Phase 3.5) |
| `docs/adr/` | Architecture decisions (sign-in, tenant isolation) |
| `docker-compose.yml` | Postgres (pgvector) · Redis · migrate · API · web |

## Run everything with Docker

```bash
cp .env.example .env   # fill in passwords + generate the two keys (commands inside)
docker compose up --build
# create a platform super-admin (operators only — there is no HTTP endpoint for this):
docker compose run --rm -e AGENTFIRM_MIGRATIONS_DATABASE_URL=postgresql+asyncpg://agentfirm_owner:$AGENTFIRM_OWNER_PASSWORD@postgres:5432/agentfirm api python -m scripts.create_superadmin you@example.com
```

## Run the API locally

```bash
cd api
python3.13 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
# Postgres 16 with roles agentfirm_owner + agentfirm_app (see infra/postgres/init.sh)
alembic upgrade head                      # runs as the OWNER role
uvicorn agentfirm.main:app --reload       # connects as the APP role (RLS applies) → http://localhost:8000/docs
python -m agentfirm.worker                # agent worker (simulated models + fixture web by default in dev)
pytest                                    # 221 tests on a throw-away database
python -m agentfirm.evals.harness creative research marketing engineer bi assistant orchestrator --publish --out ../docs/evals
python -m agentfirm.evals.harness research --judge   # rubric items via the LLM judge (live models only)
# Stop other workers on the same database first: they would pick up the harness's tasks.
```

In development the worker defaults to **simulated** models, a **fixture** web corpus and a **fixture** connector
world (repo, ad account, calendar, outbox, GN7T datasets), so nothing costs money, sends anything or touches
the internet. Fixture outputs are labelled `fixture: true` and approval previews say so. Every simulated model call is labelled in events and usage.
Set `AGENTFIRM_GATEWAY_MODE=live` / `AGENTFIRM_WEB_MODE=live` / `AGENTFIRM_CONNECTOR_MODE=live`, connect
systems in **Settings → Integrations**, and add provider keys in
**Admin → Models** to use real providers. Production refuses to start in simulated or fixture mode.

## Run the frontend

```bash
cd web
npm install
npm run dev        # http://localhost:3000 — demo data (no backend needed)
npm run build      # production build (strict TypeScript)
npm run lint

# Against the live API (sign-in, tasks, SSE, admin routing — no mocks):
NEXT_PUBLIC_AGENTFIRM_API=http NEXT_PUBLIC_AGENTFIRM_AUTH=api AGENTFIRM_API_URL=http://localhost:8000 npm run dev
```

Live mode reads data in the browser through the BFF (`/api/...`), because the refresh cookie is scoped to
`/api` and server components can't renew it (ADR 0004 §7). Demo-only widgets are hidden in live mode.

## Phase 1 — what's included

- **Design system**: tokens for independently designed dark and light themes, Geist / Geist Mono,
  and a pre-paint theme script (saved choice → system preference, no flash).
- **App shell**: collapsible sidebar (icon rail on desktop, drawer on mobile), breadcrumbs,
  search, New Task, notifications, theme switch, profile and workspace menus.
- **`AgentActivityCore`** (`web/src/components/agent/`): idle, working (real % or
  indeterminate), collaborating, completed and failed states. It honours
  `prefers-reduced-motion`.
- **`AgentCollaborationCore`**: orchestrator hub plus participating agents. Participant state is
  *derived from the event stream*, never set by hand.
- **Dashboard**: command-center input (auto or manual agent selection, multi-agent), six agent
  cards, active tasks, a live collaboration panel with an execution timeline, usage charts and
  recent activity.
- **Super-admin › Models & Routing** (`/admin/models`): choose the primary model and an ordered
  fallback chain **per task type** (reasoning, text, code, summarise, classify, creative, vision,
  long context, embeddings) across OpenAI, Gemini and GN7T. It warns about degraded or
  disabled providers and missing fallbacks.
- Later-phase routes have designed placeholder screens, so navigation never 404s.

## Phase 2 — what's included

All screens read from **`AgentFirmApi`** (`web/src/lib/api/contracts.ts`). `web/src/data/api.ts` picks the
implementation. The default is the demo adapter (`web/src/mocks/adapter.ts`); setting
`NEXT_PUBLIC_AGENTFIRM_API=http` switches to the HTTP adapter (`web/src/lib/api/http.ts`), which is
ready for the Phase-3 backend.

| Screen | Route | Highlights |
|---|---|---|
| Agent directory | `/agents` | Mission, capabilities, tools (approval-gated ones marked), routed models, usage, recent runs, search and status filter |
| Agent workspace | `/agents/[key]` | Three panels: conversations, projects and knowledge · streamed markdown chat with code highlighting, copy and stop · live execution with steps, tools, artifacts and approvals |
| Creative idea board | `/agents/creative` | Nine thinking approaches, streamed idea generation, drag-and-drop board, inline edit, compare (up to 4), send to Research, Marketing, BI or Engineer |
| Tasks & runs | `/tasks` | Approval queue, status tabs, search, progress (indeterminate when unknown) |
| Task monitor | `/tasks/[id]` | Pause, resume, cancel (with confirmation), retry from checkpoint · subtask DAG · timeline, tool calls, filterable logs, artifacts · pinned agent versions |
| Collaboration | `/collaboration` | Composer, 8-stage orchestrator pipeline derived from subtask states, dependency graph, participating agents, approval gates |
| Usage & billing | `/billing` | 7, 30 or 90 days · tokens per day · usage by agent, model (with cost estimate) and member · limits and alerts · invoices |
| Settings | `/settings` | General · members and roles (invite, change role) · brand voice · appearance (system, dark or light) · notifications · security |

Also new: a **New Task** dialog everywhere (⌘/Ctrl+Enter), toast notifications, and skeleton loading for chat.

## Phase 3 — what's included

- **Python sign-in** (ADR 0001): register, sign in, rotating refresh tokens with theft detection, account lockout, rate limits,
  sessions you can list and revoke, workspace switching, invitations tied to an email address. The web app has a sign-in page and a
  cookie-based BFF; turn it on with `NEXT_PUBLIC_AGENTFIRM_AUTH=api`.
- **Multi-tenant security** (ADR 0002): PostgreSQL row-level security, composite foreign keys, a non-owner app role,
  and the RBAC roles owner, admin, member and viewer, enforced on every request.
- **Domain API** (`/v1`): agents, projects, conversations, tasks (idempotent create, pause/resume/cancel/retry, append-only events),
  approvals, usage, members and audit log.
- **Super-admin model routing API** (`/v1/admin`): providers, envelope-encrypted API keys (only the last 4 characters are ever returned),
  the model catalogue, and per-task-type routing with up to 3 fallbacks plus a "resolve" preview. Every change is audit-logged.
- **Tests**: tenancy (with a guard that every route is classified), RLS, RBAC, auth, audit immutability, gateway and task state machine.
- **Generated types**: `web/src/lib/api/schema.d.ts` from OpenAPI (`npm run api:types`).

## Phase 3.5 — what's included

- **[Agent Interface spec](docs/agents/00-agent-interface.md):** the orchestrator ↔ agent protocol. It covers task and result
  envelopes, context handling, tool enforcement, approvals, delegation, errors and recovery, budgets, model routing,
  all 17 event types and the security rules.
- **Six agent specifications** ([docs/agents/](docs/agents/README.md)). Each one covers purpose and scope, functional requirements,
  architecture, Mermaid workflow diagrams, tools, data access, input/output schemas, permissions and approvals, failure scenarios,
  acceptance criteria and test cases.
- **Executable specs:** Pydantic contracts, six YAML manifests (the 20-point standard definition), a shared tool catalog
  (36 tools) and 91 eval cases. A registry validator enforces the brief's invariants:
  - no consequential tool without an approval gate and an approver of the right level;
  - delegation must be accepted by both agents;
  - the rules the brief mandates must be present;
  - eval coverage must span all 10 categories.
- **Versioning:** published agent versions can't be changed in the database (trigger). There is one current version per agent,
  plus publish and rollback commands, with an audit entry for each.
- **Drift guards:** tests fail if the JSON Schemas or the generated doc sections no longer match the code.

## Phase 4a — what's included

- **Model Gateway** with adapters for OpenAI (Chat Completions, native JSON schema), Gemini (`generateContent`),
  GN7T (OpenAI-compatible, at an admin-set `base_url`; it accepts only plain-text responses, so JSON schemas go in the prompt). It provides per-task routing
  (agent version → org → platform), retries, fallback to the next model, a per-provider circuit breaker, cost tracking and credits.
- **Tool Registry runtime** is the single enforcement point. The checks run in this order: grant → the step's declared tools →
  user permission → call cap → approval → budget → idempotent replay → timeout. Web fetch is SSRF-guarded
  (private, link-local and metadata IPs, redirects, size caps); search uses Brave by default.
- **Workers:** leases in Postgres, a heartbeat, and resumption from LangGraph Postgres checkpoints after a crash. Step
  outputs are committed atomically with `step.completed`, so a crashed run never repeats completed steps
  (tested by killing a worker mid-run). Approvals are LangGraph interrupts; the approver's permission depends on the side effect.
- **Live events:** `GET /v1/tasks/{id}/stream` (SSE, `Last-Event-ID` resume, 5-minute re-auth window).
- **New APIs:** knowledge documents (text/Markdown/PDF), the idea board, and organisation memories.
- **Agents:** Creative (ideation, evaluation, Six Hats/SCAMPER/premortem/debate sessions, develop and hand off) and Research
  (deep research with verified citations, document analysis, fact check). A Research claim is only marked *verified*
  if its excerpt is found in a source collected during that run and re-confirmed before delivery.
- **Eval harness:** runs each suite end-to-end. The baseline is 29/29 machine checks in `docs/evals/`; rubric items stay pending until an LLM judge runs with live models.
- **Decisions:** [ADR 0003](docs/adr/0003-agent-engine-and-workers.md).

## Phase 4b — what's included

- **Live screens:** Overview, Agents, Agent workspace, Tasks, Task monitor, Collaboration, Billing, Settings and
  Admin → Models read the real API. Task pages follow the SSE stream (resume + backoff); plan, timeline, tool calls,
  logs and progress are **derived from persisted events**, never estimated. New **Knowledge** (upload/paste
  documents, organisation memories) and **Integrations** screens. The idea board saves moves and rejections.
- **Super-admin model routing:** choose provider and model per capability (reasoning, text, …) across OpenAI,
  Gemini and GN7T; set keys and base URLs. Super-admins can **Test** a provider (one tiny real request, with a readable reason on failure) and import its model list (imported models start disabled until reviewed). Changes persist and are audit-logged.
- **Web search (super-admin):** Admin → Models → Web search. Pick Brave Search or Gemini with Google Search grounding, optionally the other as a fallback, and test each. The Brave key is stored encrypted; Gemini grounding re-uses the Gemini provider key. The `AGENTFIRM_SEARCH_PROVIDER` / `AGENTFIRM_BRAVE_API_KEY` variables remain the default until an admin saves a choice.
- **Stop and delete:** Cancel or delete a task from its page; "Stop all" in the task list stops every running task in the workspace. Super-admins can stop one agent or every agent across all workspaces from Admin → Agents. Workers interrupt a stopped run within about two seconds, even in the middle of a model call.
- **Connectors:** GitHub (allow-listed repos, `agent/*` branches only), signed webhooks (bridge for social, ads,
  calendar, payments, purchases and deploys via n8n/Zapier/Make), SMTP (TLS only), GN7T data (read-only SQL),
  OSV dependency audit. Secrets are encrypted per connection; SSRF checks run on save and on every call.
- **Agents:** Marketing (content with brand/claim checks, publish, campaigns, budget changes, SEO, analytics),
  Engineer (repo review, change + tests in a sandbox, PR, dependency audit, deploys), BI (computed analysis,
  forecasts with intervals, charts with a table view, report schedules, automations) and Personal Assistant
  (inbox triage, email drafts and sends, calendar, travel, comparisons, purchases).
- **Approval authority:** gated tools run under the **approver's** permission, checked at decision time and again
  at execution. A rejection with `replan` continues without the action. Every gated tool must be executed by a
  later step (two spec bugs caught and fixed).
- **Integrity rules:** BI numbers are computed by `data.analyze` and uncomputed claims are downgraded; Engineer
  never proposes a PR while tests fail or haven't run; Assistant comparisons only include items it actually found;
  Marketing flags unsourced figures and absolute claims.
- **LLM judge:** `harness --judge` grades rubric items with the `reasoning` route (live models only).
- **Bug found in browser testing:** an SSE end-of-stream race left finished runs showing "Running". Fixed, with a
  regression test that fails on the old code.
- **Results:** 91/91 machine checks across all six agents (simulated models + fixture connectors), 194 API tests,
  browser end-to-end flows (register → knowledge → task → approval → result; integrations; admin routing).
- **Decisions:** [ADR 0004](docs/adr/0004-connectors-authority-and-live-screens.md).

| Task awaiting approval | Task result |
|---|---|
| ![](docs/screens/phase4b-task-approval.png) | ![](docs/screens/phase4b-task-result.png) |
| ![](docs/screens/phase4b-integrations.png) | ![](docs/screens/phase4b-knowledge.png) |

## Phase 5 — what's included

- **Orchestrator:** pick several agents, or none, and the orchestrator plans the work as a graph of subtasks.
  Each subtask runs as its own agent run, independent parts in parallel. Results are handed to the agents
  that need them (as data, never instructions), and everything is combined into one answer with what each
  agent did. Spec: [`docs/agents/orchestrator.md`](docs/agents/orchestrator.md).
- **Approvals across agents:** the orchestrator has no tools and can't approve anything. "Research the
  market, then write a LinkedIn post and publish it" still stops for a person before posting; rejecting it
  means nothing is published.
- **Handoffs:** an agent's handoff becomes a new subtask when delegation rules, depth, the user's agent
  selection and the task budget allow; otherwise it's offered as a one-click suggested next step.
- **Honest failure:** subtasks that depend on failed or stuck work are skipped with the reason; independent
  work finishes; the combined status says what happened.
- **Budgets:** one credit budget per task (`max_credits`), split across subtasks; a budget too small for
  the plan stops before any agent runs.
- **Screens:** live Collaboration page (pipeline, subtask graph, participants, approvals), subtask graph and
  merged timeline on the task page, "Orchestrated" badge, suggested next steps, orchestrator usage on
  Billing. Task composers now start real multi-agent tasks.
- **Results:** 12/12 orchestrator eval cases and all six agent suites (simulated models + fixture
  connectors), 204 API tests, browser end-to-end (compose → plan → research → handoff → approval → result).
- **Decisions:** [ADR 0005](docs/adr/0005-orchestrator.md).

| Collaboration waiting for approval | Collaboration page |
|---|---|
| ![](docs/screens/phase5-task-waiting.png) | ![](docs/screens/phase5-collaboration.png) |

## Phase 6 — what's included

- **Plans & credits:** Free, Pro and Business plans (super-admin editable) with a monthly credit allowance plus
  purchased credits that never expire. Usage is charged per model call; the server stops new tasks **and running
  model calls** when a workspace runs out, and enforces seats, tasks-at-a-time and plan agents.
- **Paddle Billing:** upgrade, switch plans (prorated), buy credit packs, manage payment methods and invoices in
  Paddle's customer portal, cancel at period end. The server creates every checkout; only verified Paddle webhooks
  change plans, invoices or credits (signature, timestamp window, idempotent). Fixture mode simulates Paddle end to
  end for development and demos.
- **Platform admin (super-admins):** plans and prices, credit packs, workspaces (grant credits, invoiced plans), agents
  (turn off, roll back a version), tools (kill-switch), Paddle webhook log. Everything is audit-logged.
- **Standing approvals:** pre-approve a recurring action (e.g. the weekly report email to your own domain) with
  conditions, a use limit and an expiry. Never for production deploys or deletions; stops applying if its creator
  loses the authority.
- **Reply to continue:** when a task asks a question, answer it on the task page; orchestrated tasks reuse the
  subtasks that already finished.
- **Decisions:** [ADR 0006](docs/adr/0006-monetization-and-governance.md).

**Going live with Paddle (sandbox first):** create products and monthly prices (plans) and one-time prices
(credit packs) in Paddle; set the default payment link to `https://<app>/billing/checkout` and get the domain approved;
add a notification destination `https://<domain>/api/paddle/webhook` (or `https://<domain>/v1/billing/paddle/webhook` behind the Caddy setup, which routes it straight to the API) (subscription.* and transaction.completed);
set `AGENTFIRM_PADDLE_MODE=live`, the API key, webhook secret and `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`; enter prices and
`pri_…` IDs in Platform → Plans. Then test: subscribe, upgrade, top-up, cancel and a failed payment.

| Usage & Billing (after upgrading) | Platform → Plans & pricing |
|---|---|
| ![](docs/screens/phase6-billing.png) | ![](docs/screens/phase6-admin-plans.png) |

## Phase 7 — what's included

- **Security review** ([docs/security/review-2026-11.md](docs/security/review-2026-11.md)): 10 findings, each fixed or
  accepted with a reason. Fixes include:
  - BI identifier injection.
  - Security headers and CSP on web and API.
  - Body limits, including chunked bodies.
  - Trusted proxies and no public OpenAPI.
  - Sandboxed artifact downloads.

  Bandit, pip-audit and npm audit are clean.
- **Hardening found by testing:**
  - The load test exposed a sign-up race (500) and Argon2 blocking the event loop. Both are fixed.
  - The restore drill caught orphan rows. They are cleaned, and `verify.sql` now checks for them on every restore.
- **Observability:** JSON logs with request IDs, Prometheus metrics (token-protected `/metrics` on the API, worker on
  `:9101`) and `/readyz`. Ten alert rules map to SLOs and runbook sections, alongside a Grafana dashboard, Alertmanager and
  node/postgres exporters (`deploy/observability/`).
- **Backups:** encrypted with `age` and sent to R2 every 6 h, plus before every deploy. Retention is 35 daily and about 13 monthly.
  - Restore with `deploy/backup/restore.sh`. [Drill report](docs/ops/restore-drill-2026-11-17.md).
- **Load test:** Locust (`deploy/loadtest/`), 100 users. Steady-state p95 is 41–66 ms with 0 errors.
  [Report](docs/ops/load-test-2026-11-17.md).
- **Production stack:** `deploy/docker-compose.prod.yml` and `deploy/Caddyfile` (TLS, HSTS, admin IP allowlist,
  private metrics). VPS hardening in `deploy/provision.sh`.
- **CI/CD:** `.github/workflows/ci.yml` covers tests, scans, builds and config checks. `deploy.yml` builds SHA-tagged images to GHCR,
  then runs `deploy/deploy.sh`: backup → migrate → roll out → health checks → automatic rollback.
- **Operations:** [runbook](docs/ops/runbook.md) (deploy, rollback, restore, secret rotation, alerts),
  `scripts/rotate_master_key.py`, and the [launch checklist](docs/ops/launch-checklist.md).
- **Decisions:** [ADR 0007](docs/adr/0007-production-readiness.md).

**Verified here vs. on the server:**
- **Verified here:** tests, scans, Caddy and Prometheus configs (run with the real binaries), the restore drill and the load test.
- **Not verified here:** this build environment has no VPS and no Docker daemon. The first real deploy, a restore drill on
  the server, a live Paddle sandbox run, live-model evals and an **external penetration test** are on the launch checklist.

## Deploying

Two supported ways to run AgentFirm in production on a single server:
- **VPS Control Center, no Docker:** four applications plus PostgreSQL and Redis on the same server. Run
  `deploy/vcc/setup-server.sh`, then follow [docs/ops/deploy-vps-control-center.md](docs/ops/deploy-vps-control-center.md)
  (it includes every environment variable).
- **Docker Compose + Caddy:** `deploy/docker-compose.prod.yml`, `deploy/deploy.sh` and the CI workflows. See the
  [runbook](docs/ops/runbook.md).

## Demo data policy

All Phase-1 data lives in `web/src/mocks/` and every screen that uses it shows a **Demo data**
badge. The execution timeline is a scripted replay that has the same shape as the planned SSE
stream (`web/src/lib/events/types.ts`). Progress is computed from plan steps, and `null` renders an
indeterminate indicator. The app never shows an invented percentage.

## Next

All seven phases are delivered. Before launch, work through [docs/ops/launch-checklist.md](docs/ops/launch-checklist.md):
- the first VPS deploy;
- the restore drill and load test, repeated on the server;
- the Paddle sandbox run;
- live-model evals with the judge;
- an external pen test.

Open risks are listed in `docs/ARCHITECTURE.md` §9: 2FA (R-12), the egress proxy (R-15/R-21), CSP (R-29), PITR (R-30).
