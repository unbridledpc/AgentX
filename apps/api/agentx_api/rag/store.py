from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RagDocument:
    doc_id: str
    title: str
    source: str
    created_at: float
    updated_at: float
    meta: dict
    chunk_count: int


@dataclass(frozen=True)
class RagHit:
    doc_id: str
    chunk_id: str
    title: str
    source: str
    snippet: str
    content: str
    score: float | None = None


class RagStore:
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
            # FTS5 virtual table for chunk search. Works offline and avoids extra dependencies.
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

    def upsert_document(self, *, doc_id: str, title: str, source: str, chunks: Iterable[tuple[str, str]], meta: dict) -> None:
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
            # Replace chunks for doc_id by deleting then inserting.
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


    def list_documents(self, *, limit: int = 100, query: str | None = None) -> list[RagDocument]:
        limit = max(1, min(int(limit), 500))
        q = (query or "").strip().lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.doc_id, d.title, d.source, d.created_at, d.updated_at, d.meta_json,
                       COUNT(c.chunk_id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks_fts c ON c.doc_id = d.doc_id
                GROUP BY d.doc_id
                ORDER BY d.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        docs: list[RagDocument] = []
        for r in rows:
            try:
                meta = json.loads(r["meta_json"] or "{}")
            except Exception:
                meta = {}
            if q:
                haystack = " ".join([
                    str(r["title"] or ""),
                    str(r["source"] or ""),
                    json.dumps(meta, ensure_ascii=False),
                ]).lower()
                if q not in haystack:
                    continue
            docs.append(
                RagDocument(
                    doc_id=str(r["doc_id"]),
                    title=str(r["title"]),
                    source=str(r["source"]),
                    created_at=float(r["created_at"]),
                    updated_at=float(r["updated_at"]),
                    meta=meta if isinstance(meta, dict) else {},
                    chunk_count=int(r["chunk_count"] or 0),
                )
            )
        return docs

    def delete_document(self, doc_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM chunks_fts WHERE doc_id = ?", (doc_id,))
            return cur.rowcount > 0

    def query(self, query: str, *, k: int) -> list[RagHit]:
        q = (query or "").strip()
        if not q:
            return []
        # FTS query: simple user text -> tokens joined with AND for better precision.
        tokens = [t for t in q.replace("\n", " ").split(" ") if t.strip()]
        fts_query = " AND ".join(tokens) if tokens else q

        with self._connect() as conn:
            # bm25() is available on FTS5 builds; fall back to no score if unavailable.
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
                return [
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
                return [
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

