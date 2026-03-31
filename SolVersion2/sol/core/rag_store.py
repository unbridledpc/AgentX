from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class RagHit:
    doc_id: str
    chunk_id: str
    title: str
    source: str
    snippet: str
    content: str
    score: float | None = None
    meta: dict | None = None


class RagStore:
    """SQLite FTS-backed store (offline, dependency-free)."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                  doc_id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  source TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  meta_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                  content,
                  doc_id UNINDEXED,
                  chunk_id UNINDEXED,
                  title UNINDEXED,
                  source UNINDEXED
                )
                """
            )

    def upsert_document(
        self,
        *,
        doc_id: str,
        title: str,
        source: str,
        chunks: Iterable[tuple[str, str]],
        meta: dict,
    ) -> None:
        now = time.time()
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents(doc_id, title, source, created_at, updated_at, meta_json)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                  title=excluded.title,
                  source=excluded.source,
                  updated_at=excluded.updated_at,
                  meta_json=excluded.meta_json
                """,
                (doc_id, title, source, now, now, meta_json),
            )
            conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
            conn.executemany(
                "INSERT INTO chunks_fts(content, doc_id, chunk_id, title, source) VALUES(?, ?, ?, ?, ?)",
                [(content, doc_id, chunk_id, title, source) for (chunk_id, content) in chunks],
            )

    def stats(self) -> dict:
        with self._connect() as conn:
            doc_count = conn.execute("SELECT COUNT(1) AS n FROM documents").fetchone()["n"]
            chunk_count = conn.execute("SELECT COUNT(1) AS n FROM chunks_fts").fetchone()["n"]
        return {"doc_count": int(doc_count), "chunk_count": int(chunk_count)}

    def get_document_meta(self, doc_id: str) -> dict | None:
        if not doc_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT meta_json FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
            if not row or not row["meta_json"]:
                return None
            try:
                return json.loads(row["meta_json"])
            except Exception:
                return None

    def list_documents_meta(self, *, limit: int = 10_000) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, meta_json FROM documents LIMIT ?",
                (int(limit),),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            meta = None
            try:
                meta = json.loads(r["meta_json"]) if r["meta_json"] else {}
            except Exception:
                meta = {}
            out.append({"doc_id": r["doc_id"], "meta": meta})
        return out

    def query(self, query: str, *, k: int, mode: str = "or", min_token_len: int = 3) -> list[RagHit]:
        """Query FTS with explicit mode.

        - mode="and": requires all tokens
        - mode="or": any token
        Tokenization is sanitized to avoid FTS parser errors.
        """

        q = (query or "").strip()
        if not q:
            return []
        tokens = [t for t in re.findall(r"[A-Za-z0-9_]+", q) if len(t) >= int(min_token_len)]
        if not tokens:
            tokens = re.findall(r"[A-Za-z0-9_]+", q) or [q]
        joiner = " AND " if str(mode).lower() == "and" else " OR "
        fts_query = joiner.join(tokens)

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                      doc_id, chunk_id, title, source,
                      snippet(chunks_fts, 0, '[', ']', '...', 16) AS snippet,
                      bm25(chunks_fts) AS score,
                      content
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (fts_query, int(k)),
                ).fetchall()
                hits = [
                    RagHit(
                        doc_id=r["doc_id"],
                        chunk_id=r["chunk_id"],
                        title=r["title"],
                        source=r["source"],
                        snippet=r["snippet"],
                        content=r["content"],
                        score=float(r["score"]) if r["score"] is not None else None,
                    )
                    for r in rows
                ]
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT
                      doc_id, chunk_id, title, source,
                      snippet(chunks_fts, 0, '[', ']', '...', 16) AS snippet,
                      content
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    LIMIT ?
                    """,
                    (fts_query, int(k)),
                ).fetchall()
                hits = [
                    RagHit(
                        doc_id=r["doc_id"],
                        chunk_id=r["chunk_id"],
                        title=r["title"],
                        source=r["source"],
                        snippet=r["snippet"],
                        content=r["content"],
                        score=None,
                    )
                    for r in rows
                ]

            # Attach document meta (best-effort).
            for h in hits:
                h.meta = self.get_document_meta(h.doc_id)
            return hits

    def query_tiered(self, query: str, *, k: int, min_token_len: int = 3) -> list[RagHit]:
        """Tiered retrieval strategy:

        A) AND match across tokens
        B) if results < desired_k/2, fall back to OR and merge
        """

        k = max(1, int(k))
        primary = self.query(query, k=k, mode="and", min_token_len=min_token_len)
        want_min = max(1, k // 2)
        if len(primary) >= want_min:
            return primary

        secondary = self.query(query, k=k, mode="or", min_token_len=min_token_len)
        seen: set[tuple[str, str]] = {(h.doc_id, h.chunk_id) for h in primary}
        merged = list(primary)
        for h in secondary:
            key = (h.doc_id, h.chunk_id)
            if key in seen:
                continue
            merged.append(h)
            seen.add(key)
            if len(merged) >= k:
                break
        return merged
