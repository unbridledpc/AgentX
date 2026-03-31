from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureCategory(str, Enum):
    VALIDATION = "validation_error"
    POLICY = "policy_blocked"
    APPROVAL = "approval_required"
    EXECUTION = "tool_execution_error"
    TRANSIENT = "transient_error"
    BUDGET = "budget_exceeded"
    UNKNOWN = "unknown"


class RetryDecision(str, Enum):
    RETRY = "retry"
    RETRY_WITH_HINT = "retry_with_hint"
    STOP = "stop"


@dataclass(frozen=True)
class JobBudgets:
    max_steps: int = 10
    max_failures: int = 3
    max_runtime_s: int = 900


@dataclass(frozen=True)
class JobStepRecord:
    iteration: int
    started_at: float
    finished_at: float
    plan: dict[str, Any]
    tool_results: list[dict[str, Any]]
    summary: str
    ok: bool


@dataclass(frozen=True)
class JobFailureReflection:
    category: FailureCategory
    summary: str
    strategy: str
    retry_decision: RetryDecision
    confidence: float
    reusable: bool
    failure_signature: str
    tool_name: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class PendingApproval:
    fingerprint: str
    requested_at: float
    reason: str
    summary: str
    tool_names: tuple[str, ...]


@dataclass
class Job:
    job_id: str
    goal: str
    created_at: float
    updated_at: float
    status: JobStatus
    budgets: JobBudgets
    skill_id: str | None = None
    steps_taken: int = 0
    failures: int = 0
    summary: str = ""
    result_summary: str = ""
    last_error: str | None = None
    iterations: list[JobStepRecord] = field(default_factory=list)
    reflections: list[JobFailureReflection] = field(default_factory=list)
    approved_plan_fingerprints: list[str] = field(default_factory=list)
    pending_approval: PendingApproval | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cancellation_requested: bool = False

    @staticmethod
    def create(*, goal: str, budgets: JobBudgets, skill_id: str | None = None, metadata: dict[str, Any] | None = None) -> "Job":
        now = time.time()
        return Job(
            job_id=uuid.uuid4().hex,
            goal=goal.strip(),
            created_at=now,
            updated_at=now,
            status=JobStatus.PENDING,
            budgets=budgets,
            skill_id=skill_id,
            metadata=dict(metadata or {}),
        )
