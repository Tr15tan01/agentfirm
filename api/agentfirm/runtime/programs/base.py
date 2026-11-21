"""Agent program interface.

A program is the agent-specific half of an agent (the manifest is the other half): one
async handler per workflow step, plus `finalize()` that turns the final graph state into
an `AgentResult`. Approval steps are handled generically by the engine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from agentfirm.agents.contracts import AgentResult

if TYPE_CHECKING:
    from ..context import ExecutionContext

State = dict[str, Any]
Handler = Callable[["ExecutionContext", State], Awaitable[dict[str, Any]]]


class AgentProgram(Protocol):
    key: str
    handlers: dict[str, dict[str, Handler]]

    def finalize(self, ctx: ExecutionContext, data: State) -> AgentResult: ...

    def approval_preview(self, ctx: ExecutionContext, step: str, data: State) -> str | None: ...

    # Optional: `approval_scope(ctx, step, data) -> list[str] | None` narrows which gated
    # tools an approval step covers (the action actually prepared). None = all gated tools.


def missing_handlers(program: AgentProgram, manifest) -> list[str]:  # type: ignore[no-untyped-def]
    """Every non-approval step of every workflow must have a handler (checked in tests)."""
    out = []
    for w in manifest.workflows:
        for s in w.steps:
            if s.kind != "approval" and s.key not in program.handlers.get(w.key, {}):
                out.append(f"{manifest.key}.{w.key}.{s.key}")
    return out


# ── Shared helpers for programs ──────────────────────────────────────────────

import re as _re  # noqa: E402

NUMBER = _re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|k\b|m\b|bn\b|x\b)?", _re.I)


def approval_state(data: State, step: str = "approval") -> str:
    """approved | rejected | not_requested | absent (the approval step hasn't run)."""
    return str(data.get(f"approval:{step}", "absent"))


def wants(text: str, *patterns: str) -> bool:
    """True if the user's request explicitly asks for one of these actions (word-boundary regexes)."""
    return any(_re.search(p, text, _re.I) for p in patterns)


def art_ref(out: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
    name = out["name"]
    return {"id": out["artifact_id"], "name": name, "kind": kind or name.rsplit(".", 1)[-1]}


def fixture_flags(data: State) -> list[str]:
    """Steps whose tool outputs came from the fixture world (never real systems)."""
    return sorted(k.split(":", 1)[1] for k, v in data.items() if k.startswith("fixture:") and v)


def fixture_note(data: State) -> str:
    steps = fixture_flags(data)
    return f"\n\n> **Fixture data.** Steps {', '.join(steps)} used the fixture world, not your real systems." if steps else ""


def slug(text: str, n: int = 40) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "change"


def word_count(text: str) -> int | None:
    m = _re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\b", text, _re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"].index(w) + 1
