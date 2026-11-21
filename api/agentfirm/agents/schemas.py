"""Export JSON Schemas for the agent contracts to docs/agents/schemas/.

python -m agentfirm.agents.schemas          # write
python -m agentfirm.agents.schemas --check  # exit 1 if committed copies are stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .contracts import AgentManifest, AgentResult, AgentTask, EvalSuite, EventEnvelope, ToolCatalog

OUT = Path(__file__).resolve().parents[3] / "docs" / "agents" / "schemas"
MODELS = {
    "agent-manifest": AgentManifest,
    "tool-catalog": ToolCatalog,
    "agent-task": AgentTask,
    "agent-result": AgentResult,
    "agent-event": EventEnvelope,
    "eval-suite": EvalSuite,
}


def render() -> dict[str, str]:
    out = {}
    for name, model in MODELS.items():
        schema = model.model_json_schema(mode="serialization")
        schema["$id"] = f"https://agentfirm.app/schemas/{name}.json"
        out[f"{name}.schema.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return out


def main() -> int:
    files = render()
    if "--check" in sys.argv:
        stale = [n for n, c in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != c]
        if stale:
            print("Stale schemas:", ", ".join(stale))
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, c in files.items():
        (OUT / n).write_text(c)
    print(f"Wrote {len(files)} schemas to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
