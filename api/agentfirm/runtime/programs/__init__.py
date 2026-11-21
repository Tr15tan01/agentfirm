"""Implemented agent programs. Agents with a manifest but no program fail fast with a
clear "not implemented yet" error instead of pretending to run."""

from __future__ import annotations

from ..tools import business as _business  # noqa: F401 - registers the Phase 4b tools
from .assistant import AssistantProgram
from .base import AgentProgram
from .bi import BIProgram
from .creative import CreativeProgram
from .engineer import EngineerProgram
from .marketing import MarketingProgram
from .research import ResearchProgram

PROGRAMS: dict[str, AgentProgram] = {
    "assistant": AssistantProgram(),
    "bi": BIProgram(),
    "creative": CreativeProgram(),
    "engineer": EngineerProgram(),
    "marketing": MarketingProgram(),
    "research": ResearchProgram(),
}
