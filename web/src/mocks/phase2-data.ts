/**
 * ⚠ DEMONSTRATION DATA — NOT PRODUCTION. Phase-2 fixtures consumed only by
 * src/mocks/adapter.ts. Shapes match src/lib/api/contracts.ts.
 */
import type {
  AgentProfile,
  ChatMessage,
  Conversation,
  Idea,
  Member,
  TaskDetail,
  TaskRunSummary,
  ThinkingApproach,
} from "@/lib/types";
import { DEMO_AGENTS, DEMO_TASKS, DEMO_TIMELINE } from "./demo-data";

const summary = (key: AgentProfile["key"]) => DEMO_AGENTS.find((a) => a.key === key)!;

export const PROFILES: Omit<AgentProfile, "models">[] = [
  {
    ...summary("research"),
    version: "v1.4.0",
    mission: "Conduct structured research and turn documents and external sources into cited, verifiable knowledge.",
    capabilities: ["Web research", "Document analysis", "Semantic search", "Fact verification", "Source comparison", "Literature reviews", "Cited reports"],
    modelCapabilities: ["reasoning", "summarize", "long_context", "embeddings"],
    tools: [
      { key: "web.search", label: "Web search", sideEffect: "none", approval: "auto" },
      { key: "web.fetch", label: "Fetch page", sideEffect: "none", approval: "auto" },
      { key: "knowledge.retrieve", label: "Knowledge retrieval", sideEffect: "none", approval: "auto" },
      { key: "docs.parse", label: "Document parser", sideEffect: "none", approval: "auto" },
      { key: "artifact.write", label: "Write report", sideEffect: "internal", approval: "auto" },
    ],
    usage: { requestsMonth: 1420, successRate: 0.97, avgDurationSec: 412, creditsMonth: 1180 },
    recentExecutions: [
      { id: "exe_01JD8K4V9R", taskId: "tsk_7Q2M", title: "English-learning market scan", status: "running", durationSec: 1122, finishedSecondsAgo: 0 },
      { id: "exe_01JD7Z1M2Q", taskId: "tsk_4R7N", title: "Competitor teardown: 8 tutoring platforms", status: "completed", durationSec: 1460, finishedSecondsAgo: 9800 },
      { id: "exe_01JD6P0W3E", taskId: "tsk_6T1C", title: "EU AI Act obligations summary", status: "completed", durationSec: 640, finishedSecondsAgo: 172_000 },
    ],
    knowledgeSources: [{ name: "pricing-notes.pdf", kind: "file", detail: "412 KB · indexed" }, { name: "Market research folder", kind: "file", detail: "23 documents" }, { name: "Web", kind: "web", detail: "Search + fetch" }],
  },
  {
    ...summary("marketing"),
    version: "v1.2.1",
    mission: "Plan, create and evaluate on-brand marketing — never publishing or spending without authorization.",
    capabilities: ["Positioning", "Audience analysis", "Campaign briefs", "Content calendars", "SEO & keywords", "Ad copy", "Performance analysis"],
    modelCapabilities: ["text", "creative", "classify"],
    tools: [
      { key: "brand.memory", label: "Brand memory", sideEffect: "none", approval: "auto" },
      { key: "seo.keywords", label: "Keyword research", sideEffect: "none", approval: "auto" },
      { key: "social.publish", label: "Publish to social", sideEffect: "external", approval: "require_approval" },
      { key: "ads.budget", label: "Ad budget changes", sideEffect: "financial", approval: "require_approval" },
    ],
    usage: { requestsMonth: 812, successRate: 0.95, avgDurationSec: 188, creditsMonth: 610 },
    recentExecutions: [
      { id: "exe_01JD8H0Q8Z", taskId: "tsk_2B6R", title: "Publish LinkedIn launch post", status: "waiting_approval", durationSec: 2140, finishedSecondsAgo: 0 },
      { id: "exe_01JD5S2K7A", taskId: "tsk_3M8V", title: "November content calendar", status: "completed", durationSec: 520, finishedSecondsAgo: 260_000 },
    ],
    knowledgeSources: [{ name: "Brand voice", kind: "memory", detail: "Confident · warm · plain" }, { name: "Brand guidelines.pdf", kind: "file", detail: "v2 · indexed" }, { name: "LinkedIn", kind: "connector", detail: "Company page" }],
  },
  {
    ...summary("engineer"),
    version: "v2.0.3",
    mission: "Design, build, debug and maintain software — traceable changes, tests actually executed.",
    capabilities: ["Architecture", "Code generation", "Code review", "Debugging", "Testing", "API & DB design", "Documentation"],
    modelCapabilities: ["code", "reasoning", "long_context"],
    tools: [
      { key: "repo.read", label: "Repository read", sideEffect: "none", approval: "auto" },
      { key: "repo.write", label: "Commit to branch", sideEffect: "internal", approval: "auto" },
      { key: "sandbox.exec", label: "Sandboxed execution", sideEffect: "internal", approval: "auto" },
      { key: "deploy.preview", label: "Preview deploy", sideEffect: "external", approval: "require_approval" },
      { key: "deploy.production", label: "Production deploy", sideEffect: "destructive", approval: "require_approval" },
    ],
    usage: { requestsMonth: 1106, successRate: 0.91, avgDurationSec: 734, creditsMonth: 1640 },
    recentExecutions: [
      { id: "exe_01JD8M2C1T", taskId: "tsk_3K9P", title: "Refactor billing webhooks", status: "running", durationSec: 486, finishedSecondsAgo: 0 },
      { id: "exe_01JD8A9X4F", taskId: "tsk_9F0A", title: "Deploy preview environment", status: "failed", durationSec: 302, finishedSecondsAgo: 7_200 },
      { id: "exe_01JD7C3B6H", taskId: "tsk_1P5Z", title: "api-spec-billing-v2.yaml", status: "completed", durationSec: 890, finishedSecondsAgo: 5_400 },
    ],
    knowledgeSources: [{ name: "northwind/platform", kind: "repo", detail: "main · read/write branch" }, { name: "Architecture notes", kind: "file", detail: "14 docs" }, { name: "Sandbox", kind: "connector", detail: "Python 3.13 · Node 22" }],
  },
  {
    ...summary("bi"),
    version: "v1.1.0",
    mission: "Explain business performance, surface opportunities and run approved automations.",
    capabilities: ["KPI monitoring", "Cohort analysis", "Forecasting", "Opportunity scoring", "Spreadsheet analysis", "Workflow automation"],
    modelCapabilities: ["reasoning", "code", "summarize"],
    tools: [
      { key: "gn7t.query", label: "GN7T data query", sideEffect: "none", approval: "auto" },
      { key: "python.analyze", label: "Data analysis sandbox", sideEffect: "none", approval: "auto" },
      { key: "schedule.report", label: "Scheduled reports", sideEffect: "internal", approval: "auto" },
      { key: "automation.run", label: "Run automation", sideEffect: "external", approval: "require_approval" },
    ],
    usage: { requestsMonth: 511, successRate: 0.98, avgDurationSec: 521, creditsMonth: 740 },
    recentExecutions: [
      { id: "exe_01JD8E5R2L", taskId: "tsk_5H2D", title: "Q3 revenue cohort report", status: "completed", durationSec: 1880, finishedSecondsAgo: 1_380 },
    ],
    knowledgeSources: [{ name: "GN7T Database Service", kind: "connector", detail: "Read-only · 12 tables" }, { name: "Finance exports", kind: "file", detail: "8 spreadsheets" }],
  },
  {
    ...summary("assistant"),
    version: "v1.0.6",
    mission: "Handle everyday requests and coordinate specialists when a task needs one.",
    capabilities: ["Scheduling", "Email drafting", "Travel & service research", "Job search", "Task coordination", "Delegation"],
    modelCapabilities: ["text", "classify", "summarize"],
    tools: [
      { key: "calendar.read", label: "Calendar read", sideEffect: "none", approval: "auto" },
      { key: "calendar.write", label: "Create events", sideEffect: "external", approval: "require_approval" },
      { key: "email.draft", label: "Draft email", sideEffect: "internal", approval: "auto" },
      { key: "email.send", label: "Send email", sideEffect: "external", approval: "require_approval" },
      { key: "agents.delegate", label: "Delegate to agent", sideEffect: "internal", approval: "auto" },
    ],
    usage: { requestsMonth: 259, successRate: 0.93, avgDurationSec: 96, creditsMonth: 120 },
    recentExecutions: [
      { id: "exe_01JD7Q8N1D", taskId: "tsk_8C2K", title: "Calendar sync", status: "failed", durationSec: 14, finishedSecondsAgo: 14_200 },
    ],
    knowledgeSources: [{ name: "Google Calendar", kind: "connector", detail: "Token expired — reconnect" }, { name: "Preferences", kind: "memory", detail: "Working hours, tone" }],
  },
  {
    ...summary("creative"),
    version: "v1.3.0",
    mission: "Help you think: generate, challenge and evaluate ideas, then hand the best ones to other agents.",
    capabilities: ["Idea generation", "Naming", "Product innovation", "Scenario planning", "Critical evaluation", "Six Hats & SCAMPER"],
    modelCapabilities: ["creative", "reasoning"],
    tools: [
      { key: "ideas.board", label: "Idea board", sideEffect: "internal", approval: "auto" },
      { key: "brainstorm.engine", label: "Brainstorming engine", sideEffect: "none", approval: "auto" },
      { key: "agents.handoff", label: "Send idea to agent", sideEffect: "internal", approval: "auto" },
    ],
    usage: { requestsMonth: 704, successRate: 0.99, avgDurationSec: 74, creditsMonth: 390 },
    recentExecutions: [
      { id: "exe_01JD8N7H4B", taskId: "tsk_8V1X", title: "Tutoring product names", status: "running", durationSec: 38, finishedSecondsAgo: 0 },
    ],
    knowledgeSources: [{ name: "Idea board", kind: "memory", detail: "8 ideas · 2 shortlisted" }, { name: "Tutoring launch brief", kind: "file", detail: "Project context" }],
  },
];

