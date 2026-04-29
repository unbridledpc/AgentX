from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agentx.config import AgentXConfig
from agentx.core.chunking import chunk_text
from agentx.core.fs_policy import FsPolicyError, validate_path
from agentx.core.rag_store import RagStore
from agentx.core.project_memory import ProjectMemoryStore, ProjectMemoryEntry, ProjectMemoryHit


class MemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoryChunk:
    text: str
    source_id: str
    ts: float
    tags: list[str]
    trust: str  # "trusted" | "untrusted"
    score: float | None


def _is_untrusted(tags: Iterable[str], meta: dict[str, Any] | None) -> bool:
    if meta and isinstance(meta.get("trusted"), bool):
        return not bool(meta.get("trusted"))
    for t in tags:
        if str(t).strip().lower().startswith("untrusted:"):
            return True
    return False


def _stable_doc_id(prefix: str, source_id: str) -> str:
    h = hashlib.sha256(source_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}:{h}"


class Memory:
    """Single memory subsystem: short-term events + long-term RAG (SQLite FTS).

    Storage:
    - Events: append-only JSONL at cfg.memory.events_path
    - RAG: SQLite FTS at cfg.memory.db_path
    """

    def __init__(self, cfg: AgentXConfig):
        self.cfg = cfg
        self._store: RagStore | None = None
        self._project_store: ProjectMemoryStore | None = None

    def ensure_writable(self) -> tuple[bool, str | None]:
        if not self.cfg.memory.enabled:
            return True, None
        try:
            # Ensure events file is writable.
            self.cfg.memory.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cfg.memory.events_path.open("a", encoding="utf-8"):
                pass
            # Ensure SQLite is writable by initializing the store.
            self._get_store()
            return True, None
        except Exception as e:
            return False, str(e)

    def add_event(self, role: str, content: str, tags: list[str], meta: dict[str, Any] | None = None) -> None:
        if not self.cfg.memory.enabled:
            return
        payload = {
            "ts": time.time(),
            "role": role,
            "content": content,
            "tags": tags or [],
            "meta": meta or {},
        }
        try:
            self.cfg.memory.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cfg.memory.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            raise MemoryError(f"Failed to write memory events: {e}")

    def ingest_text(self, source_id: str, text: str, tags: list[str], meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.cfg.memory.enabled:
            raise MemoryError("Memory is disabled.")
        if self.cfg.memory.backend != "sqlite_fts":
            raise MemoryError(f"Unsupported memory backend: {self.cfg.memory.backend!r}")
        if not source_id:
            raise MemoryError("source_id is required.")

        meta_d = dict(meta or {})
        meta_d.setdefault("tags", list(tags or []))
        meta_d.setdefault("source_id", source_id)
        meta_d.setdefault("ts", time.time())
        meta_d.setdefault("trusted", not _is_untrusted(tags or [], meta_d))

        store = self._get_store()
        doc_id = _stable_doc_id("mem", source_id)
        content_sha256 = hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()
        existing = store.get_document_meta(doc_id) or {}
        if existing.get("source_id") == source_id and existing.get("content_sha256") == content_sha256:
            return {"ok": True, "doc_id": doc_id, "ingested_count": 0, "skipped_count": 1, "dedupe": True}
        chunks = [
            (c.chunk_id, c.content)
            for c in chunk_text(
                text or "",
                chunk_chars=self.cfg.memory.chunk_chars,
                overlap_chars=self.cfg.memory.chunk_overlap_chars,
            )
        ]
        meta_d["content_sha256"] = content_sha256
        store.upsert_document(
            doc_id=doc_id,
            title=meta_d.get("title") or source_id,
            source=source_id,
            chunks=chunks,
            meta=meta_d,
        )
        return {
            "ok": True,
            "doc_id": doc_id,
            "chunks": len(chunks),
            "ingested_count": 1,
            "skipped_count": 0,
            "dedupe": False,
        }

    def ingest_path(self, path: str, tags: list[str], meta: dict[str, Any] | None = None, *, recursive: bool = True, max_files: int = 200) -> dict[str, Any]:
        if not self.cfg.memory.enabled:
            raise MemoryError("Memory is disabled.")
        if self.cfg.memory.backend != "sqlite_fts":
            raise MemoryError(f"Unsupported memory backend: {self.cfg.memory.backend!r}")

        try:
            base = validate_path(path, cfg=self.cfg, for_write=False).path
        except FsPolicyError as e:
            raise MemoryError(str(e))
        if not base.exists():
            raise MemoryError("Path not found.")

        ingested = 0
        skipped = 0
        max_files = max(1, min(int(max_files), 5000))

        def ingest_file(p: Path) -> None:
            nonlocal ingested, skipped
            try:
                if p.stat().st_size > self.cfg.fs.max_read_bytes:
                    skipped += 1
                    return
                raw = p.read_bytes()
                file_sha256 = hashlib.sha256(raw).hexdigest()
                source_id = f"file:{str(p)}"
                doc_id = _stable_doc_id("mem", source_id)
                existing = self._get_store().get_document_meta(doc_id) or {}
                if existing.get("source_id") == source_id and existing.get("file_sha256") == file_sha256:
                    skipped += 1
                    return
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                skipped += 1
                return

            self.ingest_text(
                source_id=source_id,
                text=text,
                tags=tags,
                meta={**(meta or {}), "source_type": "local", "path": str(p), "title": p.name, "trusted": True, "file_sha256": file_sha256},
            )
            ingested += 1

        if base.is_file():
            ingest_file(base)
        else:
            it = base.rglob("*") if recursive else base.iterdir()
            for p in it:
                if ingested >= max_files:
                    break
                if not p.is_file():
                    continue
                # Basic extension allowlist for "text-like" ingestion.
                if p.suffix.lower() not in (".txt", ".md", ".py", ".json", ".toml", ".yaml", ".yml", ".ini", ".log", ".csv", ".ts", ".tsx", ".js", ".html", ".css"):
                    continue
                ingest_file(p)

        return {"ok": True, "ingested_count": ingested, "skipped_count": skipped, "stats": self._get_store().stats()}

    def retrieve(self, query: str, k: int = 8, tags_filter: list[str] | None = None) -> list[MemoryChunk]:
        if not self.cfg.memory.enabled:
            return []
        if self.cfg.memory.backend != "sqlite_fts":
            return []
        k = max(1, min(int(k), 50))
        q = self._normalize_query(query)
        hits = self._get_store().query_tiered(q, k=k, min_token_len=3)
        out: list[MemoryChunk] = []
        for h in hits:
            meta = h.meta or {}
            tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
            tags_s = [str(t) for t in tags if isinstance(t, (str, int, float, bool))]
            if tags_filter:
                wanted = set(str(t).lower() for t in tags_filter if t)
                if wanted and not (wanted & set(str(t).lower() for t in tags_s)):
                    continue
            ts = float(meta.get("ts") or meta.get("fetched_at") or time.time())
            untrusted = _is_untrusted(tags_s, meta)
            out.append(
                MemoryChunk(
                    text=h.content,
                    source_id=str(h.source or h.doc_id),
                    ts=ts,
                    tags=tags_s,
                    trust="untrusted" if untrusted else "trusted",
                    score=h.score,
                )
            )
        return self._apply_thresholds(query=query, chunks=out, k=k)


    def add_project_memory(
        self,
        *,
        title: str,
        summary: str,
        scope: str,
        kind: str,
        durability: str = "medium",
        module: str | None = None,
        file_path: str | None = None,
        task_id: str | None = None,
        source: str = "manual",
        tags: list[str] | None = None,
        affected_files: list[str] | None = None,
        decisions: list[str] | None = None,
        assumptions_corrected: list[str] | None = None,
        evidence: list[str] | None = None,
        confidence: float = 0.75,
        meta: dict[str, Any] | None = None,
    ) -> ProjectMemoryEntry:
        """Add one scoped durable project-memory entry.

        This is the Phase 1 entrypoint used by Draft Workspace, task reflection,
        tools, and future UI actions. It stores the structured entry and indexes
        searchable rendered content into the existing SQLite FTS memory backend.
        """

        if not self.cfg.memory.enabled:
            raise MemoryError("Memory is disabled.")
        return self._get_project_store().add_entry(
            title=title,
            summary=summary,
            scope=scope,
            kind=kind,
            durability=durability,
            module=module,
            file_path=file_path,
            task_id=task_id,
            source=source,
            tags=tags or [],
            affected_files=affected_files or [],
            decisions=decisions or [],
            assumptions_corrected=assumptions_corrected or [],
            evidence=evidence or [],
            confidence=confidence,
            meta=meta or {},
        )

    def ingest_project_raw(
        self,
        *,
        source_id: str,
        text: str,
        scope_hint: str | None = None,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ProjectMemoryEntry:
        if not self.cfg.memory.enabled:
            raise MemoryError("Memory is disabled.")
        return self._get_project_store().ingest_raw(
            source_id=source_id,
            text=text,
            scope_hint=scope_hint,
            tags=tags or [],
            meta=meta or {},
        )

    def retrieve_project_memory(
        self,
        query: str,
        *,
        k: int = 8,
        scopes: list[str] | None = None,
        kinds: list[str] | None = None,
        module: str | None = None,
        file_path: str | None = None,
        task_id: str | None = None,
        include_task_notes: bool = True,
    ) -> list[ProjectMemoryHit]:
        if not self.cfg.memory.enabled:
            return []
        return self._get_project_store().retrieve(
            query,
            k=k,
            scopes=scopes or [],
            kinds=kinds or [],
            module=module,
            file_path=file_path,
            task_id=task_id,
            include_task_notes=include_task_notes,
        )

    def project_context_stack(
        self,
        *,
        task: str,
        module: str | None = None,
        files: list[str] | None = None,
        k: int = 10,
    ) -> dict[str, Any]:
        if not self.cfg.memory.enabled:
            return {"global": [], "module": [], "files": [], "task": []}
        return self._get_project_store().retrieve_for_task(task, module=module, files=files or [], k=k)

    def list_project_memory(
        self,
        *,
        scope: str | None = None,
        module: str | None = None,
        status: str | None = "active",
        limit: int = 100,
    ) -> list[ProjectMemoryEntry]:
        if not self.cfg.memory.enabled:
            return []
        return self._get_project_store().list_entries(scope=scope, module=module, status=status, limit=limit)

    def stats(self) -> dict[str, Any]:
        if not self.cfg.memory.enabled:
            return {"enabled": False}
        store = self._get_store()
        st = store.stats()
        db_size = None
        try:
            db_size = os.path.getsize(self.cfg.memory.db_path)
        except Exception:
            db_size = None

        events_count = 0
        try:
            if self.cfg.memory.events_path.exists():
                with self.cfg.memory.events_path.open("r", encoding="utf-8") as f:
                    for _ in f:
                        events_count += 1
        except Exception:
            events_count = -1

        tag_counts: dict[str, int] = {}
        for row in store.list_documents_meta(limit=50_000):
            meta = row.get("meta") if isinstance(row, dict) else {}
            tags = meta.get("tags") if isinstance(meta, dict) else None
            if not isinstance(tags, list):
                continue
            for t in tags:
                if not isinstance(t, str):
                    continue
                key = t.strip()
                if not key:
                    continue
                tag_counts[key] = tag_counts.get(key, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:10]

        project_memory_stats = {}
        try:
            project_memory_stats = self._get_project_store().stats()
        except Exception:
            project_memory_stats = {}

        return {
            "enabled": True,
            "backend": self.cfg.memory.backend,
            "db_path": str(self.cfg.memory.db_path),
            "events_path": str(self.cfg.memory.events_path),
            "doc_count": st.get("doc_count", 0),
            "chunk_count": st.get("chunk_count", 0),
            "events_count": events_count,
            "db_bytes": db_size,
            "top_tags": [{"tag": t, "count": c} for (t, c) in top_tags],
            "project_memory": project_memory_stats,
        }

    def prune_events(self, *, older_than_days: int, dry_run: bool = False) -> dict[str, Any]:
        if not self.cfg.memory.enabled:
            raise MemoryError("Memory is disabled.")
        days = max(1, int(older_than_days))
        cutoff = time.time() - (days * 86400)
        src = self.cfg.memory.events_path
        if not src.exists():
            return {"ok": True, "pruned": 0, "kept": 0, "older_than_days": days, "dry_run": bool(dry_run)}

        kept_lines: list[str] = []
        pruned = 0
        kept = 0
        with src.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict) or "ts" not in obj:
                        # Keep lines without a timestamp to avoid accidental data loss.
                        kept_lines.append(line)
                        kept += 1
                        continue
                    ts = float(obj.get("ts"))
                except Exception:
                    # Keep corrupt lines to avoid data loss.
                    kept_lines.append(line)
                    kept += 1
                    continue
                if ts < cutoff:
                    pruned += 1
                    continue
                kept_lines.append(line)
                kept += 1

        if dry_run:
            return {"ok": True, "pruned": pruned, "kept": kept, "older_than_days": days, "dry_run": True}

        tmp = src.with_suffix(src.suffix + ".tmp")
        tmp.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
        tmp.replace(src)
        return {"ok": True, "pruned": pruned, "kept": kept, "older_than_days": days, "dry_run": False}

    def _apply_thresholds(self, *, query: str, chunks: list[MemoryChunk], k: int) -> list[MemoryChunk]:
        """Deterministic post-filtering after FTS retrieval.

        - Keep top-k.
        - If we already have >=k candidates, drop noisy results that only match a single token
          (while keeping at least k if possible).
        """

        if len(chunks) <= k:
            return chunks[:k]

        tokens = [t for t in self._normalize_query(query).split() if len(t) >= 3]
        if not tokens:
            return chunks[:k]

        def overlap_count(text: str) -> int:
            low = (text or "").lower()
            return sum(1 for t in tokens if t in low)

        min_overlap = 2 if len(tokens) >= 4 else 1
        filtered = [c for c in chunks if overlap_count(c.text) >= min_overlap]
        if len(filtered) >= k:
            return filtered[:k]
        return chunks[:k]

    def _normalize_query(self, query: str) -> str:
        """Normalize user queries to work well with strict FTS token matching.

        RagStore.query() uses an AND-joined token query. If we pass a full natural-language
        question, it often becomes too strict. Here we extract likely-keywords and drop
        common stopwords to improve recall without changing the underlying store.
        """

        q = (query or "").strip()
        if not q:
            return ""
        tokens = [t.lower() for t in q.replace("?", " ").replace(".", " ").split()]
        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "to",
            "of",
            "in",
            "on",
            "for",
            "with",
            "is",
            "are",
            "was",
            "were",
            "be",
            "does",
            "do",
            "did",
            "what",
            "where",
            "when",
            "why",
            "how",
            "use",
            "uses",
        }
        keywords = [t for t in tokens if t and t not in stop and len(t) > 2]
        # Keep it small to avoid strict AND matching on irrelevant tokens.
        picked = keywords[:8] if keywords else tokens[:4]
        return " ".join(picked)


    def _get_project_store(self) -> ProjectMemoryStore:
        if self._project_store is None:
            self._project_store = ProjectMemoryStore(self.cfg, store=self._get_store())
        return self._project_store

    def _get_store(self) -> RagStore:
        if self._store is None:
            self._store = RagStore(self.cfg.memory.db_path)
        return self._store
