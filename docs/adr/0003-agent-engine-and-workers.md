# ADR 0003: Agent Engine, workers and simulated mode

- **Status:** Accepted (Phase 4a)
- **Date:** 2026-11-16
- **Context:** Agents must run durably (survive worker crashes and deploys), stop for human approval, stream honest progress, never repeat side effects, and stay isolated per tenant. They also need to be testable in CI without paid model calls or internet access.

## Decisions

### 1. The database is authoritative; Redis only wakes things up
Executions are claimed with a compare-and-swap `UPDATE … SET lease_owner, lease_expires_at WHERE (lease expired or NULL)`. A heartbeat extends the lease every `lease/3` seconds. If a worker dies, its lease lapses and any worker resumes the execution. `claimable_executions()` is a narrow `SECURITY DEFINER` function that returns only `(id, org_id)` of claimable roots. Every subsequent read or write runs under that execution's org context, so RLS applies to workers too.

Redis carries an advisory wake-up stream (`af:wake`) and per-task pub/sub for SSE. Losing Redis only adds poll latency (2 s for workers, 1 s for streams).

*Rejected:* Celery/RQ/Arq task queues. A queue message and the execution row can disagree after a crash; leases on the row cannot.

### 2. One LangGraph graph per execution, checkpointed in Postgres
The engine builds a `StateGraph` from the pinned agent version's workflow. It creates one node per step, fans parallel groups out and back in, and runs with `AsyncPostgresSaver` (`thread_id = execution id`, `durability="sync"`). The checkpoint tables are created by Alembic, not `setup()`, and are internal to the worker (no tenant column, and they are never exposed through the API).

### 3. Exactly-once steps and side effects
- **Steps:** each step's output is written to `step_results` in the same transaction as its `step.completed` event. On resume, a node whose result exists is restored from that record instead of re-run. This covers the gap between a node finishing and LangGraph's checkpoint commit, which the kill-worker test hit in practice.
- **Tools:** side-effecting tool calls are keyed `execution:step:tool:n` in `tool_executions`. A replay returns the stored output and doesn't call the tool again.
- **Events:** every event of a task is serialized by a `FOR UPDATE` on the task row, so event ids become visible in id order. The SSE cursor (`id > Last-Event-ID`) therefore never skips one. API-side row locks on executions use `FOR NO KEY UPDATE` to avoid deadlocking with event inserts.

### 4. Approvals are interrupts
An approval step creates (idempotently) an `approval_request` with an exact preview, sets `waiting_approval` and calls `interrupt()`. A decision re-queues the execution, and the worker resumes with `Command(resume=…)`. Who may decide depends on the side effect: external → `approvals:decide`, financial → `billing:manage`, destructive → `agents:configure`. A rejection returns `needs_input` with the approver's note. The gated tool is never called.

### 5. Enforcement lives in one place
Programs reach models and tools only through `ExecutionContext`. Tool calls are checked in this order: manifest grant → the **step's declared tools** → the requesting user's permission → per-run call cap → approval → deny policy → credit budget → idempotent replay → timeout. Model calls must use a capability the manifest allows. Step identity is task-local *and* per-execution (a `ContextVar`), because LangGraph runs parallel nodes concurrently.

### 6. Simulated mode (dev/CI/evals only)
`AGENTFIRM_GATEWAY_MODE=simulated` routes through the real route table, fallback order, circuit breaker, usage records and credits. Only the provider HTTP call is replaced by a deterministic local simulator. Every `model.called` event carries `simulated: true`, and usage rows are labelled `(simulated)`. `AGENTFIRM_WEB_MODE=fixture` serves search and pages from a fixture corpus. **Production refuses to start in either non-live mode.**

### 7. Honest failure
- Seeded pre-specification agent versions are not executable. They fail with a message telling the operator to publish the specification manifest.
- Agents with a manifest but no program (Marketing, Engineer, BI and Assistant until Phase 4b) fail with "not implemented yet".
- Budget exhaustion returns a `partial` result and keeps real progress.
- Low intent confidence returns `needs_input` with a question.
- Progress stays `null` until a plan exists.

## Provider assumptions (to confirm)
- **GN7T and Tea-800** are assumed to be OpenAI-compatible (`/chat/completions`, `max_tokens`, `response_format: json_object`), each with an admin-configured `base_url`. If either differs, it needs its own adapter; the gateway interface doesn't change. (R-1, R-2)
- **Web search** defaults to the Brave Search API (`AGENTFIRM_BRAVE_API_KEY`). The provider sits behind `web.search` and can be swapped.
- **OpenAI** uses Chat Completions with `max_completion_tokens` and native JSON-schema output. It retries once without `temperature` for models that reject it. **Gemini** uses `generateContent` with the key in the `x-goog-api-key` header (never the URL).

## Known limitations
- **DNS rebinding:** `web.fetch` checks resolved addresses before connecting, but the HTTP client resolves again (a TOCTOU gap). Production should send agent egress through a filtering proxy (e.g. smokescreen) on the VPS (R-15).
- Retrieval is keyword-only (`tsvector`). pgvector embeddings arrive with the embeddings capability route (R-16).
- Child executions for multi-agent tasks wait for the Phase 5 orchestrator. `agents.delegate` records the handoff in the result but doesn't spawn it yet.
- Rubric items in eval suites need an LLM judge with live models. In simulated mode they are reported as *pending*, never as passed.