/* ── Conversations ──────────────────────────────────────────── */

export const CONVERSATIONS: Conversation[] = [
  { id: "cnv_r1", agent: "research", title: "English-learning market, CEE", preview: "Here's the evidence summary with sources…", updatedSecondsAgo: 60, project: "Tutoring launch", pinned: true },
  { id: "cnv_r2", agent: "research", title: "EU AI Act obligations", preview: "Obligations for limited-risk systems…", updatedSecondsAgo: 172_000 },
  { id: "cnv_r3", agent: "research", title: "Vector DB comparison", preview: "pgvector vs. dedicated stores…", updatedSecondsAgo: 420_000 },
  { id: "cnv_e1", agent: "engineer", title: "Billing webhook idempotency", preview: "Proposed change with tests…", updatedSecondsAgo: 120, project: "Platform", pinned: true },
  { id: "cnv_e2", agent: "engineer", title: "Preview deploy failure", preview: "deploy.preview timed out…", updatedSecondsAgo: 7_200 },
  { id: "cnv_m1", agent: "marketing", title: "Launch post — LinkedIn", preview: "Draft v3 ready for approval", updatedSecondsAgo: 140, project: "Tutoring launch", pinned: true },
  { id: "cnv_m2", agent: "marketing", title: "November content calendar", preview: "12 posts across 3 channels", updatedSecondsAgo: 260_000 },
  { id: "cnv_b1", agent: "bi", title: "Q3 revenue cohorts", preview: "Retention improved for annual plans…", updatedSecondsAgo: 1_380, pinned: true },
  { id: "cnv_a1", agent: "assistant", title: "Plan next week", preview: "3 focus blocks proposed", updatedSecondsAgo: 3_900 },
  { id: "cnv_c1", agent: "creative", title: "Tutoring product names", preview: "Exploring with lateral thinking…", updatedSecondsAgo: 2, project: "Tutoring launch", pinned: true },
];

