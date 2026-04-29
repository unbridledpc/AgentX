from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["task-reflection"])

ROOT = Path.cwd()
MEMORY_DIR = ROOT / "memory"
PROJECT_MEMORY_PATH = MEMORY_DIR / "project_memory_entries.jsonl"
REFLECTION_LEDGER_PATH = MEMORY_DIR / "task_reflections.jsonl"


def _now() -> float:
    return time.time()


def _clean(text: Any, limit: int = 1200) -> str:
    value = str(text or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:limit]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [_clean(p, 260) for p in parts if _clean(p, 260)]


def _uniq(items: list[str], limit: int = 10) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        value = _clean(item, 300)
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


class ReflectionMessage(BaseModel):
    role: str = "user"
    content: str = ""


class DraftReflectionRequest(BaseModel):
    task_title: str | None = None
    project_name: str | None = None
    thread_title: str | None = None
    messages: list[ReflectionMessage] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    git_status: str | None = None
    model: str | None = None


class TaskReflectionDraft(BaseModel):
    title: str
    summary: str
    changed: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    assumptions_corrected: list[str] = Field(default_factory=list)
    durable_memory: list[str] = Field(default_factory=list)
    discard_noise: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    confidence: float = 0.72


class PromoteReflectionRequest(BaseModel):
    title: str
    summary: str
    scope: Literal["global", "module", "file", "task"] = "task"
    kind: str = "task_note"
    durability: Literal["low", "medium", "high"] = "high"
    tags: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    assumptions_corrected: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.75
    source: str = "task_reflection_gate"


def _draft_from_request(req: DraftReflectionRequest) -> TaskReflectionDraft:
    title = _clean(req.task_title or req.thread_title or "Task reflection", 120)
    text = "\n".join(_clean(m.content, 1600) for m in req.messages[-16:] if m.content)
    sentences = _sentences(text)

    change_keywords = ("added", "built", "fixed", "changed", "updated", "implemented", "created", "removed", "patched", "wired", "restored")
    decision_keywords = ("decided", "decision", "should", "will", "going forward", "canonical", "instead", "use ", "keep ")
    assumption_keywords = ("assumed", "wrong", "actually", "turns out", "instead", "corrected", "not ")

    changed = [s for s in sentences if any(k in s.lower() for k in change_keywords)]
    decisions = [s for s in sentences if any(k in s.lower() for k in decision_keywords)]
    assumptions = [s for s in sentences if any(k in s.lower() for k in assumption_keywords)]

    files = list(req.changed_files)
    files += re.findall(r"(?:AgentXWeb|apps|AgentX|Server|scripts|tests)/[^\s`'\")]+", text)
    files = _uniq(files, 14)

    if not changed:
      changed = sentences[-4:]
    if not decisions:
      decisions = ["Reviewed the task outcome and captured durable project knowledge for future AgentX work."]

    project = _clean(req.project_name or "AgentX", 80)
    summary = _clean(
        f"{project}: {title}. " + (changed[0] if changed else "Task work was reviewed for reusable project knowledge."),
        520,
    )

    durable = _uniq([
        *decisions[:3],
        *changed[:3],
        "Promote only reusable architecture, workflow, project, or debugging knowledge; discard one-off chat noise.",
    ], 8)

    checklist = [
        "Build/tests checked where applicable",
        "Project memory reviewed",
        "README/CHANGELOG impact considered",
        "Git status reviewed before commit/push",
    ]
    if req.git_status:
        checklist.append("Git status captured from current task context")

    return TaskReflectionDraft(
        title=title,
        summary=summary,
        changed=_uniq(changed, 8),
        affected_files=files,
        decisions=_uniq(decisions, 8),
        assumptions_corrected=_uniq(assumptions, 6),
        durable_memory=durable,
        discard_noise=[
            "Transient troubleshooting commands",
            "Repeated console output unless it proves a durable failure mode",
            "One-off UI observations after the fix is captured",
        ],
        checklist=checklist,
    )


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


@router.post("/reflection/draft", response_model=TaskReflectionDraft)
def draft_reflection(req: DraftReflectionRequest) -> TaskReflectionDraft:
    return _draft_from_request(req)


@router.post("/reflection/promote")
def promote_reflection(req: PromoteReflectionRequest) -> dict[str, Any]:
    ts = _now()
    entry_id = f"pmem_{int(ts)}_{uuid.uuid4().hex[:12]}"
    tags = _uniq([*req.tags, "task-reflection", f"scope:{req.scope}", f"kind:{req.kind}"], 14)
    entry = {
        "entry_id": entry_id,
        "title": _clean(req.title, 180),
        "summary": _clean(req.summary, 2000),
        "scope": req.scope,
        "kind": req.kind,
        "durability": req.durability,
        "created_at": ts,
        "updated_at": ts,
        "module": None,
        "file_path": None,
        "task_id": None,
        "source": req.source,
        "tags": tags,
        "affected_files": _uniq(req.affected_files, 30),
        "decisions": _uniq(req.decisions, 20),
        "assumptions_corrected": _uniq(req.assumptions_corrected, 20),
        "evidence": _uniq(req.evidence, 20),
        "status": "active",
        "confidence": max(0.0, min(float(req.confidence), 1.0)),
        "meta": {"phase": "3", "workflow": "task_reflection_gate"},
    }
    _append_jsonl(PROJECT_MEMORY_PATH, entry)
    _append_jsonl(REFLECTION_LEDGER_PATH, {"promoted_at": ts, "entry": entry})
    return {"ok": True, "entry_id": entry_id, "entry": entry}
