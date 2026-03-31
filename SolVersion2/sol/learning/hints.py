from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from sol.config import SolConfig


def _tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in re.finditer(r"[a-zA-Z0-9_.-]{3,}", text or "")}


@dataclass(frozen=True)
class ReflectionHint:
    failure_signature: str
    category: str
    strategy: str
    confidence: float
    reusable: bool
    tool_name: str | None = None


@dataclass(frozen=True)
class HintRecord:
    hint_id: str
    created_at: float
    updated_at: float
    status: str  # observation | promoted
    failure_signature: str
    category: str
    tool_name: str | None
    strategy: str
    confidence: float
    occurrence_count: int
    promoted_count: int


class HintStore:
    def __init__(self, *, cfg: SolConfig, runtime_paths) -> None:
        self.cfg = cfg
        self.runtime_paths = runtime_paths
        self.path: Path = runtime_paths.learned_hints_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_hints(self) -> list[HintRecord]:
        if not self.path.exists():
            return []
        out: list[HintRecord] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                out.append(HintRecord(**raw))
            except Exception:
                continue
        return out

    def query(self, *, goal: str, tool_names: list[str] | None = None, limit: int = 5) -> list[HintRecord]:
        wanted_tools = {str(t).lower() for t in (tool_names or []) if str(t).strip()}
        goal_tokens = _tokenize(goal)
        scored: list[tuple[float, HintRecord]] = []
        for rec in self.list_hints():
            if rec.status != "promoted":
                continue
            score = rec.confidence + min(float(rec.occurrence_count) * 0.05, 0.3)
            if wanted_tools and rec.tool_name and rec.tool_name.lower() in wanted_tools:
                score += 0.4
            if goal_tokens and (_tokenize(rec.strategy) & goal_tokens):
                score += 0.2
            scored.append((score, rec))
        scored.sort(key=lambda item: (-item[0], -item[1].occurrence_count, item[1].hint_id))
        return [rec for _, rec in scored[: max(1, min(limit, 20))]]

    def consider_reflection(self, hint: ReflectionHint) -> HintRecord | None:
        if not hint.reusable or hint.confidence < 0.65:
            return None
        existing = {rec.failure_signature: rec for rec in self.list_hints()}
        now = time.time()
        prev = existing.get(hint.failure_signature)
        occurrence_count = (prev.occurrence_count if prev else 0) + 1
        avg_confidence = hint.confidence if prev is None else (prev.confidence + hint.confidence) / 2.0
        status = "promoted" if occurrence_count >= 2 and avg_confidence >= 0.75 else "observation"
        rec = HintRecord(
            hint_id=prev.hint_id if prev else hashlib.sha256(hint.failure_signature.encode("utf-8")).hexdigest()[:16],
            created_at=prev.created_at if prev else now,
            updated_at=now,
            status=status,
            failure_signature=hint.failure_signature,
            category=hint.category,
            tool_name=hint.tool_name,
            strategy=hint.strategy,
            confidence=avg_confidence,
            occurrence_count=occurrence_count,
            promoted_count=(prev.promoted_count if prev else 0) + (1 if status == "promoted" and (prev is None or prev.status != "promoted") else 0),
        )
        records = existing
        records[rec.failure_signature] = rec
        self._write_all(list(records.values()))
        return rec

    def _write_all(self, records: list[HintRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        lines = [json.dumps(asdict(rec), ensure_ascii=False, sort_keys=True) for rec in sorted(records, key=lambda r: r.failure_signature)]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(self.path)