const RESEARCH_REPLY = `**Short answer:** demand for English tutoring in Central & Eastern Europe is growing, but the growth is concentrated in *exam prep* and *business English* — general conversation apps are saturated.

### Evidence summary

| Segment | Signal | Confidence |
|---|---|---|
| Exam prep (IELTS / Cambridge) | Rising search interest, 3 new local entrants in 2026 | High |
| Business English (B2B) | Corporate L&D budgets shifting to blended formats | Medium |
| Kids' conversation apps | Price competition, falling retention | Medium |

### What is verified vs. assumed
- ✅ **Verified** — competitor pricing pages and public course catalogues (18 sources).
- ⚠️ **Assumed** — market size figures come from two analyst summaries that disagree by ~30%; I've flagged both and not merged them.

> Next step: the BI agent is scoring these segments against your cost model. I'll hand the evidence pack over automatically.

Sources are attached in \`evidence-pack.md\`.`;

const ENGINEER_REPLY = `I found the root cause: Stripe retries the same \`event.id\` and we process it twice because the handler commits **before** recording the event.

### Proposed change

\`\`\`python
async def handle_event(event: StripeEvent, db: AsyncSession) -> None:
    # Idempotency: insert first, ignore duplicates atomically.
    inserted = await db.execute(
        insert(ProcessedWebhook)
        .values(provider="stripe", event_id=event.id)
        .on_conflict_do_nothing()
        .returning(ProcessedWebhook.id)
    )
    if inserted.scalar_one_or_none() is None:
        return  # already processed
    await apply_billing_change(event, db)
    await db.commit()
\`\`\`

### Tests
- \`test_duplicate_event_is_ignored\` — **passed** (executed in sandbox, 0.42s)
- \`test_out_of_order_events\` — **running…**

I have **not** deployed anything. A preview deploy needs your approval.`;

export const MESSAGES: Record<string, ChatMessage[]> = {
  cnv_r1: [
    { id: "m1", role: "user", content: "Research the English-learning market in Central & Eastern Europe. Where are the real opportunities?", createdSecondsAgo: 1_200, attachments: [{ name: "pricing-notes.pdf", kind: "pdf", sizeKb: 412 }] },
    { id: "m2", role: "assistant", content: RESEARCH_REPLY, createdSecondsAgo: 60, model: "gemini-2.5-pro · reasoning", executionId: "exe_01JD8K4V9R" },
  ],
  cnv_e1: [
    { id: "m1", role: "user", content: "Customers are being double-charged occasionally. Look at the billing webhooks and fix it — with tests.", createdSecondsAgo: 600 },
    { id: "m2", role: "assistant", content: ENGINEER_REPLY, createdSecondsAgo: 120, model: "gpt-5 · code", executionId: "exe_01JD8M2C1T" },
  ],
  cnv_m1: [
    { id: "m1", role: "user", content: "Write a LinkedIn post announcing the tutoring beta. Confident, warm, no hype.", createdSecondsAgo: 2_400 },
    {
      id: "m2",
      role: "assistant",
      content:
        "Here's **draft v3**, aligned with your brand voice (confident · warm · plain language):\n\n> Learning English shouldn't feel like homework. Today we're opening the beta of our tutoring programme — real tutors, short sessions, and progress you can actually see.\n>\n> We're starting small: 200 places, CEE first. If you've been waiting for a calmer way to get fluent, this is for you. 👉 Link in comments.\n\nPublishing is an **external action**, so I've requested approval before posting.",
      createdSecondsAgo: 140,
      model: "gpt-5-mini · text",
      executionId: "exe_01JD8H0Q8Z",
    },
  ],
};

