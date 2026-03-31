from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from sol_api.config import config
from sol_api.rag.chunking import chunk_text
from sol_api.rag.store import RagStore

router = APIRouter(tags=["rag"])


def _store() -> RagStore:
    return RagStore(config.rag_db_path)


class RagStatus(BaseModel):
    enabled: bool
    db_path: str
    doc_count: int
    chunk_count: int


class RagDocIn(BaseModel):
    doc_id: str | None = None
    title: str = "Untitled"
    source: str = "manual"
    text: str = Field(..., min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)


class RagGatherIn(BaseModel):
    path: str
    max_files: int = 200
    max_bytes: int = 2_000_000
    extensions: list[str] = Field(default_factory=lambda: [".txt", ".md", ".json", ".py", ".yaml", ".yml"])


class RagQueryIn(BaseModel):
    query: str = Field(..., min_length=1)
    k: int = 5


class RagHitOut(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    source: str
    snippet: str
    content: str
    score: float | None = None


class RagQueryOut(BaseModel):
    hits: list[RagHitOut]


def _is_allowed_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in config.rag_allowed_roots:
        try:
            if resolved.is_relative_to(root.resolve()):
                return True
        except Exception:
            # Python <3.9 path compat not needed; keep safe fallback.
            try:
                root_res = root.resolve()
                if str(resolved).startswith(str(root_res) + os.sep):
                    return True
            except Exception:
                continue
    return False


@router.get("/rag/status", response_model=RagStatus)
def rag_status() -> RagStatus:
    if not config.rag_enabled:
        return RagStatus(enabled=False, db_path=str(config.rag_db_path), doc_count=0, chunk_count=0)
    stats = _store().stats()
    return RagStatus(
        enabled=True,
        db_path=str(config.rag_db_path),
        doc_count=stats["doc_count"],
        chunk_count=stats["chunk_count"],
    )


@router.post("/rag/doc", response_model=RagStatus)
def rag_upsert_doc(body: RagDocIn) -> RagStatus:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (SOL_RAG_ENABLED=false).")

    doc_id = body.doc_id or hashlib.sha256(f"{body.source}:{body.title}:{len(body.text)}".encode("utf-8")).hexdigest()[:24]
    chunks = list(chunk_text(body.text, chunk_chars=config.rag_chunk_chars, overlap_chars=config.rag_chunk_overlap_chars))
    _store().upsert_document(
        doc_id=doc_id,
        title=body.title,
        source=body.source,
        chunks=[(c.chunk_id, c.content) for c in chunks],
        meta=body.meta,
    )
    return rag_status()


@router.post("/rag/gather", response_model=RagStatus)
def rag_gather(body: RagGatherIn) -> RagStatus:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (SOL_RAG_ENABLED=false).")

    root = Path(body.path)
    if not _is_allowed_path(root):
        raise HTTPException(status_code=400, detail="Path is outside SOL_RAG_ALLOWED_ROOTS.")

    max_files = max(1, int(body.max_files))
    max_bytes = max(1, int(body.max_bytes))
    exts = {e.lower() for e in body.extensions}

    total_files = 0
    total_bytes = 0
    store = _store()

    for path in root.rglob("*"):
        if total_files >= max_files or total_bytes >= max_bytes:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        try:
            size = path.stat().st_size
        except Exception:
            continue
        if size <= 0:
            continue
        if total_bytes + size > max_bytes:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not text.strip():
            continue

        rel = str(path.relative_to(root))
        doc_id = hashlib.sha256(f"file:{str(path.resolve())}".encode("utf-8")).hexdigest()[:24]
        chunks = list(chunk_text(text, chunk_chars=config.rag_chunk_chars, overlap_chars=config.rag_chunk_overlap_chars))
        store.upsert_document(
            doc_id=doc_id,
            title=rel,
            source=f"file:{str(path.resolve())}",
            chunks=[(c.chunk_id, c.content) for c in chunks],
            meta={"kind": "file", "path": str(path.resolve()), "gather_root": str(root.resolve())},
        )

        total_files += 1
        total_bytes += size

    return rag_status()


@router.post("/rag/query", response_model=RagQueryOut)
def rag_query(body: RagQueryIn) -> RagQueryOut:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (SOL_RAG_ENABLED=false).")

    k = max(1, min(int(body.k), 20))
    hits = _store().query(body.query, k=k)
    return RagQueryOut(
        hits=[
            RagHitOut(
                doc_id=h.doc_id,
                chunk_id=h.chunk_id,
                title=h.title,
                source=h.source,
                snippet=h.snippet,
                content=h.content,
                score=h.score,
            )
            for h in hits
        ]
    )

