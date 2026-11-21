# ADR 0005: Orchestrator and multi-agent collaboration

- **Status:** Accepted (Phase 5)
- **Date:** 2026-11-17
- **Context:** Tasks that need several agents (research → post, analysis → email) had no coordinator: a
  multi-agent task created child executions that never ran, and agent handoffs were recorded but ignored.
  The brief requires an orchestrator that plans, assigns, runs independent work in parallel, passes
  context, keeps human approval gates and merges results.

## Decisions

### 1. The orchestrator is an execution kind, not an agent
`task_executions.kind = orchestrator`, with no agent version. Giving it a manifest would put it in the agent
directory, routing and evals as if it could act. It can't: **it has no tools**. Every action is an agent
subtask with that agent's grants, the requester's permissions and its own approvals. It shares the
`ExecutionContext` (model routing, credits, events) through a small profile with two capabilities:
`reasoning` (plan) and `summarize` (overview).

### 2. Subtasks are ordinary executions
Children of the orchestrator carry their own `objective`, `parameters`, `context.upstream`,
`depends_on`, `delegation_depth`, `origin` and budget, and run through the unchanged agent engine. New
statuses: `blocked`, `waiting_subtasks`, `skipped`. Workers now claim children (blocked ones are not
claimable).

### 3. A durable state machine, not a long-lived graph
The orchestrator doesn't hold a LangGraph run open for hours while subtasks wait for approvals. Each turn
reads the persisted state (plan event, subtask rows, acknowledgement events), advances it idempotently and
goes idle. The plan is persisted before subtasks are created; subtask keys are unique. A finishing subtask
wakes the orchestrator inside its final status transaction, under the orchestrator's row lock, and the
orchestrator re-checks under that lock before sleeping. This closes the lost-wake-up race.

### 4. Results pass as untrusted data
Upstream results are injected into the receiving agent's prompts as `<untrusted source="agent:…">` blocks
(one per upstream agent, closing tags neutralised). They inform the work; they can't change tools,
approvals or permissions, because those are enforced in code, per execution.

### 5. Handoffs are followed under policy
Agent handoffs become subtasks only within delegation policy, the user's agent selection, depth,
subtask and budget limits, and the cycle rule. Otherwise they're recorded with the reason and offered to
the user as one-click suggestions. Single-agent tasks keep handoffs as suggestions.

### 6. Failure is explicit
Dependents of a failed, skipped or input-needing subtask are skipped with the reason; independent work
continues. The combined status is computed, not generated: `completed`, `needs_input`, `partial` or
`failed`.

### 7. Budgets are task-wide
A multi-agent task has one credit budget, split across subtasks (capped by each agent's limit), with 60
credits kept for planning and synthesis. A plan the budget can't cover stops before any agent runs.

### 8. UI derives everything from events
The task page and the Collaboration page build the subtask graph, plan, timeline, tool calls and logs
from the persisted events of every execution in the task, each attributed to its agent on one clock.
Orchestrator-internal states are mapped for users (waiting for subtasks → Running; a subtask awaiting
approval → Needs approval).

## Consequences
- Collaboration needs no new infrastructure: same workers, events, SSE and approvals.
- Planning quality depends on the `reasoning` model; CI uses a deterministic clause router and measures
  machinery only (12/12 orchestrator eval cases in simulated mode; rubric items need live models).
- Known gaps: no re-planning after failure; answering a subtask's question doesn't resume the task; an
  upstream subtask that completes with no useful output still releases its dependents (R-23).