export function genericMessages(conv: Conversation): ChatMessage[] {
  return [
    { id: "g1", role: "user", content: conv.title, createdSecondsAgo: conv.updatedSecondsAgo + 300 },
    { id: "g2", role: "assistant", content: `${conv.preview}\n\nThis conversation is part of the demo dataset — send a message to see a streamed reply.`, createdSecondsAgo: conv.updatedSecondsAgo },
  ];
}

export const REPLIES: Record<string, string> = {
  research:
    "I'll treat this as a research task.\n\n1. **Scope** — I'll confirm the question and the decision it supports.\n2. **Sources** — web, your knowledge base, and any attached files.\n3. **Evidence** — every claim gets a source; anything unverified is labelled *assumption*.\n\nI'll post the cited report here and save it to **Knowledge & Files**.",
  engineer:
    "Plan:\n\n```text\n1. Inspect the repository and failing paths\n2. Reproduce with a test\n3. Implement the smallest safe change\n4. Run the test suite in the sandbox\n5. Report results — no deploys without approval\n```\n\nStarting with step 1.",
  marketing:
    "Got it. I'll check your **brand memory** first so tone and terminology stay consistent, then propose 3 angles before writing the full copy. Nothing gets published or spent without your approval.",
  bi: "I'll start by checking which data sources are connected and validating their quality. Any figure I give you will be marked as **actual** or **estimate**, with the calculation shown.",
  assistant:
    "On it. If this needs a specialist I'll delegate the relevant part and keep you updated here. I won't send messages or book anything without asking first.",
  creative:
    "Let's open it up first, then narrow down. I'll start **divergent** — 20+ raw ideas without judging them — then cluster and score the strongest. Ideas will land on your **Idea board**.",
};

/* ── Tasks ──────────────────────────────────────────────────── */

const EXTRA_TASKS: TaskRunSummary[] = [
  { id: "tsk_5H2D", executionId: "exe_01JD8E5R2L", title: "Q3 revenue cohort report", agents: ["bi"], status: "completed", progress: 1, stage: "Delivered · 3 artifacts", stepsCompleted: 6, stepsTotal: 6, startedSecondsAgo: 3_260 },
  { id: "tsk_9F0A", executionId: "exe_01JD8A9X4F", title: "Deploy preview environment", agents: ["engineer"], status: "failed", progress: 3 / 6, stage: "Failed at step 4: deploy.preview timeout", stepsCompleted: 3, stepsTotal: 6, startedSecondsAgo: 7_500 },
];

export const TASKS: TaskRunSummary[] = [...DEMO_TASKS, ...EXTRA_TASKS];

const base = (id: string) => TASKS.find((t) => t.id === id)!;

