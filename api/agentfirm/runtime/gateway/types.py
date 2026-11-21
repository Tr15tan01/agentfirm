"""Provider-neutral request/response types for the Model Gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(slots=True)
class ModelRequest:
    #: Stable label of the calling step, e.g. "creative.diverge" (logging, evals, simulator).
    task: str
    messages: list[Message]
    #: When set, the provider is asked for JSON matching this schema.
    json_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int = 2048
    #: Structured hints for the SIMULATED provider only — never sent to real providers.
    sim_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelResponse:
    text: str
    tokens_in: int
    tokens_out: int
    provider: str = ""
    model: str = ""
    fallback_index: int = 0
    simulated: bool = False
    cost_usd: Decimal = Decimal(0)


class ProviderError(Exception):
    def __init__(self, message: str, *, retriable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retriable = retriable
        self.status = status


class ModelUnavailable(Exception):
    """Every route candidate failed or was skipped."""
