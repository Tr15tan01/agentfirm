# Agent specifications

| Document | Agent | Manifest | Evals |
|---|---|---|---|
| [00-agent-interface.md](00-agent-interface.md) | Shared Agent Interface — orchestrator ↔ agent protocol | `api/agentfirm/agents/contracts.py` | — |
| [orchestrator.md](orchestrator.md) | Orchestrator (plans and coordinates; not an agent) | `api/agentfirm/runtime/orchestrator.py` | 12 |
| [research.md](research.md) | Personal Research & Knowledge | `manifests/research.yaml` v1.5.2 | 15 |
| [marketing.md](marketing.md) | AI Marketing | `manifests/marketing.yaml` v1.3.2 | 15 |
| [engineer.md](engineer.md) | Personal AI Project Engineer | `manifests/engineer.yaml` v2.1.1 | 16 |
| [bi.md](bi.md) | Business Intelligence & Automation | `manifests/bi.yaml` v1.2.1 | 15 |
| [assistant.md](assistant.md) | Personal Assistant & General Task | `manifests/assistant.yaml` v1.1.1 | 16 |
| [creative.md](creative.md) | Creative & Brainstorming | `manifests/creative.yaml` v1.4.2 | 14 |

**How this fits together**

- Each spec mixes hand-written requirements, architecture, failure scenarios, acceptance criteria and
  open decisions with sections **generated from the manifest**: tools, intents, workflow diagrams,
  approvals, limits, quality gates and evals. Regenerate them with
  `python -m agentfirm.agents.docgen`. CI fails if they are stale.
- The manifests (`api/agentfirm/agents/manifests/*.yaml`) are the configuration the Agent Engine runs.
  They are checked by `agentfirm.agents.registry.validate`, which covers the safety invariants,
  collaboration reciprocity, the rules the brief mandates and eval coverage.
- The tool catalog (`api/agentfirm/agents/tools.yaml`) is the shared Tool Registry. Every tool declares
  its side-effect class, a default approval and the permission the requesting user needs.
- The JSON Schemas in [`schemas/`](schemas/) are generated from the Pydantic contracts
  (`python -m agentfirm.agents.schemas`).
- Manifests are published as immutable agent versions (with rollback):
  `python -m agentfirm.agents.publishing`. Changing a published version requires a version bump.