export const TASK_DETAILS: Record<string, TaskDetail> = {
  tsk_7Q2M: {
    ...base("tsk_7Q2M"),
    objective: "Research the English-learning market, identify opportunities, create a business strategy and prepare a marketing campaign.",
    project: "Tutoring launch",
    createdBy: "Demo User",
    agentVersion: "orchestrator v0.9 · research v1.4.0 · bi v1.1.0 · creative v1.3.0 · marketing v1.2.1",
    plan: [
      { id: "p1", title: "Analyse request & constraints", agent: "orchestrator", status: "done", durationSec: 6 },
      { id: "p2", title: "Market sizing & evidence", agent: "research", status: "done", durationSec: 412 },
      { id: "p3", title: "Competitor teardown", agent: "research", status: "done", durationSec: 288 },
      { id: "p4", title: "Opportunity scoring", agent: "bi", status: "done", durationSec: 190 },
      { id: "p5", title: "Synthesize competitor evidence", agent: "bi", status: "done", durationSec: 120 },
      { id: "p6", title: "Generate positioning concepts (SCAMPER)", agent: "creative", status: "running", detail: "Exploring top 3 opportunities" },
      { id: "p7", title: "Business strategy draft", agent: "bi", status: "pending" },
      { id: "p8", title: "Campaign plan & budget simulation", agent: "marketing", status: "waiting", detail: "Awaiting approval: paid API" },
      { id: "p9", title: "Verify & synthesize final report", agent: "orchestrator", status: "pending" },
    ],
    events: DEMO_TIMELINE,
    toolCalls: [
      { id: "tc1", tool: "web.search", agent: "research", input: "\"English learning app market CEE 2026\"", status: "ok", durationMs: 1840, sideEffect: "none", atMs: 4_200 },
      { id: "tc2", tool: "web.fetch", agent: "research", input: "competitor pricing pages ×18", status: "ok", durationMs: 9620, sideEffect: "none", atMs: 5_100 },
      { id: "tc3", tool: "knowledge.retrieve", agent: "research", input: "pricing-notes.pdf · top_k=8", status: "ok", durationMs: 220, sideEffect: "none", atMs: 6_400 },
      { id: "tc4", tool: "gn7t.query", agent: "bi", input: "segment_revenue (read-only)", status: "ok", durationMs: 2410, sideEffect: "none", atMs: 13_800 },
      { id: "tc5", tool: "python.analyze", agent: "bi", input: "opportunity_matrix.py", status: "ok", durationMs: 3880, sideEffect: "none", atMs: 15_200 },
      { id: "tc6", tool: "ads.simulate", agent: "marketing", input: "budget scenarios ×3 (paid API)", status: "blocked", durationMs: null, sideEffect: "financial", atMs: 21_000 },
    ],
    logs: [
      { atMs: 0, level: "info", source: "orchestrator", message: "plan.created steps=9 agents=4 branches=2" },
      { atMs: 1_800, level: "info", source: "orchestrator", message: "subtask.spawned agent=research id=st_research" },
      { atMs: 4_200, level: "debug", source: "gateway", message: "route capability=reasoning → gemini:gemini-2.5-pro (primary)" },
      { atMs: 7_050, level: "warn", source: "research", message: "2 sources disagree on market size (Δ≈30%) — keeping both, flagged" },
      { atMs: 13_800, level: "info", source: "tools", message: "gn7t.query ok rows=1,284 ms=2410" },
      { atMs: 16_500, level: "info", source: "artifacts", message: "artifact.created opportunity-matrix.xlsx 48KB" },
      { atMs: 19_900, level: "debug", source: "gateway", message: "route capability=creative → gemini:gemini-2.5-flash" },
      { atMs: 21_000, level: "warn", source: "approvals", message: "approval.requested tool=ads.simulate side_effect=financial" },
    ],
    artifacts: [
      { id: "ar1", name: "evidence-pack.md", kind: "md", sizeKb: 86, agent: "research", createdSecondsAgo: 700 },
      { id: "ar2", name: "competitor-teardown.pdf", kind: "pdf", sizeKb: 1240, agent: "research", createdSecondsAgo: 520 },
      { id: "ar3", name: "opportunity-matrix.xlsx", kind: "xlsx", sizeKb: 48, agent: "bi", createdSecondsAgo: 300 },
    ],
    approvals: [
      { id: "apr_1", executionId: "exe_01JD8K4V9R", title: "Run paid ad-budget simulation", reason: "Uses a paid third-party API (≈ $4.20 estimated).", sideEffect: "financial", agent: "marketing", status: "pending", preview: "3 scenarios · €2k / €5k / €10k monthly budgets · Meta + LinkedIn", requestedSecondsAgo: 90 },
    ],
    subtasks: [
      { id: "st1", title: "Market sizing", agent: "research", status: "done", dependsOn: [], progress: 1 },
      { id: "st2", title: "Competitor teardown", agent: "research", status: "done", dependsOn: [], progress: 1 },
      { id: "st3", title: "Opportunity scoring", agent: "bi", status: "done", dependsOn: ["st1", "st2"], progress: 1 },
      { id: "st4", title: "Positioning concepts", agent: "creative", status: "running", dependsOn: ["st3"], progress: null },
      { id: "st5", title: "Business strategy", agent: "bi", status: "pending", dependsOn: ["st3", "st4"], progress: 0 },
      { id: "st6", title: "Campaign plan", agent: "marketing", status: "waiting", dependsOn: ["st4"], progress: 0.25 },
      { id: "st7", title: "Verify & synthesize", agent: "research", status: "pending", dependsOn: ["st5", "st6"], progress: 0 },
    ],
    controls: { pause: true, resume: false, cancel: true, retry: false },
  },
  tsk_3K9P: {
    ...base("tsk_3K9P"),
    objective: "Stop duplicate billing: make Stripe webhook handling idempotent and prove it with tests.",
    project: "Platform",
    createdBy: "Demo User",
    agentVersion: "engineer v2.0.3",
    plan: [
      { id: "p1", title: "Inspect repository & webhook handlers", agent: "engineer", status: "done", durationSec: 64 },
      { id: "p2", title: "Reproduce with failing test", agent: "engineer", status: "done", durationSec: 120 },
      { id: "p3", title: "Implement insert-first idempotency", agent: "engineer", status: "done", durationSec: 96 },
      { id: "p4", title: "Run test suite (pytest)", agent: "engineer", status: "running", detail: "142 / 318 tests" },
      { id: "p5", title: "Self-review diff", agent: "engineer", status: "pending" },
      { id: "p6", title: "Open pull request", agent: "engineer", status: "pending" },
      { id: "p7", title: "Report results", agent: "engineer", status: "pending" },
    ],
    events: [
      { seq: 1, kind: "plan", agent: "engineer", title: "Execution plan created", detail: "7 steps", atMs: 0 },
      { seq: 2, kind: "tool_call", agent: "engineer", title: "repo.read", detail: "api/billing/webhooks.py", atMs: 3_000 },
      { seq: 3, kind: "step_completed", agent: "engineer", title: "Root cause identified", detail: "commit before event recorded", atMs: 64_000 },
      { seq: 4, kind: "tool_call", agent: "engineer", title: "sandbox.exec", detail: "pytest -k duplicate", atMs: 150_000 },
      { seq: 5, kind: "artifact", agent: "engineer", title: "Artifact: webhooks.diff", atMs: 280_000 },
      { seq: 6, kind: "step_started", agent: "engineer", title: "Running full test suite", atMs: 300_000 },
    ],
    toolCalls: [
      { id: "tc1", tool: "repo.read", agent: "engineer", input: "api/billing/**", status: "ok", durationMs: 840, sideEffect: "none", atMs: 3_000 },
      { id: "tc2", tool: "sandbox.exec", agent: "engineer", input: "pytest -k duplicate (expect fail)", status: "ok", durationMs: 4200, sideEffect: "internal", atMs: 150_000 },
      { id: "tc3", tool: "repo.write", agent: "engineer", input: "branch agent/idempotent-webhooks", status: "ok", durationMs: 610, sideEffect: "internal", atMs: 270_000 },
      { id: "tc4", tool: "sandbox.exec", agent: "engineer", input: "pytest -q", status: "running", durationMs: null, sideEffect: "internal", atMs: 300_000 },
    ],
    logs: [
      { atMs: 0, level: "info", source: "engine", message: "execution.started agent=engineer@v2.0.3" },
      { atMs: 150_000, level: "info", source: "sandbox", message: "1 failed (expected): test_duplicate_event_is_ignored" },
      { atMs: 296_000, level: "info", source: "sandbox", message: "1 passed in 0.42s: test_duplicate_event_is_ignored" },
      { atMs: 300_000, level: "info", source: "sandbox", message: "collected 318 items" },
    ],
    artifacts: [{ id: "ar1", name: "webhooks.diff", kind: "code", sizeKb: 6, agent: "engineer", createdSecondsAgo: 200 }],
    approvals: [],
    subtasks: [],
    controls: { pause: true, resume: false, cancel: true, retry: false },
  },
  tsk_2B6R: {
    ...base("tsk_2B6R"),
    objective: "Announce the tutoring beta on LinkedIn in the brand voice.",
    project: "Tutoring launch",
    createdBy: "Demo User",
    agentVersion: "marketing v1.2.1",
    plan: [
      { id: "p1", title: "Load brand voice & guidelines", agent: "marketing", status: "done", durationSec: 3 },
      { id: "p2", title: "Draft 3 angles", agent: "marketing", status: "done", durationSec: 41 },
      { id: "p3", title: "Write final copy (v3)", agent: "marketing", status: "done", durationSec: 22 },
      { id: "p4", title: "Brand consistency review", agent: "marketing", status: "done", durationSec: 9 },
      { id: "p5", title: "Publish to LinkedIn", agent: "marketing", status: "waiting", detail: "Requires approval (external)" },
    ],
    events: [
      { seq: 1, kind: "plan", agent: "marketing", title: "Execution plan created", detail: "5 steps", atMs: 0 },
      { seq: 2, kind: "tool_call", agent: "marketing", title: "brand.memory", detail: "tone, banned phrases", atMs: 1_000 },
      { seq: 3, kind: "artifact", agent: "marketing", title: "Artifact: linkedin-post-v3.md", atMs: 64_000 },
      { seq: 4, kind: "approval", agent: "marketing", title: "Approval required", detail: "social.publish · external", atMs: 75_000 },
    ],
    toolCalls: [
      { id: "tc1", tool: "brand.memory", agent: "marketing", input: "voice profile", status: "ok", durationMs: 120, sideEffect: "none", atMs: 1_000 },
      { id: "tc2", tool: "social.publish", agent: "marketing", input: "LinkedIn · company page", status: "blocked", durationMs: null, sideEffect: "external", atMs: 75_000 },
    ],
    logs: [{ atMs: 75_000, level: "warn", source: "approvals", message: "approval.requested tool=social.publish side_effect=external" }],
    artifacts: [{ id: "ar1", name: "linkedin-post-v3.md", kind: "md", sizeKb: 2, agent: "marketing", createdSecondsAgo: 2_100 }],
    approvals: [
      { id: "apr_2", executionId: "exe_01JD8H0Q8Z", title: "Publish LinkedIn post", reason: "Posts publicly on the company page.", sideEffect: "external", agent: "marketing", status: "pending", preview: "Learning English shouldn't feel like homework. Today we're opening the beta…", requestedSecondsAgo: 140 },
    ],
    subtasks: [],
    controls: { pause: false, resume: false, cancel: true, retry: false },
  },
  tsk_8V1X: {
    ...base("tsk_8V1X"),
    objective: "Generate and rank name candidates for the tutoring product line.",
    project: "Tutoring launch",
    createdBy: "Demo User",
    agentVersion: "creative v1.3.0",
    plan: [{ id: "p1", title: "Choose thinking approach", agent: "creative", status: "running", detail: "Plan not finalised — progress unknown" }],
    events: [{ seq: 1, kind: "step_started", agent: "creative", title: "Planning", detail: "selecting approach", atMs: 0 }],
    toolCalls: [],
    logs: [{ atMs: 0, level: "info", source: "engine", message: "execution.started agent=creative@v1.3.0" }],
    artifacts: [],
    approvals: [],
    subtasks: [],
    controls: { pause: true, resume: false, cancel: true, retry: false },
  },
  tsk_5H2D: {
    ...base("tsk_5H2D"),
    objective: "Analyse Q3 revenue by signup cohort and explain retention changes.",
    createdBy: "Demo User",
    agentVersion: "bi v1.1.0",
    plan: [
      { id: "p1", title: "Validate data sources", agent: "bi", status: "done", durationSec: 40 },
      { id: "p2", title: "Build cohorts", agent: "bi", status: "done", durationSec: 380 },
      { id: "p3", title: "Retention analysis", agent: "bi", status: "done", durationSec: 520 },
      { id: "p4", title: "Charts", agent: "bi", status: "done", durationSec: 210 },
      { id: "p5", title: "Narrative & assumptions", agent: "bi", status: "done", durationSec: 600 },
      { id: "p6", title: "Deliver report", agent: "bi", status: "done", durationSec: 130 },
    ],
    events: [
      { seq: 1, kind: "plan", agent: "bi", title: "Execution plan created", detail: "6 steps", atMs: 0 },
      { seq: 2, kind: "tool_call", agent: "bi", title: "gn7t.query", detail: "revenue_by_cohort", atMs: 42_000 },
      { seq: 3, kind: "artifact", agent: "bi", title: "Artifact: q3-cohort-report.pdf", atMs: 1_750_000 },
      { seq: 4, kind: "completed", agent: "bi", title: "Execution completed", detail: "3 artifacts", atMs: 1_880_000 },
    ],
    toolCalls: [{ id: "tc1", tool: "gn7t.query", agent: "bi", input: "revenue_by_cohort Q3", status: "ok", durationMs: 3_100, sideEffect: "none", atMs: 42_000 }],
    logs: [{ atMs: 1_880_000, level: "info", source: "engine", message: "execution.completed artifacts=3" }],
    artifacts: [
      { id: "ar1", name: "q3-cohort-report.pdf", kind: "pdf", sizeKb: 2_480, agent: "bi", createdSecondsAgo: 1_380 },
      { id: "ar2", name: "cohorts.xlsx", kind: "xlsx", sizeKb: 210, agent: "bi", createdSecondsAgo: 1_390 },
      { id: "ar3", name: "assumptions.md", kind: "md", sizeKb: 4, agent: "bi", createdSecondsAgo: 1_390 },
    ],
    approvals: [],
    subtasks: [],
    controls: { pause: false, resume: false, cancel: false, retry: true },
  },
  tsk_9F0A: {
    ...base("tsk_9F0A"),
    objective: "Spin up a preview environment for the billing branch.",
    createdBy: "Demo User",
    agentVersion: "engineer v2.0.3",
    plan: [
      { id: "p1", title: "Build container", agent: "engineer", status: "done", durationSec: 140 },
      { id: "p2", title: "Run migrations on preview DB", agent: "engineer", status: "done", durationSec: 22 },
      { id: "p3", title: "Approval: preview deploy", agent: "engineer", status: "done", durationSec: 20 },
      { id: "p4", title: "deploy.preview", agent: "engineer", status: "failed", detail: "Timed out after 120s" },
      { id: "p5", title: "Smoke tests", agent: "engineer", status: "skipped" },
      { id: "p6", title: "Report", agent: "engineer", status: "skipped" },
    ],
    events: [
      { seq: 1, kind: "plan", agent: "engineer", title: "Execution plan created", detail: "6 steps", atMs: 0 },
      { seq: 2, kind: "approval", agent: "engineer", title: "Approved by Demo User", detail: "deploy.preview", atMs: 170_000 },
      { seq: 3, kind: "tool_call", agent: "engineer", title: "deploy.preview", detail: "timeout 120s", atMs: 182_000 },
    ],
    toolCalls: [{ id: "tc1", tool: "deploy.preview", agent: "engineer", input: "branch agent/idempotent-webhooks", status: "error", durationMs: 120_000, sideEffect: "external", atMs: 182_000 }],
    logs: [
      { atMs: 182_000, level: "info", source: "tools", message: "deploy.preview started" },
      { atMs: 302_000, level: "error", source: "tools", message: "deploy.preview TimeoutError after 120000ms (host unreachable)" },
      { atMs: 302_100, level: "info", source: "engine", message: "checkpoint saved at step 4 — retry resumes here" },
    ],
    artifacts: [],
    approvals: [],
    subtasks: [],
    controls: { pause: false, resume: false, cancel: false, retry: true },
  },
};

