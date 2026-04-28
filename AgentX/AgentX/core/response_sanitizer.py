from __future__ import annotations

import re


_THINK_BLOCK_RE = re.compile(r"(?is)<think\b[^>]*>.*?</think>")
_THINK_TAG_RE = re.compile(r"(?is)</?think\b[^>]*>")
_MARKDOWN_FENCE_RE = re.compile(r"```+")
_MARKDOWN_INLINE_RE = re.compile(r"`([^`]*)`")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET_PREFIX_RE = re.compile(r"^\s*[-*+]\s+")
_ORDERED_PREFIX_RE = re.compile(r"^\s*\d+\.\s+")
_INLINE_BULLET_RE = re.compile(r"\s[-*+]\s+")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

_LEADING_LINE_PATTERNS = (
    re.compile(r"^\s*i need to\b.*$", re.IGNORECASE),
    re.compile(r"^\s*the user said\b.*$", re.IGNORECASE),
    re.compile(r"^\s*we need to\b.*$", re.IGNORECASE),
    re.compile(r"^\s*let me think\b.*$", re.IGNORECASE),
    re.compile(r"^\s*i should\b.*$", re.IGNORECASE),
    re.compile(r"^\s*the correct response is\b.*$", re.IGNORECASE),
)

_LEADING_PREFIX_REWRITES = (
    re.compile(r"^\s*the correct response is\s*:?\s*", re.IGNORECASE),
    re.compile(r"^\s*the answer is\s*:?\s*", re.IGNORECASE),
    re.compile(r"^\s*here(?:'s| is)\s+(?:the answer|a concise answer)\s*:?\s*", re.IGNORECASE),
    re.compile(r"^\s*let me think(?:\s+through)?\s*:?\s*", re.IGNORECASE),
)

_SPOKEN_SETUP_REWRITES = (
    re.compile(r"^\s*(?:sure|okay|ok|alright|well)[,.!\s]+", re.IGNORECASE),
    re.compile(r"^\s*here(?:'s| is)\s+(?:the answer|the response|a concise answer)\s*:?\s*", re.IGNORECASE),
    re.compile(r"^\s*as agentx[,.!\s]+", re.IGNORECASE),
    re.compile(r"^\s*here(?:'s| is)\s*", re.IGNORECASE),
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def sanitize_assistant_response(text: str) -> str:
    """Clean assistant output while preserving markdown/code formatting.

    Chat mode must not strip indentation or collapse all whitespace because that
    breaks generated code blocks and saved scripts. Spoken mode performs its own
    aggressive cleanup later.
    """
    cleaned = _THINK_BLOCK_RE.sub(" ", text or "")
    cleaned = _THINK_TAG_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _strip_leading_meta_lines(cleaned)
    cleaned = _strip_leading_meta_prefixes(cleaned)

    lines = [line.rstrip() for line in cleaned.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    cleaned = "\n".join(lines)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def finalize_response_text(text: str, *, response_mode: str = "chat") -> str:
    mode = (response_mode or "chat").strip().lower()
    cleaned = sanitize_assistant_response(text)
    if mode != "spoken":
        return cleaned
    spoken = _cleanup_spoken_text(cleaned)
    return spoken or "I'm here."


def _strip_leading_meta_lines(text: str) -> str:
    lines = text.split("\n")
    while lines and _looks_like_meta_line(lines[0]):
        lines.pop(0)
    return "\n".join(lines)


def _looks_like_meta_line(line: str) -> bool:
    trimmed = (line or "").strip()
    if not trimmed:
        return True
    return any(pattern.match(trimmed) for pattern in _LEADING_LINE_PATTERNS)


def _strip_leading_meta_prefixes(text: str) -> str:
    cleaned = (text or "").lstrip()
    changed = True
    while cleaned and changed:
        changed = False
        for pattern in _LEADING_PREFIX_REWRITES:
            next_text, count = pattern.subn("", cleaned, count=1)
            if count:
                cleaned = next_text.lstrip()
                changed = True
    return cleaned


def _cleanup_spoken_text(text: str) -> str:
    cleaned = _MARKDOWN_FENCE_RE.sub(" ", text)
    cleaned = _MARKDOWN_INLINE_RE.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_HEADING_RE.sub("", cleaned)
    spoken_lines: list[str] = []
    for raw_line in cleaned.split("\n"):
        line = _BULLET_PREFIX_RE.sub("", raw_line)
        line = _ORDERED_PREFIX_RE.sub("", line)
        spoken_lines.append(line.strip())
    cleaned = " ".join(part for part in spoken_lines if part)
    cleaned = _INLINE_BULLET_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    for pattern in _SPOKEN_SETUP_REWRITES:
        cleaned = pattern.sub("", cleaned, count=1).strip()
    if not cleaned:
        return ""
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
    if parts:
        cleaned = " ".join(parts[:3]).strip()
    if len(cleaned) > 320:
        cleaned = cleaned[:320].rstrip(" ,;:-")
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
    return cleaned.strip()
