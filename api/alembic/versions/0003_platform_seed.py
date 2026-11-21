"""Platform seed: the six agents (v1 manifests), model providers, model catalog and
default per-capability routes. All of it is editable later by super-admins.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NS = uuid.UUID("6f1d3c52-6a8e-4f0b-9a57-2b3c9d0e7a11")


def sid(name: str) -> uuid.UUID:
    """Deterministic ids so later migrations and fixtures can reference seed rows."""
    return uuid.uuid5(NS, name)


def tool(key: str, label: str, side_effect: str, approval: str = "auto") -> dict[str, str]:
    return {"key": key, "label": label, "side_effect": side_effect, "approval": approval}


AGENTS = [
    {
        "key": "research",
        "name": "Research & Knowledge",
        "version": "1.4.0",
        "description": "Structured research, document analysis and cited reports.",
        "manifest": {
            "mission": "Conduct structured research and turn documents and external sources into cited, verifiable knowledge.",
            "capabilities": ["web_research", "document_analysis", "semantic_search", "fact_verification", "source_comparison", "cited_reports"],
            "model_capabilities": ["reasoning", "summarize", "long_context", "embeddings"],
            "tools": [
                tool("web.search", "Web search", "none"),
                tool("web.fetch", "Fetch page", "none"),
                tool("knowledge.retrieve", "Knowledge retrieval", "none"),
                tool("docs.parse", "Document parser", "none"),
                tool("artifact.write", "Write report", "internal"),
            ],
            "limits": {"max_steps": 40, "max_runtime_seconds": 3600, "max_credits": 400},
            "rules": ["never_fabricate_citations", "label_assumptions"],
        },
    },
    {
        "key": "marketing",
        "name": "AI Marketing",
        "version": "1.2.1",
        "description": "Strategy, positioning, campaigns, SEO and on-brand content.",
        "manifest": {
            "mission": "Plan, create and evaluate on-brand marketing — never publishing or spending without authorization.",
            "capabilities": ["positioning", "audience_analysis", "campaign_briefs", "content_calendars", "seo", "copywriting"],
            "model_capabilities": ["text", "creative", "classify"],
            "tools": [
                tool("brand.memory", "Brand memory", "none"),
                tool("seo.keywords", "Keyword research", "none"),
                tool("social.publish", "Publish to social", "external", "require_approval"),
                tool("ads.budget", "Ad budget changes", "financial", "require_approval"),
            ],
            "limits": {"max_steps": 30, "max_runtime_seconds": 1800, "max_credits": 200},
        },
    },
    {
        "key": "engineer",
        "name": "Project Engineer",
        "version": "2.0.3",
        "description": "Architecture, code, reviews, tests and technical documentation.",
        "manifest": {
            "mission": "Design, build, debug and maintain software — traceable changes, tests actually executed.",
            "capabilities": ["architecture", "code_generation", "code_review", "debugging", "testing", "api_design", "documentation"],
            "model_capabilities": ["code", "reasoning", "long_context"],
            "tools": [
                tool("repo.read", "Repository read", "none"),
                tool("repo.write", "Commit to branch", "internal"),
                tool("sandbox.exec", "Sandboxed execution", "internal"),
                tool("deploy.preview", "Preview deploy", "external", "require_approval"),
                tool("deploy.production", "Production deploy", "destructive", "require_approval"),
            ],
            "limits": {"max_steps": 60, "max_runtime_seconds": 5400, "max_credits": 800},
            "rules": ["never_claim_unexecuted_tests"],
        },
    },
    {
        "key": "bi",
        "name": "Business Intelligence & Automation",
        "version": "1.1.0",
        "description": "KPIs, forecasting, opportunity analysis and approved automations.",
        "manifest": {
            "mission": "Explain business performance, surface opportunities and run approved automations.",
            "capabilities": ["kpi_monitoring", "cohort_analysis", "forecasting", "opportunity_scoring", "automation"],
            "model_capabilities": ["reasoning", "code", "summarize"],
            "tools": [
                tool("gn7t.query", "GN7T data query", "none"),
                tool("python.analyze", "Data analysis sandbox", "none"),
                tool("schedule.report", "Scheduled reports", "internal"),
                tool("automation.run", "Run automation", "external", "require_approval"),
            ],
            "limits": {"max_steps": 40, "max_runtime_seconds": 3600, "max_credits": 500},
            "rules": ["distinguish_actuals_from_estimates"],
        },
    },
    {
        "key": "assistant",
        "name": "Personal Assistant",
        "version": "1.0.6",
        "description": "Scheduling, drafting, discovery — and delegating to specialists.",
        "manifest": {
            "mission": "Handle everyday requests and coordinate specialists when a task needs one.",
            "capabilities": ["scheduling", "email_drafting", "service_discovery", "job_search", "delegation"],
            "model_capabilities": ["text", "classify", "summarize"],
            "tools": [
                tool("calendar.read", "Calendar read", "none"),
                tool("calendar.write", "Create events", "external", "require_approval"),
                tool("email.draft", "Draft email", "internal"),
                tool("email.send", "Send email", "external", "require_approval"),
                tool("agents.delegate", "Delegate to agent", "internal"),
            ],
            "limits": {"max_steps": 20, "max_runtime_seconds": 900, "max_credits": 100},
        },
    },
    {
        "key": "creative",
        "name": "Creative & Brainstorming",
        "version": "1.3.0",
        "description": "Divergent ideation, SCAMPER, Six Hats and critical evaluation.",
        "manifest": {
            "mission": "Help you think: generate, challenge and evaluate ideas, then hand the best ones to other agents.",
            "capabilities": ["idea_generation", "naming", "product_innovation", "scenario_planning", "critical_evaluation"],
            "model_capabilities": ["creative", "reasoning"],
            "tools": [
                tool("ideas.board", "Idea board", "internal"),
                tool("brainstorm.engine", "Brainstorming engine", "none"),
                tool("agents.handoff", "Send idea to agent", "internal"),
            ],
            "limits": {"max_steps": 20, "max_runtime_seconds": 900, "max_credits": 120},
            "rules": ["label_speculation"],
        },
    },
]

PROVIDERS = [
    {"key": "openai", "name": "OpenAI", "kind": "External API", "base_url": "https://api.openai.com/v1"},
    {"key": "gemini", "name": "Google Gemini", "kind": "External API", "base_url": "https://generativelanguage.googleapis.com"},
    {"key": "gn7t", "name": "GN7T", "kind": "In-house service", "base_url": None},
    {"key": "tea800", "name": "Tea-800", "kind": "Self-hosted GPU inference", "base_url": None},
]

# Catalog entries are placeholders until super-admins confirm names and prices.
MODELS = [
    ("openai", "gpt-5", "GPT-5", ["reasoning", "text", "code", "long_context", "vision"], 1.25, 10),
    ("openai", "gpt-5-mini", "GPT-5 mini", ["text", "summarize", "classify", "code", "creative"], 0.25, 2),
    ("openai", "text-embedding-3-large", "text-embedding-3-large", ["embeddings"], 0.13, None),
    ("gemini", "gemini-2.5-pro", "Gemini 2.5 Pro", ["reasoning", "text", "code", "long_context", "vision"], 1.25, 10),
    ("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", ["text", "summarize", "classify", "creative", "vision"], 0.30, 2.5),
    ("gemini", "gemini-embedding", "Gemini Embedding", ["embeddings"], 0.15, None),
    ("gn7t", "gn7t-core", "GN7T Core", ["text", "summarize", "classify", "reasoning"], None, None),
    ("gn7t", "gn7t-embed", "GN7T Embed", ["embeddings"], None, None),
    ("tea800", "tea-800", "Tea-800", ["text", "creative", "summarize"], None, None),
]

ROUTES = {
    "reasoning": ["gemini/gemini-2.5-pro", "openai/gpt-5"],
    "text": ["openai/gpt-5-mini", "gemini/gemini-2.5-flash", "gn7t/gn7t-core"],
    "code": ["openai/gpt-5", "gemini/gemini-2.5-pro"],
    "summarize": ["gn7t/gn7t-core", "gemini/gemini-2.5-flash"],
    "classify": ["gn7t/gn7t-core", "openai/gpt-5-mini"],
    "creative": ["gemini/gemini-2.5-flash", "openai/gpt-5-mini"],
    "vision": ["gemini/gemini-2.5-pro", "openai/gpt-5"],
    "long_context": ["gemini/gemini-2.5-pro"],
    "embeddings": ["openai/text-embedding-3-large", "gn7t/gn7t-embed"],
}
TEMPERATURE = {"reasoning": 0.2, "text": 0.6, "code": 0.1, "summarize": 0.3, "classify": 0.0, "creative": 0.95, "vision": 0.2, "long_context": 0.2}


def upgrade() -> None:
    agents = sa.table("agents", sa.column("id", sa.Uuid), sa.column("key"), sa.column("name"), sa.column("description"))
    op.bulk_insert(agents, [{"id": sid(f"agent:{a['key']}"), "key": a["key"], "name": a["name"], "description": a["description"]} for a in AGENTS])
    for a in AGENTS:
        op.execute(
            sa.text(
                "INSERT INTO agent_versions (id, agent_id, version, manifest, published_at, is_current) "
                "VALUES (:id, :agent, :v, CAST(:m AS jsonb), now(), true)"
            ).bindparams(id=sid(f"agentver:{a['key']}:{a['version']}"), agent=sid(f"agent:{a['key']}"), v=a["version"], m=json.dumps(a["manifest"]))
        )

    providers = sa.table(
        "model_providers",
        sa.column("id", sa.Uuid),
        sa.column("key"),
        sa.column("name"),
        sa.column("kind"),
        sa.column("base_url"),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(providers, [{"id": sid(f"provider:{p['key']}"), **p, "enabled": p["key"] != "tea800"} for p in PROVIDERS])

    for prov, name, label, caps, pin, pout in MODELS:
        op.execute(
            sa.text(
                "INSERT INTO models (id, provider_id, name, label, capabilities, price_in_per_1m, price_out_per_1m) VALUES (:id, :p, :n, :l, :c, :pi, :po)"
            ).bindparams(id=sid(f"model:{prov}/{name}"), p=sid(f"provider:{prov}"), n=name, l=label, c=caps, pi=pin, po=pout)
        )

    for cap, chain in ROUTES.items():
        for priority, ref in enumerate(chain):
            op.execute(
                sa.text(
                    "INSERT INTO model_routes (id, scope, scope_id, capability, priority, model_id, params) "
                    "VALUES (:id, 'platform', NULL, :cap, :prio, :m, CAST(:params AS jsonb))"
                ).bindparams(
                    id=sid(f"route:platform:{cap}:{priority}"),
                    cap=cap,
                    prio=priority,
                    m=sid(f"model:{ref}"),
                    params=json.dumps({"temperature": TEMPERATURE.get(cap)} if cap in TEMPERATURE else {}),
                )
            )


def downgrade() -> None:
    for t in ("model_routes", "models", "model_providers", "agent_versions", "agents"):
        op.execute(f"DELETE FROM {t}")
