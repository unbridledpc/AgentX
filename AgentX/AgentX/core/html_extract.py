from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any


_DROP_TAGS = {"script", "style", "noscript", "svg"}
_STRUCT_BREAK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
_MAIN_TAGS = {"main", "article"}


def _norm_ws(s: str) -> str:
    s = unescape(s or "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _looks_like_junk(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in {"navigation", "contents", "table of contents"}:
        return True
    if len(t) < 20 and any(k in t for k in ("cookies", "privacy", "terms", "sign in", "log in")):
        return True
    return False


class _MetaExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = (tag or "").lower()
        attrs_d = {k.lower(): (v or "") for (k, v) in attrs}
        if tag_l == "title":
            self._in_title = True
        if tag_l == "meta":
            name = (attrs_d.get("name") or attrs_d.get("property") or "").strip().lower()
            content = (attrs_d.get("content") or "").strip()
            if name and content:
                self.meta[name] = content

    def handle_endtag(self, tag: str) -> None:
        if (tag or "").lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data:
            self._title_parts.append(data)

    def title(self) -> str | None:
        t = _norm_ws("".join(self._title_parts))
        return t or None


class _SectionExtractor(HTMLParser):
    """Extract readable text, optionally focusing only within <main>/<article> blocks."""

    def __init__(self, *, focus_main: bool) -> None:
        super().__init__()
        self.focus_main = bool(focus_main)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._skip_stack: list[bool] = []
        self._focus_depth = 0
        self._main_seen = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = (tag or "").lower()
        attrs_d = {k.lower(): (v or "") for (k, v) in attrs}
        cls = (attrs_d.get("class") or "").lower()
        el_id = (attrs_d.get("id") or "").lower()

        if tag_l in _MAIN_TAGS:
            self._main_seen = True
            self._focus_depth += 1

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
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_l = (tag or "").lower()
        if tag_l in _MAIN_TAGS and self._focus_depth > 0:
            self._focus_depth -= 1
        if self._skip_depth == 0 and tag_l in _STRUCT_BREAK_TAGS:
            self._chunks.append("\n")
        if self._skip_stack:
            skip_here = self._skip_stack.pop()
            if skip_here and self._skip_depth > 0:
                self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self.focus_main and self._main_seen and self._focus_depth <= 0:
            return
        if not data:
            return
        self._chunks.append(data)

    def text(self) -> str:
        return _norm_ws("".join(self._chunks))


class _ReadableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._skip_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = (tag or "").lower()
        attrs_d = {k.lower(): (v or "") for (k, v) in attrs}
        cls = (attrs_d.get("class") or "").lower()
        el_id = (attrs_d.get("id") or "").lower()

        skip_here = False
        if tag_l in _DROP_TAGS:
            skip_here = True
        if tag_l in {"nav", "aside", "footer", "header"}:
            skip_here = True
        if any(k in cls for k in ("nav", "navbar", "sidebar", "menu", "toc", "footer", "header", "ads", "advert", "cookie", "masthead")):
            skip_here = True
        if any(k in el_id for k in ("nav", "sidebar", "menu", "toc", "footer", "header", "ads", "cookie")):
            skip_here = True

        self._skip_stack.append(skip_here)
        if skip_here:
            self._skip_depth += 1

        if self._skip_depth == 0 and tag_l in _STRUCT_BREAK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_l = (tag or "").lower()
        if self._skip_depth == 0 and tag_l in _STRUCT_BREAK_TAGS:
            self._chunks.append("\n")
        if self._skip_stack:
            skip_here = self._skip_stack.pop()
            if skip_here and self._skip_depth > 0:
                self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if not data:
            return
        self._chunks.append(data)

    def text(self) -> str:
        return _norm_ws("".join(self._chunks))


def extract_readable_text(html: str) -> str:
    """Extract readable text from HTML using stdlib-only heuristics.

    - Drops script/style/noscript blocks
    - Drops common nav/aside/footer/header containers
    - Normalizes whitespace and keeps paragraph-ish breaks
    """

    # Prefer focusing on <main>/<article> if present; fall back to general heuristics.
    out_main = ""
    try:
        main_parser = _SectionExtractor(focus_main=True)
        main_parser.feed(html or "")
        out_main = main_parser.text()
    except Exception:
        out_main = ""

    parser = _ReadableExtractor()
    try:
        parser.feed(html or "")
    except Exception:
        return _norm_ws(html or "")
    out = out_main if out_main and len(out_main) >= 200 else parser.text()
    # Remove obviously junky leading lines.
    lines = [ln.strip() for ln in out.splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if not ln:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        if not cleaned and _looks_like_junk(ln):
            continue
        cleaned.append(ln)
    return _norm_ws("\n".join(cleaned))


def extract_text_and_meta(html: str) -> tuple[str, dict[str, Any]]:
    """Extract main text + basic metadata from HTML (stdlib-only)."""

    meta = {}
    try:
        mp = _MetaExtractor()
        mp.feed(html or "")
        title = mp.title() or (mp.meta.get("og:title") if mp.meta else None)
        byline = mp.meta.get("author") if mp.meta else None
        if not byline and mp.meta:
            byline = mp.meta.get("article:author") or mp.meta.get("og:article:author")
        published = None
        if mp.meta:
            published = mp.meta.get("article:published_time") or mp.meta.get("og:published_time") or mp.meta.get("published_time")
        meta = {
            "title": _norm_ws(title) if title else None,
            "byline": _norm_ws(byline) if byline else None,
            "published_time": _norm_ws(published) if published else None,
            "extracted_with": "stdlib:html_extract",
        }
    except Exception:
        meta = {"title": None, "byline": None, "published_time": None, "extracted_with": "stdlib:html_extract"}

    text = extract_readable_text(html or "")
    blocks = [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]
    if blocks and len(blocks) >= 3:
        best = max(blocks, key=lambda b: len(b.split()))
        if len(best.split()) >= 80 and len(best) >= 600:
            text = best.strip()

    words = re.findall(r"[A-Za-z0-9_]+", text or "")
    meta["word_count"] = int(len(words))
    return text, meta


@dataclass(frozen=True)
class TibiaMonsterExtraction:
    name: str | None
    url: str
    description: str | None
    attributes: dict[str, str]
    loot: list[str]
    abilities: list[str]
    raw_text: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "attributes": dict(self.attributes),
            "loot": list(self.loot),
            "abilities": list(self.abilities),
            "raw_text": self.raw_text,
            "confidence": float(self.confidence),
        }


class _TibiaMonsterParser(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.name: str | None = None
        self._in_h1 = False
        self._h1_parts: list[str] = []

        self._current_heading: str | None = None
        self._in_heading = False
        self._heading_parts: list[str] = []

        self._in_p = False
        self._p_parts: list[str] = []
        self._paras: list[str] = []

        # Table parsing (fallback).
        self._in_tr = False
        self._in_th = False
        self._in_td = False
        self._th_parts: list[str] = []
        self._td_parts: list[str] = []
        self.attributes: dict[str, str] = {}

        # Portable infobox parsing (Fandom).
        self._in_pi_data = False
        self._in_pi_label = False
        self._in_pi_value = False
        self._pi_label_parts: list[str] = []
        self._pi_value_parts: list[str] = []

        self.loot: list[str] = []
        self.abilities: list[str] = []
        self._in_li = False
        self._li_parts: list[str] = []

        # Reuse readable extraction as a fallback for raw_text.
        self.raw_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = (tag or "").lower()
        attrs_d = {k.lower(): (v or "") for (k, v) in attrs}
        cls = (attrs_d.get("class") or "").lower()

        if tag_l == "h1":
            self._in_h1 = True
            self._h1_parts = []

        if tag_l in {"h2", "h3"}:
            self._in_heading = True
            self._heading_parts = []

        if tag_l == "p":
            self._in_p = True
            self._p_parts = []

        if tag_l == "tr":
            self._in_tr = True
            self._th_parts = []
            self._td_parts = []

        if self._in_tr and tag_l == "th":
            self._in_th = True
        if self._in_tr and tag_l == "td":
            self._in_td = True

        if "pi-data" in cls:
            self._in_pi_data = True
            self._pi_label_parts = []
            self._pi_value_parts = []
        if self._in_pi_data and "pi-data-label" in cls:
            self._in_pi_label = True
        if self._in_pi_data and "pi-data-value" in cls:
            self._in_pi_value = True

        if tag_l == "li":
            self._in_li = True
            self._li_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag_l = (tag or "").lower()

        if tag_l == "h1" and self._in_h1:
            self._in_h1 = False
            name = _norm_ws("".join(self._h1_parts))
            if name:
                self.name = name
            self._h1_parts = []

        if tag_l in {"h2", "h3"} and self._in_heading:
            self._in_heading = False
            heading = _norm_ws("".join(self._heading_parts))
            self._heading_parts = []
            if heading:
                self._current_heading = heading.lower()

        if tag_l == "p" and self._in_p:
            self._in_p = False
            para = _norm_ws("".join(self._p_parts))
            self._p_parts = []
            if para and not _looks_like_junk(para):
                self._paras.append(para)

        if tag_l == "th":
            self._in_th = False
        if tag_l == "td":
            self._in_td = False
        if tag_l == "tr" and self._in_tr:
            self._in_tr = False
            k = _norm_ws("".join(self._th_parts))
            v = _norm_ws("".join(self._td_parts))
            self._th_parts = []
            self._td_parts = []
            if k and v and len(k) <= 80 and len(v) <= 400:
                # Avoid overwriting a key we already captured.
                self.attributes.setdefault(k, v)

        if tag_l == "div" and self._in_pi_value:
            # allow nested divs inside values; end handled by pi-data end
            pass
        if self._in_pi_label and tag_l in {"h3", "div", "span"}:
            self._in_pi_label = False
        if self._in_pi_value and tag_l in {"div", "span"}:
            self._in_pi_value = False
        if self._in_pi_data and tag_l in {"section", "div"}:
            # Closing a pi-data block: flush label/value.
            label = _norm_ws("".join(self._pi_label_parts))
            value = _norm_ws("".join(self._pi_value_parts))
            if label and value and len(label) <= 80 and len(value) <= 400:
                self.attributes.setdefault(label, value)
            self._in_pi_data = False
            self._pi_label_parts = []
            self._pi_value_parts = []

        if tag_l == "li" and self._in_li:
            self._in_li = False
            item = _norm_ws("".join(self._li_parts))
            self._li_parts = []
            if not item:
                return
            h = self._current_heading or ""
            if "loot" in h:
                self.loot.append(item)
            elif "abilit" in h:
                self.abilities.append(item)

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._in_h1:
            self._h1_parts.append(data)
        if self._in_heading:
            self._heading_parts.append(data)
        if self._in_p:
            self._p_parts.append(data)
        if self._in_tr and self._in_th:
            self._th_parts.append(data)
        if self._in_tr and self._in_td:
            self._td_parts.append(data)
        if self._in_pi_label:
            self._pi_label_parts.append(data)
        if self._in_pi_value:
            self._pi_value_parts.append(data)
        if self._in_li:
            self._li_parts.append(data)


def extract_tibia_monster(html: str, url: str) -> dict[str, Any]:
    """Best-effort Tibia Fandom monster extraction (stdlib only).

    Returns a JSON-serializable dict with:
    - name/url/description/attributes/loot/abilities/raw_text/confidence
    """

    raw_text = extract_readable_text(html or "")
    parser = _TibiaMonsterParser(url=url)
    try:
        parser.feed(html or "")
    except Exception:
        # If parsing fails, return readable text only.
        return TibiaMonsterExtraction(
            name=None,
            url=url,
            description=None,
            attributes={},
            loot=[],
            abilities=[],
            raw_text=raw_text,
            confidence=0.15,
        ).to_dict()

    desc = None
    for p in parser._paras:
        if p and len(p) >= 40:
            desc = p
            break
    conf = 0.2
    if parser.name:
        conf += 0.25
    if parser.attributes:
        conf += 0.25
    if parser.loot or parser.abilities:
        conf += 0.2
    conf = max(0.0, min(conf, 0.95))

    return TibiaMonsterExtraction(
        name=parser.name,
        url=url,
        description=desc,
        attributes=parser.attributes,
        loot=parser.loot[:50],
        abilities=parser.abilities[:50],
        raw_text=raw_text,
        confidence=conf,
    ).to_dict()


def safe_json_dumps(obj: Any, *, max_chars: int = 20_000) -> str:
    """Dump JSON deterministically and truncate if necessary (for event payloads)."""

    s = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    if len(s) > max(1, int(max_chars)):
        return s[: max(1, int(max_chars))] + "\n...truncated...\n"
    return s
