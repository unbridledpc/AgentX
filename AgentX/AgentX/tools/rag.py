from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from agentx.core.chunking import chunk_text
from agentx.core.fs_policy import FsPolicyError, validate_path
from agentx.core.rag_store import RagStore
from agentx.tools.base import Tool, ToolArgument, ToolExecutionError


def _doc_id_for_path(path: Path) -> str:
    h = hashlib.sha256(str(path).encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"file:{h}"


class RagUpsertTextTool(Tool):
    name = "rag.upsert_text"
    description = "Upsert a text document into RAG (trusted/untrusted metadata supported)"
    args = (
        ToolArgument("doc_id", str, "Document id", required=True),
        ToolArgument("title", str, "Document title", required=True),
        ToolArgument("source", str, "Source identifier (path or URL)", required=True),
        ToolArgument("text", str, "Text content", required=True),
        ToolArgument("source_type", str, "Source type (local|web|note)", required=False, default="note"),
        ToolArgument("trusted", bool, "Trusted source?", required=False, default=False),
    )
    safety_flags = ("rag",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        if not ctx.cfg.rag.enabled:
            raise ToolExecutionError("RAG is disabled.")
        store = RagStore(ctx.cfg.rag.db_path)
        chunks = [
            (c.chunk_id, c.content)
            for c in chunk_text(
                args["text"], chunk_chars=ctx.cfg.rag.chunk_chars, overlap_chars=ctx.cfg.rag.chunk_overlap_chars
            )
        ]
        store.upsert_document(
            doc_id=args["doc_id"],
            title=args["title"],
            source=args["source"],
            chunks=chunks,
            meta={"source_type": args.get("source_type") or "note", "trusted": bool(args.get("trusted"))},
        )
        return {"ok": True, "doc_id": args["doc_id"], "chunks": len(chunks)}


class RagQueryTool(Tool):
    name = "rag.query"
    description = "Query RAG (SQLite FTS) and return top hits with source metadata"
    args = (
        ToolArgument("query", str, "Query text", required=True),
        ToolArgument("k", int, "Top K", required=False, default=5),
        ToolArgument("collection", str, "Optional: only return docs from this collection", required=False, default=""),
        ToolArgument("source_prefix", str, "Optional: only return docs whose source starts with this prefix", required=False, default=""),
        ToolArgument("tag_prefix", str, "Optional: only return docs with any tag starting with this prefix", required=False, default=""),
    )
    safety_flags = ("rag",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        if not ctx.cfg.rag.enabled:
            raise ToolExecutionError("RAG is disabled.")
        store = RagStore(ctx.cfg.rag.db_path)

        want_k = max(1, min(int(args.get("k") or 5), 20))
        # Filtering is applied post-query (meta lives in documents.meta_json), so oversample.
        hits = store.query_tiered(args["query"], k=min(200, max(want_k * 20, want_k)))

        collection = str(args.get("collection") or "").strip()
        source_prefix = str(args.get("source_prefix") or "").strip()
        tag_prefix = str(args.get("tag_prefix") or "").strip()

        def _matches(h) -> bool:  # type: ignore[no-untyped-def]
            meta = h.meta or {}
            if source_prefix:
                src = str(h.source or "")
                src_id = str(meta.get("source_id") or "")
                if not (src.startswith(source_prefix) or src_id.startswith(source_prefix)):
                    return False
            if collection:
                coll = str(meta.get("collection") or "")
                tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
                tags_s = [str(t) for t in tags if isinstance(t, (str, int, float, bool))]
                if coll != collection and f"collection:{collection}" not in tags_s:
                    return False
            if tag_prefix:
                tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
                tags_s = [str(t) for t in tags if isinstance(t, (str, int, float, bool))]
                if not any(str(t).startswith(tag_prefix) for t in tags_s):
                    return False
            return True

        hits = [h for h in hits if _matches(h)][:want_k]
        out = []
        for h in hits:
            out.append(
                {
                    "doc_id": h.doc_id,
                    "chunk_id": h.chunk_id,
                    "title": h.title,
                    "source": h.source,
                    "snippet": h.snippet,
                    "content": h.content[:2000],
                    "score": h.score,
                }
            )
        return {
            "query": args["query"],
            "filters": {"collection": collection or None, "source_prefix": source_prefix or None, "tag_prefix": tag_prefix or None},
            "hits": out,
            "stats": store.stats(),
        }


class RagIngestPathTool(Tool):
    name = "rag.ingest_path"
    description = "Ingest local text files into RAG (safe roots only)"
    args = (
        ToolArgument("path", str, "File or directory path", required=True),
        ToolArgument("recursive", bool, "Recurse when path is a directory", required=False, default=True),
        ToolArgument("max_files", int, "Max files to ingest", required=False, default=200),
    )
    safety_flags = ("rag", "filesystem")
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        if not ctx.cfg.rag.enabled:
            raise ToolExecutionError("RAG is disabled.")

        try:
            base = validate_path(args["path"], cfg=ctx.cfg, for_write=False).path
        except FsPolicyError as e:
            raise ToolExecutionError(str(e))
        if not base.exists():
            raise ToolExecutionError("Path not found.")

        store = RagStore(ctx.cfg.rag.db_path)
        recursive = bool(args.get("recursive") or False)
        max_files = max(1, min(int(args.get("max_files") or 200), 2000))
        ingested = 0
        skipped = 0

        def ingest_file(p: Path) -> None:
            nonlocal ingested, skipped
            try:
                if p.stat().st_size > ctx.cfg.fs.max_read_bytes:
                    skipped += 1
                    return
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                skipped += 1
                return
            doc_id = _doc_id_for_path(p)
            chunks = [
                (c.chunk_id, c.content)
                for c in chunk_text(text, chunk_chars=ctx.cfg.rag.chunk_chars, overlap_chars=ctx.cfg.rag.chunk_overlap_chars)
            ]
            store.upsert_document(
                doc_id=doc_id,
                title=p.name,
                source=str(p),
                chunks=chunks,
                meta={"source_type": "local", "trusted": True, "path": str(p)},
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
                if p.suffix.lower() not in (".txt", ".md", ".py", ".json", ".toml", ".yaml", ".yml", ".ini", ".log", ".csv"):
                    continue
                ingest_file(p)

        return {"ok": True, "ingested": ingested, "skipped": skipped, "stats": store.stats()}
