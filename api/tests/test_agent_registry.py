"""Agent specifications as executable checks (Phase 3.5).

The six manifests, the shared tool catalog and the eval suites must satisfy the
brief's invariants; the validator must catch violations; contracts must reject
dishonest results; versions must be immutable once published.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import asyncpg
import pytest
from pydantic import ValidationError

from agentfirm.agents import contracts as c
from agentfirm.agents.registry import CORE_AGENTS, Registry, load, registry, validate

DOCS = Path(__file__).resolve().parents[2] / "docs" / "agents"


# ── The real registry is valid ───────────────────────────────────────────────


def test_registry_is_valid():
    reg = load()
    assert validate(reg) == []
    assert set(reg.agents) == set(CORE_AGENTS)


def test_every_consequential_tool_is_approval_gated_for_every_agent():
    reg = registry()
    for key, m in reg.agents.items():
        for g in m.tools:
            spec = reg.tools[g.tool]
            if spec.side_effect in c.CONSEQUENTIAL:
                assert reg.effective_approval(key, g.tool) != c.ApprovalPolicy.AUTO, (key, g.tool)


def test_eval_suites_cover_all_categories():
    reg = registry()
    for key, suite in reg.evals.items():
        assert {case.category for case in suite.cases} == set(c.EVAL_CATEGORIES), key


# ── The validator catches violations (mutation tests) ───────────────────────


def _mutated(mutate) -> list[str]:
    base = load()
    agents = {k: v.model_dump() for k, v in base.agents.items()}
    mutate(agents)
    reg = Registry(tools=base.tools, agents={k: c.AgentManifest.model_validate(v) for k, v in agents.items()}, evals=base.evals)
    return validate(reg)


def test_detects_consequential_tool_without_approval_step():
    def m(a):
        wf = next(w for w in a["marketing"]["workflows"] if w["key"] == "publish")
        wf["steps"] = [s for s in wf["steps"] if s["kind"] != "approval"]

    errs = _mutated(m)
    assert any("before an approval step" in e for e in errs)


def test_detects_grant_loosening_approval():
    def m(a):
        g = next(g for g in a["engineer"]["tools"] if g["tool"] == "deploy.production")
        g["approval"] = "auto"

    assert any("loosens approval" in e for e in _mutated(m))


def test_detects_wrong_approver_for_financial_tool():
    def m(a):
        rule = next(r for r in a["marketing"]["approvals"] if r["key"] == "spend_money")
        rule["approver_permission"] = "approvals:decide"

    assert any("needs approver" in e for e in _mutated(m))


def test_detects_non_reciprocal_delegation():
    def m(a):
        a["bi"]["collaboration"]["accepts_from"] = ["user", "orchestrator"]

    assert any("does not accept work from" in e for e in _mutated(m))


def test_detects_missing_brief_rule():
    def m(a):
        a["research"]["rules"] = ["report_source_recency"]

    assert any("never_fabricate_citations" in e for e in _mutated(m))


def test_detects_ungranted_tool_in_workflow():
    def m(a):
        a["creative"]["workflows"][0]["steps"][0]["tools"] = ["email.send"]

    assert any("ungranted tool email.send" in e for e in _mutated(m))


# ── Contracts reject dishonest or inconsistent payloads ─────────────────────


def test_verified_claim_requires_citation():
    with pytest.raises(ValidationError):
        c.Claim(text="Market grew 12%", status="verified")
    assert c.Claim(text="Market may grow", status="speculative").status == "speculative"


def test_progress_cannot_exceed_total():
    with pytest.raises(ValidationError):
        c.Progress(execution_id="00000000-0000-0000-0000-000000000001", seq=1, at="2026-11-16T00:00:00Z", completed_weight=5, total_weight=4)


def test_failed_result_requires_error_and_needs_input_requires_questions():
    eid = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(ValidationError):
        c.AgentResult(execution_id=eid, status="failed", summary="x")
    with pytest.raises(ValidationError):
        c.AgentResult(execution_id=eid, status="needs_input", summary="x")


def test_tool_spec_rejects_auto_approved_external_tool():
    with pytest.raises(ValidationError):
        c.ToolSpec(key="x.send", label="x", description="x", side_effect="external", default_approval="auto", required_permission="agents:use", provider="x")


def test_event_union_parses_by_type():
    env = c.EventEnvelope.model_validate(
        {
            "event": {
                "type": "model.called",
                "execution_id": "00000000-0000-0000-0000-000000000001",
                "seq": 3,
                "at": "2026-11-16T10:00:00Z",
                "capability": "reasoning",
                "provider": "gn7t",
                "model": "gn7t-core",
                "fallback_index": 1,
                "tokens_in": 10,
                "tokens_out": 5,
            }
        }
    )
    assert isinstance(env.event, c.ModelCalled) and env.event.fallback_index == 1


def test_plan_weights_define_progress():
    m = registry().agents["research"]
    total = m.plan_weight("deep_research")
    done = sum(s.weight for s in m.workflow("deep_research").steps[:4])
    assert 0 < done / total < 1  # progress is a ratio of declared weights, never a guess


# ── JSON Schemas and docs stay in sync with the code ────────────────────────


def test_committed_json_schemas_are_current():
    from agentfirm.agents.schemas import OUT, render

    for name, content in render().items():
        assert (OUT / name).read_text() == content, f"Run: python -m agentfirm.agents.schemas ({name} is stale)"


@pytest.mark.parametrize("key", CORE_AGENTS)
def test_spec_document_matches_manifest(key):
    doc = (DOCS / f"{key}.md").read_text()
    m = registry().agents[key]
    assert f"v{m.version}" in doc, "spec must state the manifest version"
    for item in [*(g.tool for g in m.tools), *(i.key for i in m.intents), *(w.key for w in m.workflows), *(r.key for r in m.approvals)]:
        assert re.search(rf"`{re.escape(item)}`", doc), f"{key}.md does not mention `{item}`"
    for case in registry().evals[key].cases:
        assert case.id in doc, f"{key}.md does not list eval {case.id}"


def test_interface_spec_covers_every_event_type():
    doc = (DOCS / "00-agent-interface.md").read_text()
    for model in c.AgentEvent.__args__[0].__args__:  # type: ignore[attr-defined]
        assert f"`{model.model_fields['type'].default}`" in doc


# ── Versioning: publish, immutability, rollback ─────────────────────────────


async def test_publish_rollback_and_immutability(database, owner_db):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from agentfirm.agents.publishing import PublishError, publish, publish_all, rollback
    from agentfirm.core.config import get_settings

    engine = create_async_engine(get_settings().migrations_database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    seeded = {
        r["key"]: r["version"]
        for r in await owner_db.fetch("SELECT a.key, v.version FROM agent_versions v JOIN agents a ON a.id = v.agent_id WHERE v.is_current")
    }
    try:
        async with Session() as s, s.begin():
            results = await publish_all(s)
        assert {r.status for r in results} <= {"created", "unchanged"}  # other modules may have published some already

        async with Session() as s, s.begin():
            again = await publish_all(s)
        assert {r.status for r in again} == {"unchanged"}

        research = registry().agents["research"]
        tampered = research.model_copy(update={"mission": "Something else"})
        async with Session() as s, s.begin():
            with pytest.raises(PublishError, match="bump the version"):
                await publish(s, tampered)

        older = research.model_copy(update={"version": "1.0.0"})
        async with Session() as s, s.begin():
            with pytest.raises(PublishError, match="must be greater"):
                await publish(s, older)

        current = await owner_db.fetchval("SELECT v.version FROM agent_versions v JOIN agents a ON a.id = v.agent_id WHERE a.key = 'research' AND v.is_current")
        assert current == research.version

        async with Session() as s, s.begin():
            await rollback(s, "research", "1.4.0")
        rows = await owner_db.fetch("SELECT v.version, v.is_current FROM agent_versions v JOIN agents a ON a.id = v.agent_id WHERE a.key = 'research'")
        assert {r["version"]: r["is_current"] for r in rows} == {"1.4.0": True, research.version: False}

        # Published manifests cannot be rewritten or deleted — not even by the schema owner.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await owner_db.execute("UPDATE agent_versions SET manifest = '{}'::jsonb WHERE version = '1.4.0'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await owner_db.execute("DELETE FROM agent_versions WHERE version = '1.4.0'")
        # Only one current version per agent.
        with pytest.raises(asyncpg.UniqueViolationError):
            await owner_db.execute("UPDATE agent_versions SET is_current = true WHERE agent_id = (SELECT id FROM agents WHERE key='research')")

        audit = await owner_db.fetchval("SELECT count(*) FROM audit_logs WHERE action LIKE 'agent.version_%'")
        assert audit >= 7
    finally:
        # Restore the seeded current versions so other tests see the original state.
        async with Session() as s, s.begin():
            for key, version in seeded.items():
                await rollback(s, key, version)
        await engine.dispose()


def test_mutation_helper_does_not_touch_real_registry():
    before = copy.deepcopy(registry().agents["marketing"].model_dump())
    _mutated(lambda a: a["marketing"].update(rules=["x"]))
    assert registry().agents["marketing"].model_dump() == before


def test_generated_doc_sections_are_current():
    from agentfirm.agents.docgen import DOCS as DOC_DIR
    from agentfirm.agents.docgen import render_doc

    reg = registry()
    for key, m in reg.agents.items():
        text = (DOC_DIR / f"{key}.md").read_text()
        assert render_doc(text, m, reg) == text, f"Run: python -m agentfirm.agents.docgen ({key}.md is stale)"
