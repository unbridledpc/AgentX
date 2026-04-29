from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from agentx.config import AgentXConfig
from agentx.core.chunking import chunk_text
from agentx.core.rag_store import RagHit, RagStore


class ProjectMemoryError(RuntimeError):
    pass


class MemoryScope(str, Enum):
    GLOBAL = "global"
    MODULE = "module"
    FILE = "file"
    TASK = "task"
    DECISION = "decision"
    ERROR = "error"


class MemoryKind(str, Enum):
    ARCHITECTURE = "architecture"
    CONVENTION = "convention"
    DEPENDENCY = "dependency"
    MODULE_NOTE = "module_note"
    TASK_NOTE = "task_note"
    DECISION = "decision"
    ERROR = "error"
    TEST_RESULT = "test_result"
    SETUP = "setup"
    USER_PREFERENCE = "user_preference"
    CHANGE_SUMMARY = "change_summary"


class Durability(str, Enum):
    EPHEMERAL = "ephemeral"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EntryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class ProjectMemoryEntry:
    entry_id: str
    title: str
    summary: str
    scope: MemoryScope
    kind: MemoryKind
    durability: Durability
    created_at: float
    updated_at: float
    module: str | None = None
    file_path: str | None = None
    task_id: str | None = None
    source: str = "manual"
    tags: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    assumptions_corrected: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    status: EntryStatus = EntryStatus.ACTIVE
    confidence: float = 0.75
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.value
        data["kind"] = self.kind.value
        data["durability"] = self.durability.value
        data["status"] = self.status.value
        return data

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ProjectMemoryEntry":
        if not isinstance(raw, dict):
            raise ProjectMemoryError("Project memory entry must be a dict.")
        now = time.time()
        return ProjectMemoryEntry(
            entry_id=str(raw.get("entry_id") or raw.get("id") or uuid.uuid4().hex),
            title=str(raw.get("title") or "Untitled memory").strip()[:240] or "Untitled memory",
            summary=str(raw.get("summary") or raw.get("content") or "").strip(),
            scope=_coerce_enum(MemoryScope, raw.get("scope"), MemoryScope.TASK),
            kind=_coerce_enum(MemoryKind, raw.get("kind"), MemoryKind.TASK_NOTE),
            durability=_coerce_enum(Durability, raw.get("durability"), Durability.MEDIUM),
            created_at=float(raw.get("created_at") or now),
            updated_at=float(raw.get("updated_at") or now),
            module=_clean_optional(raw.get("module")),
            file_path=_clean_optional(raw.get("file_path")),
            task_id=_clean_optional(raw.get("task_id")),
            source=str(raw.get("source") or "manual").strip() or "manual",
            tags=_clean_list(raw.get("tags")),
            affected_files=_clean_list(raw.get("affected_files")),
            decisions=_clean_list(raw.get("decisions")),
            assumptions_corrected=_clean_list(raw.get("assumptions_corrected")),
            evidence=_clean_list(raw.get("evidence")),
            status=_coerce_enum(EntryStatus, raw.get("status"), EntryStatus.ACTIVE),
            confidence=max(0.0, min(float(raw.get("confidence") if raw.get("confidence") is not None else 0.75), 1.0)),
            meta=dict(raw.get("meta") or {}),
        )


@dataclass(frozen=True)
class ProjectMemoryHit:
    entry: ProjectMemoryEntry
    content: str
    score: float | None = None
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "content": self.content,
            "score": self.score,
            "snippet": self.snippet,
        }