/* ── Ideas ──────────────────────────────────────────────────── */

const idea = (id: string, title: string, summary: string, approach: ThinkingApproach, scores: [number, number, number], column: Idea["column"], tags: string[], lens?: string): Idea => ({
  id, title, summary, approach, lens, tags, column, verified: false,
  scores: { impact: scores[0], feasibility: scores[1], novelty: scores[2] },
});

export const IDEAS: Idea[] = [
  idea("i1", "Fluent in 15", "Fifteen-minute daily sessions with the same tutor — habit over intensity.", "divergent", [8, 8, 5], "shortlisted", ["Product", "Positioning"]),
  idea("i2", "Exam Sprint", "Six-week IELTS/Cambridge sprint with a score-improvement guarantee.", "convergent", [9, 6, 6], "shortlisted", ["Exam prep", "Pricing"]),
  idea("i3", "Team Tongue", "B2B package: tutors join the client's real meetings as silent coaches.", "lateral", [8, 4, 9], "developing", ["B2B", "Wild card"]),
  idea("i4", "Accent-free isn't the goal", "Campaign reframing fluency as clarity, not native-like accent.", "six_hats", [6, 9, 6], "new", ["Marketing"], "Green hat"),
  idea("i5", "Swap the classroom for commutes", "Audio-first micro-lessons that sync with tutor feedback.", "scamper", [7, 6, 7], "new", ["Product"], "Substitute"),
  idea("i6", "Tutor marketplace", "Open the platform to independent tutors with revenue share.", "first_principles", [7, 3, 4], "parked", ["Business model"]),
  idea("i7", "What kills this in a year?", "Premortem: AI conversation apps undercut price — differentiate on human accountability.", "premortem", [8, 7, 5], "new", ["Risk"]),
  idea("i8", "Lingo Ledger", "Progress you can show: a verified skill record employers can check.", "analogical", [7, 5, 8], "new", ["Differentiator"]),
];


