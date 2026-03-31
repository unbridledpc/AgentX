from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sol.core.memory import MemoryChunk
from sol.core.types import VerificationLevel


@dataclass(frozen=True)
class PlanStep:
    tool_name: str
    arguments: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class Plan:
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True)
class ToolResult:
    tool: str
    ok: bool
    skipped: bool
    output: Any
    error: str | None
    duration_ms: float
    reason: str


@dataclass(frozen=True)
class AgentResult:
    ok: bool
    plan: Plan
    text: str
    tool_results: tuple[ToolResult, ...]
    retrieved: tuple[MemoryChunk, ...]
    context: str
    sources: tuple[dict[str, str], ...] = tuple()
    verification_level: VerificationLevel = VerificationLevel.UNVERIFIED
    verification: dict[str, Any] | None = None