class ProjectMemoryStore:
    """Scoped durable project knowledge built on AgentX's SQLite FTS store.

    The store writes every durable entry to the existing RAG database with a
    project-memory metadata envelope, then maintains a compact JSONL ledger for
    cheap listing, auditability, and future UI rendering.
    """

    META_TYPE = "agentx.project_memory"

    def __init__(self, cfg: AgentXConfig, *, store: RagStore | None = None) -> None:
        self.cfg = cfg
        self.store = store or RagStore(cfg.memory.db_path)
        self.ledger_path = cfg.paths.memory_dir / "project_memory_entries.jsonl"
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def add_entry(
        self,
        *,
        title: str,
        summary: str,
        scope: str | MemoryScope,
        kind: str | MemoryKind,
        durability: str | Durability = Durability.MEDIUM,
        module: str | None = None,
        file_path: str | None = None,
        task_id: str | None = None,
        source: str = "manual",
        tags: Iterable[str] | None = None,
        affected_files: Iterable[str] | None = None,
        decisions: Iterable[str] | None = None,
        assumptions_corrected: Iterable[str] | None = None,
        evidence: Iterable[str] | None = None,
        confidence: float = 0.75,
        meta: dict[str, Any] | None = None,
        entry_id: str | None = None,
    ) -> ProjectMemoryEntry:
        title_s = (title or "").strip()
        summary_s = (summary or "").strip()
        if not title_s:
            raise ProjectMemoryError("title is required.")
        if not summary_s:
            raise ProjectMemoryError("summary is required.")

        now = time.time()
        scope_e = _coerce_enum(MemoryScope, scope, MemoryScope.TASK)
        kind_e = _coerce_enum(MemoryKind, kind, MemoryKind.TASK_NOTE)
        durability_e = _coerce_enum(Durability, durability, Durability.MEDIUM)
        tags_l = _normalize_tags(tags, scope_e=scope_e, kind_e=kind_e, module=module, file_path=file_path, task_id=task_id)
        entry = ProjectMemoryEntry(
            entry_id=entry_id or self._new_entry_id(title_s, summary_s, scope_e, kind_e, module, file_path, task_id),
            title=title_s[:240],
            summary=summary_s,
            scope=scope_e,
            kind=kind_e,
            durability=durability_e,
            created_at=now,
            updated_at=now,
            module=_clean_optional(module),
            file_path=_clean_optional(file_path),
            task_id=_clean_optional(task_id),
            source=(source or "manual").strip() or "manual",
            tags=tags_l,
            affected_files=_clean_list(list(affected_files or [])),
            decisions=_clean_list(list(decisions or [])),
            assumptions_corrected=_clean_list(list(assumptions_corrected or [])),
            evidence=_clean_list(list(evidence or [])),
            confidence=max(0.0, min(float(confidence), 1.0)),
            meta=dict(meta or {}),
        )
        self._upsert_entry(entry)
        self._append_ledger(entry)
        return entry

    def ingest_raw(
        self,
        *,
        source_id: str,
        text: str,
        scope_hint: str | None = None,
        tags: Iterable[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ProjectMemoryEntry:
        """Distill raw material into a conservative task-scoped memory entry.

        This method is deterministic. It does not pretend to perform model-level
        summarization; callers can pass already-distilled text when they have an
        LLM available. It strips obvious log noise, chooses a scope from hints,
        and stores only a bounded reusable note.
        """

        source_s = (source_id or "raw").strip() or "raw"
        cleaned = distill_reusable_text(text)
        if not cleaned:
            raise ProjectMemoryError("raw text did not contain reusable project knowledge.")
        inferred_scope = infer_scope(scope_hint=scope_hint, text=cleaned, meta=meta or {})
        inferred_kind = infer_kind(cleaned, meta=meta or {})
        return self.add_entry(
            title=f"Distilled knowledge from {source_s[:80]}",
            summary=cleaned,
            scope=inferred_scope,
            kind=inferred_kind,
            durability=Durability.MEDIUM,
            source=source_s,
            tags=list(tags or []),
            affected_files=_clean_list((meta or {}).get("affected_files")),
            module=_clean_optional((meta or {}).get("module")),
            file_path=_clean_optional((meta or {}).get("file_path")),
            task_id=_clean_optional((meta or {}).get("task_id")),
            meta=dict(meta or {}),
        )

    def retrieve(
        self,
        query: str,
        *,
        k: int = 8,
        scopes: Iterable[str | MemoryScope] | None = None,
        kinds: Iterable[str | MemoryKind] | None = None,
        module: str | None = None,
        file_path: str | None = None,
        task_id: str | None = None,
        include_task_notes: bool = True,
        include_discarded: bool = False,
    ) -> list[ProjectMemoryHit]:
        q = (query or "").strip()
        if not q:
            return []
        k = max(1, min(int(k), 50))
        hits = self.store.query_tiered(q, k=max(k * 4, 12), min_token_len=3)
        scope_set = {_coerce_enum(MemoryScope, s, MemoryScope.TASK).value for s in scopes or []}
        kind_set = {_coerce_enum(MemoryKind, s, MemoryKind.TASK_NOTE).value for s in kinds or []}
        out: list[ProjectMemoryHit] = []
        for hit in hits:
            entry = self._entry_from_hit(hit)
            if entry is None:
                continue
            if entry.status == EntryStatus.DISCARDED and not include_discarded:
                continue
            if not include_task_notes and entry.scope == MemoryScope.TASK:
                continue
            if scope_set and entry.scope.value not in scope_set:
                continue
            if kind_set and entry.kind.value not in kind_set:
                continue
            if module and (entry.module or "").lower() != module.lower():
                continue
            if file_path and _norm_path(entry.file_path) != _norm_path(file_path):
                continue
            if task_id and entry.task_id != task_id:
                continue
            out.append(ProjectMemoryHit(entry=entry, content=hit.content, score=hit.score, snippet=hit.snippet or ""))
            if len(out) >= k:
                break
        return out

    def retrieve_for_task(
        self,
        task: str,
        *,
        module: str | None = None,
        files: Iterable[str] | None = None,
        k: int = 10,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return the scoped context stack the UI can show before a run."""

        files_l = _clean_list(list(files or []))
        global_hits = self.retrieve(task, k=max(1, k // 3), scopes=[MemoryScope.GLOBAL, MemoryScope.DECISION], include_task_notes=False)
        module_hits = self.retrieve(task, k=max(1, k // 3), scopes=[MemoryScope.MODULE], module=module) if module else []
        file_hits: list[ProjectMemoryHit] = []
        for p in files_l[:6]:
            file_hits.extend(self.retrieve(task, k=2, scopes=[MemoryScope.FILE], file_path=p))
        task_hits = self.retrieve(task, k=max(1, k // 3), scopes=[MemoryScope.TASK, MemoryScope.ERROR], include_task_notes=True)
        return {
            "global": [h.to_dict() for h in _dedupe_hits(global_hits)],
            "module": [h.to_dict() for h in _dedupe_hits(module_hits)],
            "files": [h.to_dict() for h in _dedupe_hits(file_hits)],
            "task": [h.to_dict() for h in _dedupe_hits(task_hits)],
        }

    def list_entries(
        self,
        *,
        scope: str | MemoryScope | None = None,
        module: str | None = None,
        status: str | EntryStatus | None = EntryStatus.ACTIVE,
        limit: int = 100,
    ) -> list[ProjectMemoryEntry]:
        rows = self.store.list_documents_meta(limit=100_000)
        scope_e = _coerce_enum(MemoryScope, scope, None) if scope is not None else None
        status_e = _coerce_enum(EntryStatus, status, None) if status is not None else None
        out: list[ProjectMemoryEntry] = []
        for row in rows:
            meta = row.get("meta") if isinstance(row, dict) else {}
            if not isinstance(meta, dict) or meta.get("meta_type") != self.META_TYPE:
                continue
            raw = meta.get("entry")
            if not isinstance(raw, dict):
                continue
            try:
                entry = ProjectMemoryEntry.from_dict(raw)
            except Exception:
                continue
            if scope_e and entry.scope != scope_e:
                continue
            if status_e and entry.status != status_e:
                continue
            if module and (entry.module or "").lower() != module.lower():
                continue
            out.append(entry)
        out.sort(key=lambda e: (e.updated_at, e.created_at), reverse=True)
        return out[: max(1, min(int(limit), 1000))]

    def get_entry(self, entry_id: str) -> ProjectMemoryEntry | None:
        if not entry_id:
            return None
        meta = self.store.get_document_meta(self._doc_id(entry_id))
        if not isinstance(meta, dict) or meta.get("meta_type") != self.META_TYPE:
            return None
        raw = meta.get("entry")
        if not isinstance(raw, dict):
            return None
        return ProjectMemoryEntry.from_dict(raw)

    def mark_status(self, entry_id: str, status: str | EntryStatus, *, reason: str = "") -> ProjectMemoryEntry:
        entry = self.get_entry(entry_id)
        if entry is None:
            raise ProjectMemoryError(f"project memory entry not found: {entry_id}")
        new_status = _coerce_enum(EntryStatus, status, EntryStatus.ACTIVE)
        data = entry.to_dict()
        data["status"] = new_status.value
        data["updated_at"] = time.time()
        meta = dict(data.get("meta") or {})
        if reason:
            meta.setdefault("status_history", []).append({"ts": time.time(), "status": new_status.value, "reason": reason})
        data["meta"] = meta
        updated = ProjectMemoryEntry.from_dict(data)
        self._upsert_entry(updated)
        self._append_ledger(updated)
        return updated

    def stats(self) -> dict[str, Any]:
        entries = self.list_entries(status=None, limit=100_000)
        by_scope: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for e in entries:
            by_scope[e.scope.value] = by_scope.get(e.scope.value, 0) + 1
            by_kind[e.kind.value] = by_kind.get(e.kind.value, 0) + 1
            by_status[e.status.value] = by_status.get(e.status.value, 0) + 1
        return {
            "enabled": bool(self.cfg.memory.enabled),
            "entry_count": len(entries),
            "ledger_path": str(self.ledger_path),
            "by_scope": by_scope,
            "by_kind": by_kind,
            "by_status": by_status,
        }

    def _upsert_entry(self, entry: ProjectMemoryEntry) -> None:
        content = render_entry_content(entry)
        chunks = [(c.chunk_id, c.content) for c in chunk_text(content, chunk_chars=self.cfg.memory.chunk_chars, overlap_chars=self.cfg.memory.chunk_overlap_chars)]
        if not chunks:
            chunks = [("chunk-0000", content)]
        meta = {
            "meta_type": self.META_TYPE,
            "entry_id": entry.entry_id,
            "source_id": f"project-memory:{entry.entry_id}",
            "trusted": True,
            "tags": entry.tags,
            "project_memory_scope": entry.scope.value,
            "project_memory_kind": entry.kind.value,
            "project_memory_durability": entry.durability.value,
            "module": entry.module,
            "file_path": entry.file_path,
            "task_id": entry.task_id,
            "status": entry.status.value,
            "ts": entry.updated_at,
            "entry": entry.to_dict(),
            "content_sha256": hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest(),
        }
        self.store.upsert_document(
            doc_id=self._doc_id(entry.entry_id),
            title=entry.title,
            source=f"project-memory:{entry.entry_id}",
            chunks=chunks,
            meta=meta,
        )

    def _append_ledger(self, entry: ProjectMemoryEntry) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "entry": entry.to_dict()}, ensure_ascii=False, sort_keys=True) + "\n")

    def _entry_from_hit(self, hit: RagHit) -> ProjectMemoryEntry | None:
        meta = hit.meta or {}
        if not isinstance(meta, dict) or meta.get("meta_type") != self.META_TYPE:
            return None
        raw = meta.get("entry")
        if not isinstance(raw, dict):
            return None
        try:
            return ProjectMemoryEntry.from_dict(raw)
        except Exception:
            return None

    def _new_entry_id(self, title: str, summary: str, scope: MemoryScope, kind: MemoryKind, module: str | None, file_path: str | None, task_id: str | None) -> str:
        basis = "|".join([title, summary[:500], scope.value, kind.value, module or "", file_path or "", task_id or ""])
        digest = hashlib.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"pmem_{int(time.time())}_{digest}"

    def _doc_id(self, entry_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", entry_id.strip())
        return f"pmem:{safe}"


def render_entry_content(entry: ProjectMemoryEntry) -> str:
    lines = [
        f"Title: {entry.title}",
        f"Scope: {entry.scope.value}",
        f"Kind: {entry.kind.value}",
        f"Durability: {entry.durability.value}",
    ]
    if entry.module:
        lines.append(f"Module: {entry.module}")
    if entry.file_path:
        lines.append(f"File: {entry.file_path}")
    if entry.task_id:
        lines.append(f"Task: {entry.task_id}")
    if entry.affected_files:
        lines.append("Affected files: " + ", ".join(entry.affected_files))
    if entry.decisions:
        lines.append("Decisions: " + "; ".join(entry.decisions))
    if entry.assumptions_corrected:
        lines.append("Assumptions corrected: " + "; ".join(entry.assumptions_corrected))
    if entry.tags:
        lines.append("Tags: " + ", ".join(entry.tags))
    lines.append("")
    lines.append(entry.summary.strip())
    if entry.evidence:
        lines.append("")
        lines.append("Evidence:")
        lines.extend(f"- {x}" for x in entry.evidence)
    return "\n".join(lines).strip() + "\n"


def distill_reusable_text(text: str, *, max_chars: int = 2400) -> str:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    noisy_prefixes = ("debug:", "trace:", "npm warn", "warning:")
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if len(s) > 800:
            s = s[:800].rstrip() + "..."
        if low.startswith(noisy_prefixes):
            continue
        if re.fullmatch(r"[-=*_]{4,}", s):
            continue
        lines.append(s)
        if sum(len(x) + 1 for x in lines) >= max_chars:
            break
    cleaned = "\n".join(lines).strip()
    return cleaned[:max_chars].rstrip()


def infer_scope(*, scope_hint: str | None, text: str, meta: dict[str, Any]) -> MemoryScope:
    if scope_hint:
        return _coerce_enum(MemoryScope, scope_hint, MemoryScope.TASK)
    if meta.get("file_path"):
        return MemoryScope.FILE
    if meta.get("module"):
        return MemoryScope.MODULE
    low = (text or "").lower()
    if any(w in low for w in ("architecture", "project-wide", "global", "convention", "standard")):
        return MemoryScope.GLOBAL
    if any(w in low for w in ("decision", "decided", "chose", "rejected")):
        return MemoryScope.DECISION
    if any(w in low for w in ("error", "failed", "traceback", "exception")):
        return MemoryScope.ERROR
    return MemoryScope.TASK


def infer_kind(text: str, *, meta: dict[str, Any]) -> MemoryKind:
    raw = meta.get("kind")
    if raw:
        return _coerce_enum(MemoryKind, raw, MemoryKind.TASK_NOTE)
    low = (text or "").lower()
    if "architecture" in low:
        return MemoryKind.ARCHITECTURE
    if any(w in low for w in ("convention", "standard", "naming", "pattern")):
        return MemoryKind.CONVENTION
    if any(w in low for w in ("decision", "decided", "chose", "rejected")):
        return MemoryKind.DECISION
    if any(w in low for w in ("error", "failed", "traceback", "exception")):
        return MemoryKind.ERROR
    if any(w in low for w in ("test", "pytest", "passed", "failed checks")):
        return MemoryKind.TEST_RESULT
    return MemoryKind.TASK_NOTE


def _coerce_enum(enum_cls, value, default):
    if isinstance(value, enum_cls):
        return value
    if value is None:
        return default
    try:
        return enum_cls(str(value).strip().lower())
    except Exception:
        return default


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, Iterable):
        raw = list(value)
    else:
        raw = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = str(item).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:500])
    return out


def _normalize_tags(tags: Iterable[str] | None, *, scope_e: MemoryScope, kind_e: MemoryKind, module: str | None, file_path: str | None, task_id: str | None) -> list[str]:
    out = _clean_list(list(tags or []))
    required = ["project-memory", f"scope:{scope_e.value}", f"kind:{kind_e.value}"]
    if module:
        required.append(f"module:{module}")
    if file_path:
        required.append(f"file:{file_path}")
    if task_id:
        required.append(f"task:{task_id}")
    for tag in required:
        if tag.lower() not in {x.lower() for x in out}:
            out.append(tag)
    return out


def _norm_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").strip().lower()


def _dedupe_hits(hits: Iterable[ProjectMemoryHit]) -> list[ProjectMemoryHit]:
    out: list[ProjectMemoryHit] = []
    seen: set[str] = set()
    for h in hits:
        if h.entry.entry_id in seen:
            continue
        seen.add(h.entry.entry_id)
        out.append(h)
    return out
