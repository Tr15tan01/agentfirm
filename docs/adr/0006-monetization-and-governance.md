# ADR 0006: Plans, credits, Paddle billing, platform admin and standing approvals

- **Status:** Accepted (Phase 6)
- **Date:** 2026-11-17
- **Context:** The platform needs paid plans with server-enforced limits, a billing provider (the owner chose **Paddle**), super-admin control over pricing, agents and tools, a way for recurring automations to run without a person approving every action, and a way to continue a task that stopped to ask a question.

## Decisions

### 1. Plans and a two-bucket credit balance
- **Plans** (platform table, super-admin managed) set the monthly credit allowance, seats, concurrent tasks and, optionally, which agents are included.
- **Paid plans start without a price.** Pricing is a business decision, so a paid plan can only be bought once a super-admin sets a price *and* its Paddle price ID.
- **Two credit buckets:**
  - **plan:** the monthly allowance. It resets each period and never rolls over.
  - **purchased:** top-ups and admin grants, kept until used.
- **How usage is charged:** usage draws from the plan bucket first. It is charged in the same transaction as the usage record, with one `UPDATE`, so two concurrent charges can't spend the same credit.
- **Ledger:** every grant goes to an append-only `credit_ledger`. The app role has no UPDATE or DELETE on it, and each entry has a unique idempotency reference.
- **Periods:**
  - Free and manual plans roll monthly, in the worker or on read.
  - Paddle plans move only on Paddle's webhooks, so access matches what was paid.

### 2. Limits are enforced on the server
| Limit | Where |
|---|---|
| Credits > 0 | Task creation (402 `out_of_credits`), **and before every model call**: a running task stops with `budget_exceeded` when the workspace runs dry |
| Concurrent tasks | Task creation (429 `plan_concurrency`) |
| Seats | Invitation and acceptance (402 `plan_seats`) |
| Agents in plan | Task creation (402 `plan_agent`), and the orchestrator's candidate list |
| Tool kill-switch | Tool runtime, before any other check |
| Agent turned off | Task creation (404) and engine load (queued runs fail with a clear reason) |

### 3. Paddle Billing
- **Checkout:**
  - The server creates a Paddle transaction for the price, with `custom_data = {org_id, kind, key}` set from the session, so the browser never picks the organisation or the price.
  - The returned `checkout.url` is the approved default payment link plus `?_ptxn=`. Our `/billing/checkout` page loads Paddle.js, which opens Paddle's overlay; card details never touch AgentFirm.
- **Webhooks are the only source of truth:**
  - **Verification:** `Paddle-Signature: ts=…;h1=…` is checked as HMAC-SHA256 over `ts:rawBody` with the notification secret. The comparison is constant-time, accepts any `h1` (for secret rotation), and rejects timestamps more than 5 minutes off.
  - **Idempotency:** each event is stored once by its `event_id`.
  - **Mapping:** subscription events map a price ID to a plan, start a new allowance when the billing period changes, and adjust the allowance by the difference when the plan changes mid-period. `canceled` moves the workspace to Free but keeps purchased credits.
  - **Transactions:** `transaction.completed` records an invoice, and grants pack credits once, keyed by `paddle:<txn>`.
  - **Errors:** permanent errors (unknown price or organisation, customer mismatch) are stored and acknowledged so Paddle doesn't retry forever, and listed for super-admins.
- **Plan changes** go through the subscriptions API (`PATCH`, prorated immediately), because the customer portal can't change plans. **Payment methods, invoices and cancellation details** go through customer-portal sessions; we cancel at period end through the API.
- **Modes:**
  - `fixture` simulates Paddle in-process. Its checkout completes through the *same* signed-webhook code path, for dev, CI and demos, and production refuses it.
  - `disabled` turns paid plans off.
  - `live` needs the API key and the webhook secret (the server refuses to start without them).

### 4. Platform administration
Super-admin endpoints manage:
- plans and prices, and credit packs;
- workspaces: credit grants and removals, manually invoiced plans (refused for Paddle-managed subscriptions);
- tool kill-switches;
- agent on/off and version rollback;
- the billing event log.

Every change is checked on the server and audit-logged with its before and after values. `billing_events` is a platform log written before the organisation is known, so it has no RLS and no `org_id` column.

### 5. Standing approvals
- **What it is:** a pre-approval for one gated tool, optionally for one agent, with conditions over *facts the agent program reports* about the prepared action:
  - channel;
  - amount, currency and payee;
  - recipient domains and count;
  - number of targets;
  - environment and repository.
  Conditions fail closed when a fact is missing.
- **Limits:**
  - Only `external` and `financial` tools, never `destructive` ones such as production deploys.
  - Financial tools need an `amount ≤` cap.
  - An expiry of at most 90 days, and 1 to 1,000 uses, counted atomically.
- **Authority:**
  - The creator must be able to approve the action themselves (ADR 0004).
  - This is re-checked against their *current* role at every use, so demoting the creator stops it.
- **Each use** is recorded as an approved approval request linked to the standing approval, with `approval.requested` and `approval.resolved` events on the run. Creating and revoking are audit-logged.

### 6. Replying resumes a task
- `POST /v1/tasks/{id}/reply` starts a new attempt when the task's result is `needs_input`. The answer is added to the objective.
- **Orchestrated tasks:**
  - The new attempt keeps the previous plan and *copies* finished subtasks' results, without re-running them. Their actions (posts, emails) are never repeated.
  - It re-runs only the stuck and skipped subtasks; the stuck ones get the answer.
  - If the previous attempt stopped before planning, it plans afresh.

## Consequences and limits
- Pricing, Paddle catalog IDs and the default payment link must be set by the operator; nothing is guessed.
- Not built yet:
  - **Taxes, invoices and receipts:** handled by Paddle as merchant of record. AgentFirm stores only the totals and links to Paddle's PDF.
  - **Seat-based pricing and metered overage billing:** not built.
  - **Annual plans:** they work if their Paddle price is annual, but the credit allowance still resets monthly per the plan, and annual allowances aren't modelled.
- `FixturePaddle` keeps state in memory, so a fixture checkout must complete on the same API process. That's fine for development and demos, and the mode isn't allowed in production.