export function generatedIdeas(approach: ThinkingApproach, objective: string): Idea[] {
  const topic = objective.trim() || "your objective";
  const lenses: Record<ThinkingApproach, string[]> = {
    divergent: ["Wide net", "Wide net", "Wide net", "Wide net"],
    convergent: ["Cluster A", "Cluster B", "Cluster C", "Best of"],
    first_principles: ["Fundamental", "Constraint", "Cost driver", "Rebuild"],
    lateral: ["Random entry", "Provocation", "Reversal", "Escape"],
    scamper: ["Substitute", "Combine", "Adapt", "Eliminate"],
    six_hats: ["White hat", "Yellow hat", "Black hat", "Green hat"],
    analogical: ["From fitness", "From gaming", "From banking", "From music"],
    debate: ["For", "Against", "Rebuttal", "Synthesis"],
    premortem: ["Failure mode", "Failure mode", "Mitigation", "Early signal"],
  };
  const titles = [
    `Make "${topic}" a weekly ritual`,
    `Remove the hardest step in ${topic}`,
    `Borrow a loyalty loop for ${topic}`,
    `A partner-led version of ${topic}`,
  ];
  return lenses[approach].map((lens, i) =>
    idea(`gen-${approach}-${i}-${Date.now()}`, titles[i], `${lens} perspective. Speculative idea generated for discussion — not a verified fact.`, approach, [5 + ((i * 3) % 5), 4 + ((i * 2) % 6), 5 + ((i * 5) % 5)], "new", ["Generated"], lens),
  );
}

/* ── Members ────────────────────────────────────────────────── */

export const MEMBERS: Member[] = [
  { id: "u1", name: "Demo User", email: "demo@northwind.example", role: "owner", lastActiveSecondsAgo: 30, status: "active" },
  { id: "u2", name: "Maya Chen", email: "maya@northwind.example", role: "admin", lastActiveSecondsAgo: 3_600, status: "active" },
  { id: "u3", name: "Daniel Okafor", email: "daniel@northwind.example", role: "member", lastActiveSecondsAgo: 18_000, status: "active" },
  { id: "u4", name: "Sofia Rossi", email: "sofia@northwind.example", role: "member", lastActiveSecondsAgo: 90_000, status: "active" },
  { id: "u5", name: "Lucas Meyer", email: "lucas@northwind.example", role: "viewer", lastActiveSecondsAgo: 400_000, status: "active" },
  { id: "u6", name: "", email: "finance@northwind.example", role: "viewer", lastActiveSecondsAgo: 0, status: "invited" },
];
