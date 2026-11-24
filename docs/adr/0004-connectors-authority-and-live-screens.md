# ADR 0004: Connectors, approval authority and live screens

- **Status:** Accepted (Phase 4b)
- **Date:** 2026-11-17
- **Context:** The Marketing, Engineer, BI and Assistant agents act on outside systems: repositories, ad accounts, calendars, mailboxes, payment providers, deploy targets and GN7T. Their approval rules come from the spec, but the evals expect a member to *request* actions that only an admin or owner can authorise. The web screens also had to move from demo data to the live API without weakening the Phase 3 session design.

## Decisions

### 1. Approval authority belongs to the approver
- **Ordinary tools** run with the *requesting user's* permission.
- **Approval-gated tools** are authorised by the *approver*. The approver must hold both the side-effect approver class (external → `approvals:decide`, financial → `billing:manage`, destructive → `agents:configure`) and the tool's own `required_permission`.
- This is checked when the decision is recorded (403 otherwise), and checked again by the tool runtime against the approver's **current** role at execution time.
- So a member can ask for a production deploy that an admin approves, and an admin can prepare an ad-budget change that only an owner can approve.
- The Agent Interface spec §6 has been updated to match.

Approval steps also gained two outcomes besides approve/reject:
- **`not_requested`:** the user didn't ask for the gated action (for example "refactor" without "open a PR"), so nothing is requested and nothing runs.
- **`rejected`:** with `on_failure: replan` or `skip`, the run continues without the action and reports the approver's note (Marketing proposes a revised post). With other policies the result is `needs_input`.

A new registry invariant requires every gated tool to be executed by a **later** step of the same workflow. It caught two spec bugs, both now fixed:
- Assistant `discovery.purchase` had no step that made the purchase.
- Engineer `implement_change.pull_request` had no step that opened the pull request.

### 2. Connectors
| Kind | Used by | Notes |
|---|---|---|
| `github` | `repo.read`, `repo.write_branch`, `repo.open_pull_request`, sandbox file sync | Allow-listed repositories only. Writes go only to `agent/*` branches, never to the default or a protected branch, and never to `.git/` or `.github/workflows/` paths. All of this is enforced in code before any request. |
| `webhook` | social posts, ad budgets and performance, keywords, calendar, automations, payments, purchases, deploys, email (alternative to SMTP) | The organisation routes actions to n8n, Zapier, Make or its own service. Body `{action, organization_id, execution_id, idempotency_key, args}`. Header `X-AgentFirm-Signature: t=<unix>,v1=HMAC-SHA256(secret, "t.body")` plus `Idempotency-Key`. HTTPS on a public address only, checked when saved **and** on every call. Redirects are never followed and responses are capped at 1 MB. |
| `smtp` | `email.send` | TLS only: port 465, or 587 with STARTTLS required before login. The Message-ID comes from the idempotency key. |
| `gn7t` | `gn7t.query` | Read-only is enforced here: one `SELECT`/`WITH` statement with no write keywords, plus `read_only: true` in the request. |
| (public) | `deps.audit` | OSV.dev batch API. |

- Secrets are envelope-encrypted with an AAD bound to the organisation and the connection. The API only ever returns `secret_last4`; a generated webhook secret is shown once.
- Connections are scoped by RLS like every tenant table, and every change is audit-logged.
- **Native OAuth connectors** (Google and Microsoft calendars and mail, LinkedIn, Meta Ads) are not built yet. Until then the webhook connector bridges them (R-19).

### 3. Fixture world (`AGENTFIRM_CONNECTOR_MODE=fixture`)
In development, CI and evals, every external system is replaced by a deterministic in-memory **fixture world**: a billing-service repository, an ad account, a calendar, an outbox, GN7T datasets and advisories.
- Every output carries `fixture: true`. Results add a "Fixture data" note, and approval previews say "Prepared from FIXTURE data".
- **Production refuses to start** with fixture connectors or the fixture sandbox, just as it does with simulated models.

### 4. Code execution
`sandbox.exec` has three backends:
- **`docker`:** no network, read-only root, non-root user, all capabilities dropped, memory/CPU/PID limits, wall-clock timeout.
- **`fixture`:** never executes anything. Results are labelled "not a real test run".
- **`disabled`.**

The Engineer marks a change `partial` unless a test run passed. It never proposes a PR while tests fail or haven't run.

**Limitation:** this workspace has the Docker client but no daemon, so only the docker command line (flags) is tested here (R-18). Mounting the host Docker socket into the worker would give it root on the host, so `docker-compose.yml` ships with `SANDBOX_BACKEND=disabled`. Production needs a separate sandbox host (rootless Docker or gVisor) before code execution is enabled.

### 5. Numbers are computed, not generated
`data.analyze` is a declarative pandas engine:
- **Operations:** profile, filter, derive, group, sort, limit, time series, percentage change, linear forecast with an 80% interval, cohort retention, weighted scoring and sensitivity.
- **No generated code runs.**
- **Interpretation check:** BI checks every number in its interpretation against the computed values. A "computed" finding that quotes a figure nobody computed becomes an `assumption`.
- **Labels:** forecasts and model-estimated scoring inputs are `estimate`; computed facts cite the dataset.
- **Bad data:** if key columns are more than 20% empty, the analysis stops and asks the user.

### 6. Report schedules
- **Cadence grammar:** a deliberately small `daily@HH:MM | weekly:<day>@HH:MM | monthly:<1-28>@HH:MM` in an IANA time zone (DST-correct); no cron.
- **Running:** the worker turns due schedules into tasks *as their creator*, re-checking that the creator is still an active member with `tasks:create`; otherwise the schedule is disabled. Runs are idempotent per due time.
- **No self-replication:** a scheduled run passes `schedule: off`, so a weekly report can't create a new schedule every week.

### 7. Live screens load in the browser
- **Constraint:** the refresh cookie is scoped to `/api` (ADR 0001), so server components can't refresh an expired session. Rather than widen it, live screens load through the BFF in the browser.
- **Loading:** `useResource` (suspense + stale-while-revalidate cache) feeds the same components the demo uses. `LiveBoundary` renders only after hydration and shows sign-in, forbidden and retry states.
- **Live runs:** task pages follow the SSE stream (`useTaskStream`, resuming from the last event id). The plan, timeline, tool calls, logs and progress are **derived from persisted events** (`lib/events/derive.ts`), never estimated.
- **No demo leftovers in live mode:** the sidebar plan widget, the task badge, the notification dot and the "Live agent core" demo are hidden or replaced with real state. Billing says plainly that plans and invoices arrive with the billing provider.

### 8. SSE end-of-stream race (bug found in browser testing)
The engine commits the terminal status a moment before its final `execution.status` event. The stream could see "completed", end, and never deliver that event, leaving the UI on "Running". The stream now ends only after it has delivered a terminal status event, or after a short grace period for runs that end without one. The client also refetches when the stream closes. A regression test reproduces the race and was confirmed to fail on the old code.

## Assumptions to confirm
- **GN7T API (R-1):** `GET /v1/datasets` and `POST /v1/query {query, read_only, max_rows}` returning `{columns, rows}`, with Bearer auth.
- **GN7T as a model provider (R-2):** OpenAI-compatible `/chat/completions` at an admin-set base URL. Tea-800 was dropped later.
- **Search-backed listings:** jobs and places come from web search in live mode, since no listing API was specified.
