from __future__ import annotations

from dataclasses import dataclass, field
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
class ToolError:
    code: str
    message: str
    details: Any = None


@dataclass(frozen=True)
class ToolResult:
    tool: str
    ok: bool
    skipped: bool
    output: Any
    error: str | None
    duration_ms: float
    reason: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error_info: ToolError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequestAssessment:
    mode: str
    intent: str
    requires_tools: bool
    target_paths: tuple[str, ...] = tuple()
    missing_arguments: tuple[str, ...] = tuple()
    confidence: float = 0.0
    evidence: tuple[str, ...] = tuple()
    repo_query: str | None = None
    should_ground_response: bool = False


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
