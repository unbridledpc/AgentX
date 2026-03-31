from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    content: str


def chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> Iterable[Chunk]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    if chunk_chars <= 0:
        return [Chunk(chunk_id="0", content=cleaned)]

    overlap = max(0, min(overlap_chars, max(0, chunk_chars - 1)))
    step = max(1, chunk_chars - overlap)

    chunks: list[Chunk] = []
    i = 0
    idx = 0
    while i < len(cleaned):
        piece = cleaned[i : i + chunk_chars].strip()
        if piece:
            chunks.append(Chunk(chunk_id=str(idx), content=piece))
            idx += 1
        i += step
    return chunks

