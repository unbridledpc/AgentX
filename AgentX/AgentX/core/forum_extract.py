from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any


_DROP_TAGS = {"script", "style", "noscript", "svg"}
_STRUCT_BREAK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


def _norm_ws(s: str) -> str:
    s = unescape(s or "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _norm_final(s: str) -> str:
    """Normalize extracted output without touching code block spacing."""
    s = unescape(s or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


_OTLAND_DROP_PHRASES = (
    "there is no official otland's discord server",
    "you are using an out of date browser",
)

_NAV_TOKENS = {
    "home",
    "forums",
    "members",
    "search",
    "whats",
    "what's",
    "new",
    "log",
    "in",
    "register",
    "help",
    "contact",
    "privacy",
    "terms",
    "rules",
    "cookie",
    "cookies",
    "toggle",
    "navigation",
}


def _looks_like_nav_line(line: str) -> bool:
    # Heuristic: drop short lines dominated by XenForo navigation tokens.
    s = (line or "").strip()
    if not s or len(s) > 140:
        return False
    # Avoid removing normal prose or bullet points.
    if any(ch in s for ch in (".", ":", ";", "?", "!", "(", ")")):
        return False
    tokens = [t.casefold() for t in re.findall(r"[A-Za-z']+", s)]
    if len(tokens) < 3:
        return False
    nav_hits = sum(1 for t in tokens if t in _NAV_TOKENS)
    return nav_hits >= 3 and (nav_hits / max(1, len(tokens))) >= 0.8


def _clean_otland_text_block(text: str) -> str:
    """Remove common OTland boilerplate while preserving code segments elsewhere."""
    if not text:
        return ""
    out_lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            out_lines.append("")
            continue
        low = line.casefold()
        if any(p in low for p in _OTLAND_DROP_PHRASES):
            continue
        if _looks_like_nav_line(line):
            continue
        out_lines.append(raw)
    return _norm_ws("\n".join(out_lines))


@dataclass
class _Segment:
    kind: str  # "text" | "code"
    content: str


class _ForumExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._segments: list[_Segment] = []
        self._text_buf: list[str] = []
        self._code_buf: list[str] = []
        self._skip_depth = 0
        self._skip_stack: list[bool] = []
        self._in_code = 0
        self._in_title = False
        self._title_buf: list[str] = []

    def _flush_text(self) -> None:
        if not self._text_buf:
            return
        raw = "".join(self._text_buf)
        self._text_buf = []
        t = _norm_ws(raw)
        if t:
            self._segments.append(_Segment(kind="text", content=t))

    def _flush_code(self) -> None:
        if not self._code_buf:
            return
        raw = "".join(self._code_buf)
        self._code_buf = []
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        raw = raw.strip("\n")
        if raw:
            self._segments.append(_Segment(kind="code", content=raw))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = (tag or "").lower()
        attrs_d = {k.lower(): (v or "") for (k, v) in attrs}
        cls = (attrs_d.get("class") or "").lower()
        el_id = (attrs_d.get("id") or "").lower()

        if tag_l == "title":
            self._in_title = True

        skip_here = False
        if tag_l in _DROP_TAGS:
            skip_here = True
        if tag_l in {"nav", "aside", "footer", "header", "form"}:
            skip_here = True
        if any(k in cls for k in ("nav", "navbar", "sidebar", "menu", "toc", "footer", "header", "ads", "advert", "cookie", "masthead", "breadcrumb")):
            skip_here = True
        if any(k in el_id for k in ("nav", "sidebar", "menu", "toc", "footer", "header", "ads", "cookie", "breadcrumb")):
            skip_here = True

        self._skip_stack.append(skip_here)
        if skip_here:
            self._skip_depth += 1

        if self._skip_depth == 0 and tag_l in _STRUCT_BREAK_TAGS:
            # Avoid inserting break markers inside code blocks.
            if self._in_code <= 0:
                self._text_buf.append("\n")

        if self._skip_depth == 0 and tag_l in {"pre", "code"}:
            self._flush_text()
            self._in_code += 1

    def handle_endtag(self, tag: str) -> None:
        tag_l = (tag or "").lower()
        if tag_l == "title":
            self._in_title = False

        if self._skip_depth == 0 and tag_l in _STRUCT_BREAK_TAGS:
            if self._in_code <= 0:
                self._text_buf.append("\n")

        if self._skip_depth == 0 and tag_l in {"pre", "code"} and self._in_code > 0:
            self._in_code -= 1
            if self._in_code == 0:
                self._flush_code()

        if self._skip_stack:
            skip_here = self._skip_stack.pop()
            if skip_here and self._skip_depth > 0:
                self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._in_title:
            self._title_buf.append(data)
        if self._skip_depth > 0:
            return
        if self._in_code > 0:
            self._code_buf.append(data)
        else:
            self._text_buf.append(data)

    def title(self) -> str | None:
        t = _norm_ws("".join(self._title_buf))
        return t or None

    def finish(self) -> tuple[str, dict[str, Any]]:
        if self._in_code > 0:
            self._flush_code()
        self._flush_text()

        parts: list[str] = []
        code_blocks = 0
        removed_otland_boilerplate = 0
        for seg in self._segments:
            if seg.kind == "code":
                code_blocks += 1
                parts.append("```")
                parts.append(seg.content)
                parts.append("```")
            else:
                cleaned = _clean_otland_text_block(seg.content)
                if not cleaned.strip() and seg.content.strip():
                    removed_otland_boilerplate += 1
                if cleaned.strip():
                    parts.append(cleaned)
        text = _norm_final("\n\n".join([p for p in parts if p and p.strip()]))
        meta = {
            "title": self.title(),
            "extracted_with": "stdlib:forum_extract",
            "code_blocks": int(code_blocks),
            "removed_otland_boilerplate_segments": int(removed_otland_boilerplate),
        }
        return text, meta


def extract_forum_text_and_meta(html: str) -> tuple[str, dict[str, Any]]:
    """Extract forum/thread-like text while preserving <pre>/<code> blocks.

    Best-effort, stdlib-only:
    - Drops scripts/styles and common nav/aside/footer/header containers
    - Preserves code blocks as fenced triple-backticks
    """
    parser = _ForumExtractor()
    try:
        parser.feed(html or "")
    except Exception:
        # Best-effort fallback: return normalized raw HTML.
        return _norm_ws(html or ""), {"title": None, "extracted_with": "fallback:raw", "code_blocks": 0}
    return parser.finish()
