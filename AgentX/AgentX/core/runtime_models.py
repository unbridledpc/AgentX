from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentx.core.memory import MemoryChunk
from agentx.core.types import VerificationLevel


@dataclass(frozen=True)
class PlanStep:
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


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
class ArtifactContext:
    source: str
    type: str
    language: str | None = None
    content: str | None = None
    path: str | None = None
    dirty: bool | None = None
    title: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class PendingAction:
    intent: str
    mode: str
    tool_name: str
    known_args: dict[str, Any] = field(default_factory=dict)
    missing_arguments: tuple[str, ...] = tuple()
    filled_arguments: tuple[str, ...] = tuple()
    clarification_prompt: str = ""
    hints: dict[str, Any] = field(default_factory=dict)
    created_at: float | None = None
    thread_id: str | None = None
    source_turn_text: str | None = None


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
    artifact_context: ArtifactContext | None = None


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
