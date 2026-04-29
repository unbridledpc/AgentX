from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agentx_api.agentx_bridge import AgentXUnavailable, get_handle

router = APIRouter(tags=["project-memory"])


class ProjectMemoryEntryOut(BaseModel):
    entry_id: str
    title: str
    summary: str
    scope: str
    kind: str
    durability: str
    created_at: float
    updated_at: float
    module: str | None = None
    file_path: str | None = None
    task_id: str | None = None
    source: str = "manual"
    tags: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    assumptions_corrected: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    status: str = "active"
    confidence: float = 0.75
    meta: dict[str, Any] = Field(default_factory=dict)


class ProjectMemoryHitOut(BaseModel):
    entry: ProjectMemoryEntryOut
    content: str
    score: float | None = None
    snippet: str = ""


class ProjectMemoryStatsOut(BaseModel):
    ok: bool = True
    enabled: bool = True
    entry_count: int = 0
    ledger_path: str | None = None
    by_scope: dict[str, int] = Field(default_factory=dict)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)


class ProjectMemoryListOut(BaseModel):
    ok: bool = True
    entries: list[ProjectMemoryEntryOut]
    stats: ProjectMemoryStatsOut


class ProjectMemorySearchOut(BaseModel):
    ok: bool = True
    hits: list[ProjectMemoryHitOut]


class ProjectMemoryCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    summary: str = Field(..., min_length=1)
    scope: str = "global"
    kind: str = "task_note"
    durability: str = "medium"
    module: str | None = None
    file_path: str | None = None
    task_id: str | None = None
    source: str = "manual"
    tags: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    assumptions_corrected: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.75
    meta: dict[str, Any] = Field(default_factory=dict)


class ProjectMemoryStatusIn(BaseModel):
    status: str = Field(..., pattern="^(active|superseded|discarded)$")
    reason: str = ""


class ProjectContextIn(BaseModel):
    task: str = Field(..., min_length=1)
    module: str | None = None
    files: list[str] = Field(default_factory=list)
    k: int = 10


def _memory():
    try:
        handle = get_handle()
        from agentx.core.memory import Memory
        return Memory(handle.cfg)
    except AgentXUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project memory unavailable: {e}") from e


def _entry_out(entry: Any) -> ProjectMemoryEntryOut:
    raw = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
    return ProjectMemoryEntryOut(**raw)


def _stats_out(raw: dict[str, Any]) -> ProjectMemoryStatsOut:
    return ProjectMemoryStatsOut(
        enabled=bool(raw.get("enabled", True)),
        entry_count=int(raw.get("entry_count") or 0),
        ledger_path=raw.get("ledger_path"),
        by_scope=dict(raw.get("by_scope") or {}),
        by_kind=dict(raw.get("by_kind") or {}),
        by_status=dict(raw.get("by_status") or {}),
    )


@router.get("/memory/project/stats", response_model=ProjectMemoryStatsOut)
def project_memory_stats() -> ProjectMemoryStatsOut:
    memory = _memory()
    stats = memory.stats().get("project_memory") or {}
    return _stats_out(stats)


@router.get("/memory/project", response_model=ProjectMemoryListOut)
def list_project_memory(
    scope: str | None = None,
    module: str | None = None,
    status: str | None = "active",
    limit: int = Query(100, ge=1, le=500),
) -> ProjectMemoryListOut:
    memory = _memory()
    entries = memory.list_project_memory(scope=scope or None, module=module or None, status=status or None, limit=limit)
    stats = memory.stats().get("project_memory") or {}
    return ProjectMemoryListOut(entries=[_entry_out(e) for e in entries], stats=_stats_out(stats))


@router.get("/memory/project/search", response_model=ProjectMemorySearchOut)
def search_project_memory(
    query: str = Query(..., min_length=1),
    scope: str | None = None,
    kind: str | None = None,
    module: str | None = None,
    file_path: str | None = None,
    task_id: str | None = None,
    limit: int = Query(8, ge=1, le=50),
) -> ProjectMemorySearchOut:
    memory = _memory()
    hits = memory.retrieve_project_memory(
        query,
        k=limit,
        scopes=[scope] if scope else [],
        kinds=[kind] if kind else [],
        module=module or None,
        file_path=file_path or None,
        task_id=task_id or None,
    )
    return ProjectMemorySearchOut(
        hits=[ProjectMemoryHitOut(entry=_entry_out(hit.entry), content=hit.content, score=hit.score, snippet=hit.snippet) for hit in hits]
    )


@router.post("/memory/project", response_model=ProjectMemoryEntryOut)
def create_project_memory(payload: ProjectMemoryCreateIn) -> ProjectMemoryEntryOut:
    memory = _memory()
    try:
        entry = memory.add_project_memory(**payload.model_dump())
        return _entry_out(entry)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/memory/project/context")
def project_memory_context(payload: ProjectContextIn) -> dict[str, Any]:
    memory = _memory()
    return memory.project_context_stack(task=payload.task, module=payload.module, files=payload.files, k=payload.k)


@router.patch("/memory/project/{entry_id}/status", response_model=ProjectMemoryEntryOut)
def update_project_memory_status(entry_id: str, payload: ProjectMemoryStatusIn) -> ProjectMemoryEntryOut:
    memory = _memory()
    try:
        entry = memory._get_project_store().mark_status(entry_id, payload.status, reason=payload.reason)
        return _entry_out(entry)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
