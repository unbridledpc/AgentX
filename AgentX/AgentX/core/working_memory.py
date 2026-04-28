from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from agentx.core.runtime_models import PendingAction


@dataclass
class WorkingMemoryState:
    scope_id: str
    user_id: str | None
    thread_id: str | None = None
    job_id: str | None = None
    goal: str = ""
    current_subgoal: str = ""
    active_plan: list[dict[str, Any]] = field(default_factory=list)
    recent_tool_outputs: list[dict[str, Any]] = field(default_factory=list)
    focus_resources: list[str] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    memories_used: list[dict[str, Any]] = field(default_factory=list)
    evidence_notes: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    summary: str = ""
    pending_action: PendingAction | None = None
    last_updated: float = field(default_factory=time.time)

    def begin(self, *, goal: str, constraints: list[str] | None = None) -> None:
        self.goal = (goal or "").strip()
        self.current_subgoal = ""
        self.summary = ""
        self.active_plan = []
        self.recent_tool_outputs = []
        self.focus_resources = []
        self.attempts = []
        self.failures = []
        self.decisions = []
        self.memories_used = []
        self.evidence_notes = []
        self.unresolved_items = []
        self.constraints = [str(x).strip() for x in (constraints or []) if str(x).strip()]
        self.last_updated = time.time()

    def set_subgoal(self, text: str) -> None:
        self.current_subgoal = (text or "").strip()
        self.last_updated = time.time()

    def set_plan(self, steps: list[dict[str, Any]]) -> None:
        self.active_plan = [dict(step) for step in steps]
        self.last_updated = time.time()

    def append_result(self, *, tool: str, ok: bool, summary: str, output: Any = None, error: str | None = None) -> None:
        item = {
            "tool": str(tool or "").strip(),
            "ok": bool(ok),
            "summary": str(summary or "").strip(),
            "error": str(error).strip() if error is not None else None,
        }
        if output is not None:
            item["output"] = output
        self.recent_tool_outputs.append(item)
        self.recent_tool_outputs = self.recent_tool_outputs[-5:]
        self.last_updated = time.time()

    def add_focus_resources(self, resources: list[str]) -> None:
        for resource in resources:
            text = (resource or "").strip()
            if not text:
                continue
            if text not in self.focus_resources:
                self.focus_resources.append(text)
        self.focus_resources = self.focus_resources[-12:]
        self.last_updated = time.time()

    def record_attempt(self, *, signature: str, tool: str, reason: str, status: str, category: str | None = None) -> None:
        item = {
            "signature": str(signature or "").strip(),
            "tool": str(tool or "").strip(),
            "reason": str(reason or "").strip(),
            "status": str(status or "").strip(),
            "category": str(category or "").strip() or None,
            "ts": time.time(),
        }
        self.attempts.append(item)
        self.attempts = self.attempts[-16:]
        if item["status"] == "failure":
            self.failures.append(dict(item))
            self.failures = self.failures[-12:]
        self.last_updated = time.time()

    def record_decision(self, *, action: str, reason: str, evidence: list[str] | None = None) -> None:
        self.decisions.append(
            {
                "action": str(action or "").strip(),
                "reason": str(reason or "").strip(),
                "evidence": [str(x).strip() for x in (evidence or []) if str(x).strip()],
                "ts": time.time(),
            }
        )
        self.decisions = self.decisions[-12:]
        self.last_updated = time.time()

    def record_memories_used(self, memories: list[dict[str, Any]]) -> None:
        self.memories_used = [dict(item) for item in memories][-8:]
        self.last_updated = time.time()

    def add_evidence_notes(self, notes: list[str]) -> None:
        for note in notes:
            text = (note or "").strip()
            if not text:
                continue
            if text not in self.evidence_notes:
                self.evidence_notes.append(text)
        self.evidence_notes = self.evidence_notes[-10:]
        self.last_updated = time.time()

    def set_summary(self, summary: str) -> None:
        self.summary = (summary or "").strip()
        self.last_updated = time.time()

    def set_pending_action(self, pending: PendingAction | None) -> None:
        self.pending_action = pending
        self.last_updated = time.time()

    def clear_pending_action(self) -> None:
        self.pending_action = None
        self.last_updated = time.time()

    def note_unresolved(self, item: str) -> None:
        text = (item or "").strip()
        if not text:
            return
        if text not in self.unresolved_items:
            self.unresolved_items.append(text)
        self.unresolved_items = self.unresolved_items[-8:]
        self.last_updated = time.time()

    def clear_unresolved(self) -> None:
        self.unresolved_items = []
        self.last_updated = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "job_id": self.job_id,
            "goal": self.goal,
            "current_subgoal": self.current_subgoal,
            "active_plan": [dict(step) for step in self.active_plan],
            "recent_tool_outputs": [dict(item) for item in self.recent_tool_outputs],
            "focus_resources": list(self.focus_resources),
            "attempts": [dict(item) for item in self.attempts],
            "failures": [dict(item) for item in self.failures],
            "decisions": [dict(item) for item in self.decisions],
            "memories_used": [dict(item) for item in self.memories_used],
            "evidence_notes": list(self.evidence_notes),
            "unresolved_items": list(self.unresolved_items),
            "constraints": list(self.constraints),
            "summary": self.summary,
            "pending_action": (asdict(self.pending_action) if self.pending_action is not None else None),
            "last_updated": float(self.last_updated),
        }


class WorkingMemoryManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, WorkingMemoryState] = {}

    @staticmethod
    def _scope_id(*, user_id: str | None, thread_id: str | None, job_id: str | None) -> str:
        if job_id:
            return f"job:{(user_id or '').strip().lower()}:{job_id.strip()}"
        if thread_id:
            return f"thread:{(user_id or '').strip().lower()}:{thread_id.strip()}"
        return f"session:{(user_id or '').strip().lower() or 'local'}"

    def for_scope(self, *, user_id: str | None, thread_id: str | None = None, job_id: str | None = None) -> WorkingMemoryState:
        scope_id = self._scope_id(user_id=user_id, thread_id=thread_id, job_id=job_id)
        with self._lock:
            state = self._states.get(scope_id)
            if state is None:
                state = WorkingMemoryState(scope_id=scope_id, user_id=(user_id or "").strip().lower() or None, thread_id=thread_id, job_id=job_id)
                self._states[scope_id] = state
            return state
