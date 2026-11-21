"""Deterministic local model simulator.

Used when AGENTFIRM_GATEWAY_MODE=simulated (development, CI, evals without provider
keys). It is NOT a language model: agent programs register small builders that turn
the request's `sim_context` into schema-valid output so the whole engine — routing,
events, tools, checkpoints, approvals — can be exercised end to end. Every response is
marked `simulated=True` and surfaced as such in `model.called` events.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

from .types import ModelRequest, ModelResponse

Builder = Callable[[ModelRequest], Any]
_BUILDERS: dict[str, Builder] = {}
#: Test hook: providers forced to fail, e.g. {"gemini"} → simulate an outage for fallback tests.
FAILING_PROVIDERS: set[str] = set()

WORD = re.compile(r"[a-z0-9]+")


def register(task: str) -> Callable[[Builder], Builder]:
    def deco(fn: Builder) -> Builder:
        _BUILDERS[task] = fn
        return fn

    return deco


STOP = {"the", "and", "for", "our", "with", "this", "that", "what", "how", "from", "into", "next", "last", "about", "your", "you", "can", "please"}


def tokens(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if len(w) > 2}


def _minimal(schema: dict[str, Any]) -> Any:
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object":
        return {k: _minimal(v) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    if t == "array":
        return []
    return {"string": "simulated", "integer": 0, "number": 0, "boolean": False}.get(t, None)


@register("classify_intent")
def _classify(req: ModelRequest) -> dict[str, Any]:
    """Nearest-intent classifier over manifest examples (crude 5-letter stems,
    so "pay"/"payment" or "buy"/"buying" match). A stand-in for a real model, nothing more."""

    def stems(text: str) -> set[str]:
        return {w[:5] for w in tokens(text) if w not in STOP}

    q = stems(req.sim_context.get("objective", ""))
    best, best_score = None, 0.0
    for intent in req.sim_context.get("intents", []):
        pos = max((len(q & stems(e)) / (len(stems(e)) or 1) for e in intent["examples"]), default=0)
        neg = max((len(q & stems(e)) / (len(stems(e)) or 1) for e in intent.get("counter_examples", [])), default=0)
        score = pos - 0.5 * neg
        if score > best_score:
            best, best_score = intent["key"], score
    if best is None:
        best = req.sim_context["intents"][0]["key"]
    return {"intent": best, "confidence": round(min(0.99, 0.55 + best_score), 2), "rationale": "simulated nearest-example match"}


async def complete(req: ModelRequest, *, latency_ms: int = 0) -> ModelResponse:
    if latency_ms:
        await asyncio.sleep(latency_ms / 1000)
    builder = _BUILDERS.get(req.task) or _BUILDERS.get(req.task.split(".", 1)[-1])
    if builder is not None:
        out = builder(req)
    elif req.json_schema is not None:
        out = _minimal(req.json_schema)
    else:
        out = f"(simulated response for {req.task})"
    text = out if isinstance(out, str) else json.dumps(out)
    prompt_chars = sum(len(m.content) for m in req.messages)
    return ModelResponse(text=text, tokens_in=max(1, prompt_chars // 4), tokens_out=max(1, len(text) // 4), simulated=True)
