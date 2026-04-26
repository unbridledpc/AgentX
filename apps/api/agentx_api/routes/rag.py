from __future__ import annotations

import hashlib
import os
import re
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from agentx_api.config import config
from agentx_api.rag.chunking import chunk_text
from agentx_api.rag.store import RagStore
from agentx_api.web_access.errors import WebAccessDenied, WebFetchError
from agentx_api.web_access.fetch import fetch_text
from agentx_api.web_access.policy import WebPolicy

router = APIRouter(tags=["rag"])


def _store() -> RagStore:
    return RagStore(config.rag_db_path)


def _web_policy() -> WebPolicy:
    return WebPolicy(
        enabled=config.web_enabled,
        allow_all_hosts=config.web_allow_all_hosts,
        allowed_host_suffixes=tuple(config.web_allowed_hosts),
        block_private_networks=config.web_block_private_networks,
        timeout_s=config.web_timeout_s,
        max_bytes=config.web_max_bytes,
        user_agent=config.web_user_agent,
        max_redirects=config.web_max_redirects,
        max_search_results=config.web_max_search_results,
    )


def _clean_title(value: str | None, fallback: str) -> str:
    raw = (value or "").strip() or fallback
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:160] or "Untitled"


def _title_from_text(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        cleaned = _clean_title(line, "")
        if 4 <= len(cleaned) <= 160:
            return cleaned
    return fallback


class RagStatus(BaseModel):
    enabled: bool
    db_path: str
    doc_count: int
    chunk_count: int


class RagSourceOut(BaseModel):
    doc_id: str
    title: str
    source: str
    created_at: float
    updated_at: float
    chunk_count: int
    meta: dict[str, Any] = Field(default_factory=dict)


class RagSourcesOut(BaseModel):
    ok: bool = True
    sources: list[RagSourceOut]


class RagIngestResult(BaseModel):
    ok: bool = True
    doc_id: str
    title: str
    source: str
    chunks: int
    chars: int
    truncated: bool = False
    status: RagStatus


class RagUrlIn(BaseModel):
    url: str = Field(..., min_length=8)
    title: str | None = None
    collection: str = "Web"
    tags: list[str] = Field(default_factory=list)
    max_chars: int = 200_000


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
    extensions: list[str] = Field(default_factory=lambda: [".txt", ".md", ".json", ".py", ".ps1", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".toml", ".xml", ".lua"])
    collection: str = "Local Files"
    tags: list[str] = Field(default_factory=list)


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




@router.get("/rag/sources", response_model=RagSourcesOut)
def rag_sources(limit: int = 100, query: str | None = None) -> RagSourcesOut:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (AGENTX_RAG_ENABLED=false).")
    docs = _store().list_documents(limit=limit, query=query)
    return RagSourcesOut(
        sources=[
            RagSourceOut(
                doc_id=d.doc_id,
                title=d.title,
                source=d.source,
                created_at=d.created_at,
                updated_at=d.updated_at,
                chunk_count=d.chunk_count,
                meta=d.meta,
            )
            for d in docs
        ]
    )


@router.delete("/rag/sources/{doc_id}")
def rag_delete_source(doc_id: str) -> dict[str, Any]:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (AGENTX_RAG_ENABLED=false).")
    deleted = _store().delete_document(doc_id)
    return {"ok": True, "deleted": deleted, "status": rag_status().model_dump()}


@router.post("/rag/url", response_model=RagIngestResult)
def rag_ingest_url(body: RagUrlIn) -> RagIngestResult:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (AGENTX_RAG_ENABLED=false).")
    try:
        fetched = fetch_text(body.url, policy=_web_policy())
    except WebAccessDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except WebFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))

    text = (fetched.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Fetched page did not contain readable text.")
    max_chars = max(1000, min(int(body.max_chars), 1_000_000))
    truncated_by_request = len(text) > max_chars
    if truncated_by_request:
        text = text[:max_chars]

    parsed = urlparse(fetched.url or body.url)
    fallback_title = parsed.netloc + parsed.path if parsed.netloc else body.url
    title = _clean_title(body.title, _title_from_text(text, fallback_title))
    doc_id = hashlib.sha256(f"url:{fetched.url}".encode("utf-8")).hexdigest()[:24]
    chunks = list(chunk_text(text, chunk_chars=config.rag_chunk_chars, overlap_chars=config.rag_chunk_overlap_chars))
    meta = {
        "kind": "url",
        "url": fetched.url,
        "requested_url": body.url,
        "collection": body.collection.strip() or "Web",
        "tags": [str(t).strip() for t in body.tags if str(t).strip()],
        "content_type": fetched.content_type,
        "fetched_at": fetched.ts,
        "truncated": bool(fetched.truncated or truncated_by_request),
    }
    _store().upsert_document(
        doc_id=doc_id,
        title=title,
        source=f"url:{fetched.url}",
        chunks=[(c.chunk_id, c.content) for c in chunks],
        meta=meta,
    )
    return RagIngestResult(
        doc_id=doc_id,
        title=title,
        source=f"url:{fetched.url}",
        chunks=len(chunks),
        chars=len(text),
        truncated=bool(fetched.truncated or truncated_by_request),
        status=rag_status(),
    )


@router.post("/rag/doc", response_model=RagStatus)
def rag_upsert_doc(body: RagDocIn) -> RagStatus:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (AGENTX_RAG_ENABLED=false).")

    doc_id = body.doc_id or hashlib.sha256(f"{body.source}:{body.title}:{len(body.text)}".encode("utf-8")).hexdigest()[:24]
    chunks = list(chunk_text(body.text, chunk_chars=config.rag_chunk_chars, overlap_chars=config.rag_chunk_overlap_chars))
    _store().upsert_document(
        doc_id=doc_id,
        title=body.title,
        source=body.source,
        chunks=[(c.chunk_id, c.content) for c in chunks],
        meta={**body.meta, "collection": body.meta.get("collection", "Manual") if isinstance(body.meta, dict) else "Manual"},
    )
    return rag_status()


@router.post("/rag/gather", response_model=RagStatus)
def rag_gather(body: RagGatherIn) -> RagStatus:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (AGENTX_RAG_ENABLED=false).")

    root = Path(body.path)
    if not _is_allowed_path(root):
        raise HTTPException(status_code=400, detail="Path is outside AGENTX_RAG_ALLOWED_ROOTS.")

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
            meta={"kind": "file", "path": str(path.resolve()), "gather_root": str(root.resolve()), "collection": body.collection.strip() or "Local Files", "tags": [str(t).strip() for t in body.tags if str(t).strip()]},
        )

        total_files += 1
        total_bytes += size

    return rag_status()


@router.post("/rag/folder", response_model=RagStatus)
def rag_ingest_folder(body: RagGatherIn) -> RagStatus:
    return rag_gather(body)


@router.post("/rag/query", response_model=RagQueryOut)
def rag_query(body: RagQueryIn) -> RagQueryOut:
    if not config.rag_enabled:
        raise HTTPException(status_code=400, detail="RAG is disabled (AGENTX_RAG_ENABLED=false).")

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

