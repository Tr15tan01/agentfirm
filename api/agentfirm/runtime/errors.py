from __future__ import annotations

from agentfirm.agents.contracts import ErrorCode


class StepError(Exception):
    """A failure the engine maps to the manifest's recovery rules."""

    def __init__(self, code: ErrorCode, message: str, *, retriable: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.retriable = code, message, retriable


class ExecutionHalted(Exception):
    """Pause/cancel requested, or the worker lost its lease — stop without changing status."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
