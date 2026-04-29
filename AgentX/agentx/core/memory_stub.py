from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentx.config import AgentXConfig
from agentx.core.memory import MemoryChunk


@dataclass(frozen=True)
class MemoryRecord:
    ts: float
    user_message: str
    plan: dict[str, Any]
    outcome: dict[str, Any]
    tags: list[str]


class MemoryStub:
    """Minimal memory hook (append-only JSONL).

    This is intentionally NOT a vector DB. It records:
    - user message
    - plan (tool steps)
    - outcome (success + summary)
    - tags: trusted:user | untrusted:web

    TODO (next slices):
    - Replace/augment this with RAG ingestion + retrieval.
    - Store web sources separately with citation metadata.
    - Add a UI viewer for recent memory/audit entries.
    """

    def __init__(self, cfg: AgentXConfig):
        self.cfg = cfg
        self.path = cfg.paths.data_dir / "memory_stub.jsonl"

    def ensure_writable(self) -> tuple[bool, str | None]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8"):
                pass
            return True, None
        except Exception as e:
            return False, str(e)

    def append(self, record: MemoryRecord) -> tuple[bool, str | None]:
        payload = {
            "ts": record.ts,
            "user_message": record.user_message,
            "plan": record.plan,
            "outcome": record.outcome,
            "tags": record.tags,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.open("a", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False) + "\n")
            return True, None
        except Exception as e:
            return False, str(e)

    # Memory interface (stub) -------------------------------------------
    def add_event(self, role: str, content: str, tags: list[str], meta: dict[str, Any] | None = None) -> None:
        self.record(
            user_message=f"{role}: {content}",
            plan={},
            outcome={"meta": meta or {}},
            tags=tags or [],
        )

    def ingest_text(self, source_id: str, text: str, tags: list[str], meta: dict[str, Any] | None = None) -> dict[str, Any]:
        self.record(
            user_message=f"ingest_text:{source_id}",
            plan={},
            outcome={"bytes": len((text or "").encode("utf-8", errors="ignore")), "meta": meta or {}},
            tags=tags or [],
        )
        return {"ok": True, "stub": True}

    def ingest_path(self, path: str, tags: list[str], meta: dict[str, Any] | None = None, *, recursive: bool = True, max_files: int = 200) -> dict[str, Any]:
        self.record(
            user_message=f"ingest_path:{path}",
            plan={},
            outcome={"recursive": bool(recursive), "max_files": int(max_files), "meta": meta or {}},
            tags=tags or [],
        )
        return {"ok": True, "stub": True}

    def retrieve(self, query: str, k: int = 8, tags_filter: list[str] | None = None) -> list[MemoryChunk]:
        return []

    def add_project_memory(self, **kwargs):
        raise RuntimeError("Memory is disabled.")

    def ingest_project_raw(self, **kwargs):
        raise RuntimeError("Memory is disabled.")

    def retrieve_project_memory(self, *args, **kwargs):
        return []

    def project_context_stack(self, **kwargs):
        return {"global": [], "module": [], "files": [], "task": []}

    def list_project_memory(self, **kwargs):
        return []

    def record(
        self,
        *,
        user_message: str,
        plan: dict[str, Any],
        outcome: dict[str, Any],
        tags: list[str],
    ) -> tuple[bool, str | None]:
        return self.append(
            MemoryRecord(
                ts=time.time(),
                user_message=user_message,
                plan=plan,
                outcome=outcome,
                tags=tags,
            )
        )
