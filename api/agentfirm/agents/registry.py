"""Agent registry: loads the tool catalog and agent manifests and enforces the
cross-cutting invariants that a single Pydantic model cannot see.

Every invariant here is a requirement from the brief or the architecture docs; the
`BRIEF_RULES` table maps each agent to the behavioural rules the brief demands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .contracts import (
    APPROVAL_STRICTNESS,
    CONSEQUENTIAL,
    AgentManifest,
    ApprovalPolicy,
    EvalSuite,
    SideEffect,
    ToolCatalog,
    ToolSpec,
)

ROOT = Path(__file__).parent
MANIFEST_DIR = ROOT / "manifests"
EVAL_DIR = ROOT / "evals"
CORE_AGENTS = ("research", "marketing", "engineer", "bi", "assistant", "creative")
PLATFORM_MAX_CREDITS_PER_RUN = 1000
PLATFORM_MAX_DELEGATION_DEPTH = 2

#: Behavioural rules the brief requires for each agent (§21.2-21.7).
BRIEF_RULES: dict[str, set[str]] = {
    "research": {"never_fabricate_citations", "distinguish_verified_from_assumptions"},
    "marketing": {"no_publish_or_spend_without_approval", "respect_brand_voice"},
    "engineer": {"never_claim_unexecuted_tests", "destructive_requires_approval"},
    "bi": {"distinguish_actuals_from_estimates", "show_assumptions"},
    "assistant": {"no_consequential_action_without_approval", "delegate_specialist_work"},
    "creative": {"label_speculation", "avoid_generic_repetition"},
}

#: Approver permission required per side-effect class (least privilege for risky actions).
APPROVER_FOR: dict[SideEffect, set[str]] = {
    SideEffect.EXTERNAL: {"approvals:decide", "agents:configure", "billing:manage"},
    SideEffect.FINANCIAL: {"billing:manage"},
    SideEffect.DESTRUCTIVE: {"agents:configure"},
}


@dataclass
class Registry:
    tools: dict[str, ToolSpec]
    agents: dict[str, AgentManifest]
    evals: dict[str, EvalSuite] = field(default_factory=dict)

    def effective_approval(self, agent: str, tool: str) -> ApprovalPolicy:
        spec = self.tools[tool]
        grant = next(g for g in self.agents[agent].tools if g.tool == tool)
        if grant.approval and APPROVAL_STRICTNESS[grant.approval] > APPROVAL_STRICTNESS[spec.default_approval]:
            return grant.approval
        return spec.default_approval


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load(include_evals: bool = True) -> Registry:
    catalog = ToolCatalog.model_validate(_load_yaml(ROOT / "tools.yaml"))
    agents = {p.stem: AgentManifest.model_validate(_load_yaml(p)) for p in sorted(MANIFEST_DIR.glob("*.yaml"))}
    evals = {p.stem: EvalSuite.model_validate(_load_yaml(p)) for p in sorted(EVAL_DIR.glob("*.yaml"))} if include_evals else {}
    return Registry(tools=catalog.by_key(), agents=agents, evals=evals)


def validate(reg: Registry) -> list[str]:
    """Return human-readable violations (empty list = valid)."""
    errors: list[str] = []
    e = errors.append

    if len(set(reg.tools)) != len(reg.tools):
        e("tool catalog: duplicate keys")

    for key, m in reg.agents.items():
        p = f"{key}:"
        if m.key != key:
            e(f"{p} file name must match manifest key ({m.key})")

        granted = {g.tool for g in m.tools}
        if len(granted) != len(m.tools):
            e(f"{p} a tool is granted twice")
        # Tools must exist; grants may only make approval stricter.
        for g in m.tools:
            spec = reg.tools.get(g.tool)
            if spec is None:
                e(f"{p} grants unknown tool {g.tool}")
                continue
            if g.approval and APPROVAL_STRICTNESS[g.approval] < APPROVAL_STRICTNESS[spec.default_approval]:
                e(f"{p} {g.tool} grant loosens approval ({g.approval} < {spec.default_approval})")

        # Workflows: tools granted, capabilities allowed, every workflow reachable from an intent.
        wf_keys = {w.key for w in m.workflows}
        if len(wf_keys) != len(m.workflows):
            e(f"{p} duplicate workflow keys")
        for w in m.workflows:
            for s in w.steps:
                for t in s.tools:
                    if t not in granted:
                        e(f"{p} workflow {w.key}.{s.key} uses ungranted tool {t}")
                if s.capability and s.capability not in m.models.capabilities:
                    e(f"{p} workflow {w.key}.{s.key} uses capability {s.capability} not in models.capabilities")
                if s.kind == "approval":
                    gated = [t for t in s.tools if t in reg.tools and reg.effective_approval(key, t) == ApprovalPolicy.REQUIRE]
                    if not gated:
                        e(f"{p} approval step {w.key}.{s.key} gates no approval-required tool")
                if s.kind == "delegate" and "agents.delegate" not in s.tools:
                    e(f"{p} delegate step {w.key}.{s.key} must use agents.delegate")
            # Consequential tools must be preceded by an approval step in the same workflow.
            seen_approval: set[str] = set()
            for s in w.steps:
                if s.kind == "approval":
                    seen_approval.update(s.tools)
                    continue
                for t in s.tools:
                    spec = reg.tools.get(t)
                    if spec and spec.side_effect in CONSEQUENTIAL and t not in seen_approval:
                        e(f"{p} workflow {w.key}.{s.key} calls {spec.side_effect} tool {t} before an approval step")
            # …and every tool an approval step gates must be executed by a LATER step (otherwise
            # the approval authorises nothing, which is how a "purchase" step silently no-ops).
            for n, s in enumerate(w.steps):
                if s.kind != "approval":
                    continue
                later = {t for x in w.steps[n + 1 :] if x.kind != "approval" for t in x.tools}
                for t in s.tools:
                    if reg.effective_approval(key, t) == ApprovalPolicy.REQUIRE and t not in later:
                        e(f"{p} approval step {w.key}.{s.key} gates {t} but no later step executes it")
        intents_wf = {i.workflow for i in m.intents}
        for i in m.intents:
            if i.workflow not in wf_keys:
                e(f"{p} intent {i.key} → unknown workflow {i.workflow}")
        for w in wf_keys - intents_wf:
            e(f"{p} workflow {w} is not reachable from any intent")

        # Approvals: every approval-required tool is covered by a rule with an adequate approver.
        covered: dict[str, str] = {}
        for rule in m.approvals:
            for t in rule.tools:
                if t not in granted:
                    e(f"{p} approval rule {rule.key} references ungranted tool {t}")
                    continue
                covered[t] = rule.approver_permission
                spec = reg.tools[t]
                allowed = APPROVER_FOR.get(spec.side_effect)
                if allowed and rule.approver_permission not in allowed:
                    e(f"{p} {t} ({spec.side_effect}) needs approver in {sorted(allowed)}, got {rule.approver_permission}")
        for g in m.tools:
            if g.tool in reg.tools and reg.effective_approval(key, g.tool) == ApprovalPolicy.REQUIRE and g.tool not in covered:
                e(f"{p} {g.tool} requires approval but no approval rule covers it")

        # Collaboration graph.
        if m.collaboration.can_delegate_to and "agents.delegate" not in granted:
            e(f"{p} delegates to agents but is not granted agents.delegate")
        for target in m.collaboration.can_delegate_to:
            if target == key:
                e(f"{p} cannot delegate to itself")
            elif target not in reg.agents:
                e(f"{p} delegates to unknown agent {target}")
            elif key not in reg.agents[target].collaboration.accepts_from:
                e(f"{p} delegates to {target}, but {target} does not accept work from {key}")
        for src in m.collaboration.accepts_from:
            if src not in ("user", "orchestrator") and src not in reg.agents:
                e(f"{p} accepts_from unknown agent {src}")

        # Limits & rules.
        if m.limits.max_credits > PLATFORM_MAX_CREDITS_PER_RUN:
            e(f"{p} max_credits above platform cap {PLATFORM_MAX_CREDITS_PER_RUN}")
        if m.limits.max_delegation_depth > PLATFORM_MAX_DELEGATION_DEPTH:
            e(f"{p} delegation depth above platform cap")
        missing_rules = BRIEF_RULES.get(key, set()) - set(m.rules)
        if missing_rules:
            e(f"{p} missing brief-mandated rules {sorted(missing_rules)}")
        if "web" in m.knowledge.sources and "web" not in m.knowledge.untrusted_sources:
            e(f"{p} web content must be declared untrusted")

    # Evaluation suites (brief §21.10).
    from .contracts import EVAL_CATEGORIES

    for key in reg.agents:
        suite = reg.evals.get(key)
        if suite is None:
            e(f"{key}: missing eval suite")
            continue
        cats = {c.category for c in suite.cases}
        for c in sorted(set(EVAL_CATEGORIES) - cats):
            e(f"{key}: eval suite missing category {c}")
        ids = [c.id for c in suite.cases]
        if len(ids) != len(set(ids)):
            e(f"{key}: duplicate eval ids")
        m = reg.agents[key]
        intents = {i.key for i in m.intents}
        deliverables = {d.key for d in m.deliverables}
        for c in suite.cases:
            if not c.id.startswith(f"{key}-"):
                e(f"{key}: eval id {c.id} must start with '{key}-'")
            x = c.expect
            if x.intent and x.intent not in intents:
                e(f"{key}: eval {c.id} expects unknown intent {x.intent}")
            for t in [*x.tools_called, *x.tools_not_called, *x.approval_required_for]:
                if t not in reg.tools:
                    e(f"{key}: eval {c.id} references unknown tool {t}")
            for d in x.deliverables:
                if d not in deliverables:
                    e(f"{key}: eval {c.id} expects unknown deliverable {d}")
            for a in x.handoff_to:
                if a not in m.collaboration.can_delegate_to:
                    e(f"{key}: eval {c.id} expects handoff to {a}, which is not allowed")
        # Every intent is exercised by at least one classification case.
        classified = {c.expect.intent for c in suite.cases if c.category == "classification"}
        for i in sorted(intents - classified):
            e(f"{key}: no classification eval for intent {i}")
        # Every approval-gated tool has a permission-enforcement case.
        gated = {g.tool for g in m.tools if reg.effective_approval(key, g.tool) == ApprovalPolicy.REQUIRE}
        tested = {t for c in suite.cases if c.category == "permission_enforcement" for t in c.expect.approval_required_for}
        for t in sorted(gated - tested):
            e(f"{key}: no permission_enforcement eval covers {t}")

    for key in CORE_AGENTS:
        if key not in reg.agents:
            e(f"missing core agent manifest: {key}")
    return errors


@lru_cache
def registry() -> Registry:
    reg = load()
    problems = validate(reg)
    if problems:
        raise ValueError("Agent registry invalid:\n- " + "\n- ".join(problems))
    return reg
