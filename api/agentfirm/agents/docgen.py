"""Render the manifest-derived sections of docs/agents/<agent>.md.

Spec documents mix hand-written narrative with generated blocks delimited by

    <!-- BEGIN GENERATED: tools -->
    …
    <!-- END GENERATED: tools -->

so tables and workflow diagrams can never drift from the manifests.

    python -m agentfirm.agents.docgen          # update docs in place
    python -m agentfirm.agents.docgen --check  # exit 1 if any generated block is stale
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

from .contracts import AgentManifest, ApprovalPolicy, Workflow
from .registry import Registry, registry

DOCS = Path(__file__).resolve().parents[3] / "docs" / "agents"
BLOCK = re.compile(r"(<!-- BEGIN GENERATED: (?P<name>[a-z_]+) -->\n)(?P<body>.*?)(<!-- END GENERATED: (?P=name) -->)", re.S)


def _esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _code(items: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in items) if items else "—"


def header(m: AgentManifest, reg: Registry) -> str:
    return (
        "| | |\n|---|---|\n"
        f"| **Agent key** | `{m.key}` |\n"
        f"| **Manifest version** | v{m.version} ({m.status}) |\n"
        f"| **Manifest** | `api/agentfirm/agents/manifests/{m.key}.yaml` |\n"
        f"| **Eval suite** | `api/agentfirm/agents/evals/{m.key}.yaml` ({len(reg.evals[m.key].cases)} cases) |\n"
        f"| **Invocation permissions** | {_code(m.permissions)} |\n"
        f"| **Changelog** | {'<br>'.join(_esc(x) for x in m.changelog)} |\n"
    )


def scope(m: AgentManifest, _: Registry) -> str:
    out = [f"**Mission.** {m.mission}\n", "**Responsibilities**\n"]
    out += [f"- {r}" for r in m.responsibilities]
    out += ["", "**In scope**\n", *[f"- {s}" for s in m.scope_in], "", "**Out of scope**\n", *[f"- {s}" for s in m.scope_out]]
    out += ["", "**Known limitations**\n", *[f"- {s}" for s in m.limitations], "", f"**Capabilities:** {_code(m.capabilities)}", ""]
    return "\n".join(out)


def intents(m: AgentManifest, _: Registry) -> str:
    rows = ["| Intent | Meaning | Workflow | Example requests | Not this agent | Min. confidence |", "|---|---|---|---|---|---|"]
    for i in m.intents:
        rows.append(
            f"| `{i.key}` | {_esc(i.description)} | `{i.workflow}` | {'<br>'.join('“' + _esc(x) + '”' for x in i.examples)} | "
            f"{'<br>'.join('“' + _esc(x) + '”' for x in i.counter_examples) or '—'} | {i.min_confidence:.2f} |"
        )
    return "\n".join(rows) + "\n"


def _node(i: int, s) -> str:  # type: ignore[no-untyped-def]
    label = s.title.replace('"', "'")
    if s.kind == "approval":
        return f'  s{i}{{{{"🛡 {label}"}}}}'
    if s.kind == "delegate":
        return f'  s{i}[["↗ {label}"]]'
    if s.kind == "tool":
        return f'  s{i}[/"{label}"/]'
    if s.kind in ("verify",):
        return f'  s{i}(["✓ {label}"])'
    return f'  s{i}["{label}"]'


def _mermaid(w: Workflow) -> str:
    lines = ["```mermaid", "flowchart LR"]
    lines += [_node(i, s) for i, s in enumerate(w.steps)]
    # Group consecutive steps that share a parallel_group.
    layers: list[list[int]] = []
    for i, s in enumerate(w.steps):
        if layers and s.parallel_group and w.steps[layers[-1][0]].parallel_group == s.parallel_group:
            layers[-1].append(i)
        else:
            layers.append([i])
    for a, b in itertools.pairwise(layers):
        for x in a:
            for y in b:
                lines.append(f"  s{x} --> s{y}")
    lines.append("```")
    return "\n".join(lines)


def workflows(m: AgentManifest, _: Registry) -> str:
    out: list[str] = []
    for w in m.workflows:
        total = m.plan_weight(w.key)
        out += [f"#### {w.title} (`{w.key}`)", "", w.description, "", _mermaid(w), ""]
        out += ["| # | Step | Kind | Model capability | Tools | Weight (share of progress) | On failure |", "|---|---|---|---|---|---|---|"]
        for n, s in enumerate(w.steps, 1):
            out.append(
                f"| {n} | {_esc(s.title)} (`{s.key}`) | {s.kind} | {s.capability or '—'} | {_code(list(s.tools))} | "
                f"{s.weight:g} ({s.weight / total:.0%}) | {s.on_failure} |"
            )
        out.append("")
    out.append("Legend: 🛡 approval gate · ↗ delegation to another agent · parallelogram = tool call · ✓ verification step.\n")
    return "\n".join(out)


def tools(m: AgentManifest, reg: Registry) -> str:
    rows = ["| Tool | Side effect | Effective approval | User permission | Max calls / run | Provider (status) |", "|---|---|---|---|---|---|"]
    for g in m.tools:
        t = reg.tools[g.tool]
        appr = reg.effective_approval(m.key, g.tool)
        mark = "**require approval**" if appr == ApprovalPolicy.REQUIRE else appr.value
        rows.append(
            f"| `{g.tool}` — {_esc(t.label)} | {t.side_effect.value} | {mark} | `{t.required_permission}` | {g.max_calls_per_run} | {_esc(t.provider)} ({t.status}) |"
        )
    notes = [f"- `{g.tool}`: {g.notes}" for g in m.tools if g.notes]
    return "\n".join(rows) + ("\n\n" + "\n".join(notes) if notes else "") + "\n"


def data(m: AgentManifest, _: Registry) -> str:
    k, mem = m.knowledge, m.memory
    return (
        f"- **Knowledge sources:** {_code(list(k.sources))} (scope: {k.scope})\n"
        f"- **Untrusted sources** (treated as data, never instructions): {_code(list(k.untrusted_sources))}\n"
        f"- **Citations required:** {'yes' if k.citations_required else 'no'} · **PII handling:** {k.pii}\n"
        f"- **Memory:** conversation {'✓' if mem.conversation else '✗'} · user preferences {'✓' if mem.user_preferences else '✗'} · "
        f"project {'✓' if mem.project else '✗'} · named memories {_code(mem.agent_memory)} · retention {mem.retention_days} days"
        f"{' · memory writes confirmed by the user' if mem.writes_require_confirmation else ''}\n"
    )


def models(m: AgentManifest, _: Registry) -> str:
    temps = ", ".join(f"{k} {v}" for k, v in m.models.temperature.items()) or "gateway defaults"
    prefs = "".join(f"\n  - {p}" for p in m.models.preferences)
    return (
        f"- **Capabilities requested from the Model Gateway:** {_code(list(m.models.capabilities))} (default `{m.models.default_capability}`)\n"
        f"- **Temperatures:** {temps} · **max output tokens:** {m.models.max_output_tokens}\n"
        f"- **Routing:** super-admins choose provider/model per capability (OpenAI, Gemini, GN7T) — the agent never names a model.\n"
        f"- **Routing hints:**{prefs or ' none'}\n"
    )


def io(m: AgentManifest, _: Registry) -> str:
    rows = ["**Task parameters** (`AgentTask.parameters`)\n", "| Name | Type | Required | Description |", "|---|---|---|---|"]
    for p in m.inputs:
        t = p.type + (f" ({' / '.join(p.enum)})" if p.enum else "")
        rows.append(f"| `{p.name}` | {t} | {'yes' if p.required else 'no'} | {_esc(p.description)} |")
    rows += ["", "**Deliverables** (artifacts referenced from `AgentResult.artifacts`)\n", "| Key | Title | Format | Contents |", "|---|---|---|---|"]
    for d in m.deliverables:
        rows.append(f"| `{d.key}` | {_esc(d.title)} | {d.format} | {_esc(d.description)} |")
    return "\n".join(rows) + "\n"


def approvals(m: AgentManifest, _: Registry) -> str:
    if not m.approvals:
        return "This agent has no tools that need approval. All of its tools are read-only or only change AgentFirm itself.\n"
    rows = ["| Rule | When | Tools | Who can approve | Preview | Timeout → |", "|---|---|---|---|---|---|"]
    for r in m.approvals:
        rows.append(
            f"| `{r.key}` | {_esc(r.description)} | {_code(list(r.tools))} | `{r.approver_permission}` | {'required' if r.preview_required else '—'} | {r.timeout_hours} h → {r.on_timeout} |"
        )
    return "\n".join(rows) + "\n"


def recovery(m: AgentManifest, _: Registry) -> str:
    rows = ["| Error | Strategy | Max attempts |", "|---|---|---|"]
    rows += [f"| `{r.error.value}` | {r.strategy} | {r.max_attempts} |" for r in m.recovery]
    return "\n".join(rows) + "\n"


def limits(m: AgentManifest, _: Registry) -> str:
    lim = m.limits
    rows = [
        "| Limit | Value |",
        "|---|---|",
        f"| Max steps | {lim.max_steps} |",
        f"| Max runtime | {lim.max_runtime_seconds // 60} min |",
        f"| Max credits per run | {lim.max_credits} |",
        f"| Max tool calls | {lim.max_tool_calls} |",
        f"| Parallel subtasks | {lim.max_parallel_subtasks} |",
        f"| Delegation depth | {lim.max_delegation_depth} |",
        "",
        "**Quality gates** (measured by the eval harness; a release is blocked if any gate fails)\n",
        "| Metric | Threshold | Meaning |",
        "|---|---|---|",
    ]
    rows += [f"| `{q.metric}` | {'≥' if q.direction == 'min' else '≤'} {q.threshold:g} | {_esc(q.description)} |" for q in m.quality]
    rows += ["", f"**Behavioural rules:** {_code(m.rules)}"]
    return "\n".join(rows) + "\n"


def collaboration(m: AgentManifest, reg: Registry) -> str:
    c = m.collaboration
    invoked_by = sorted(k for k, a in reg.agents.items() if m.key in a.collaboration.can_delegate_to)
    return (
        f"- **Can delegate to:** {_code(list(c.can_delegate_to))}\n"
        f"- **Accepts work from:** {_code(list(c.accepts_from))}\n"
        f"- **Agents that delegate to it today:** {_code(invoked_by)}\n"
        f"- **Shared capabilities used:** {_code([s.value for s in c.shared_capabilities])}\n"
        f"- **Shared capabilities provided:** {_code([s.value for s in c.provides])}\n"
    )


def evals(m: AgentManifest, reg: Registry) -> str:
    rows = ["| ID | Category | Scenario | Key expectations |", "|---|---|---|---|"]
    for case in reg.evals[m.key].cases:
        x = case.expect
        exp: list[str] = []
        if x.intent:
            exp.append(f"intent `{x.intent}`")
        if x.status:
            exp.append(f"status {x.status}")
        if x.error_code:
            exp.append(f"error `{x.error_code.value}`")
        if x.tools_called:
            exp.append("calls " + _code(list(x.tools_called)))
        if x.tools_not_called:
            exp.append("never calls " + _code(list(x.tools_not_called)))
        if x.approval_required_for:
            exp.append("approval for " + _code(list(x.approval_required_for)))
        if x.handoff_to:
            exp.append("hands off to " + _code(list(x.handoff_to)))
        if x.deliverables:
            exp.append("delivers " + _code(list(x.deliverables)))
        if x.claim_statuses_required:
            exp.append("claims labelled " + "/".join(x.claim_statuses_required))
        if x.max_credits:
            exp.append(f"≤ {x.max_credits} credits")
        if x.max_duration_seconds:
            exp.append(f"≤ {x.max_duration_seconds}s")
        exp += [_esc(r) for r in x.rubric]
        who = f" (as {case.requester_role})" if case.requester_role != "member" else ""
        setup = f" — setup: {_esc('; '.join(case.setup))}" if case.setup else ""
        rows.append(f"| {case.id} | {case.category} | “{_esc(case.objective)}”{who}{setup} | {'; '.join(exp)} |")
    return "\n".join(rows) + "\n"


RENDERERS = {
    "header": header,
    "scope": scope,
    "intents": intents,
    "workflows": workflows,
    "tools": tools,
    "data": data,
    "models": models,
    "io": io,
    "approvals": approvals,
    "recovery": recovery,
    "limits": limits,
    "collaboration": collaboration,
    "evals": evals,
}


def render_doc(text: str, m: AgentManifest, reg: Registry) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in RENDERERS:
            raise KeyError(f"unknown generated block {name}")
        return f"{match.group(1)}{RENDERERS[name](m, reg)}{match.group(4)}"

    return BLOCK.sub(sub, text)


def main() -> int:
    reg = registry()
    stale = []
    for key, m in reg.agents.items():
        path = DOCS / f"{key}.md"
        current = path.read_text()
        rendered = render_doc(current, m, reg)
        if rendered != current:
            stale.append(path.name)
            if "--check" not in sys.argv:
                path.write_text(rendered)
    if "--check" in sys.argv and stale:
        print("Stale generated sections:", ", ".join(stale))
        return 1
    print("Updated:" if stale else "Up to date.", ", ".join(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
