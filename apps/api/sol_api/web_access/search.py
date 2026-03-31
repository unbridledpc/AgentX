from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

from .errors import WebFetchError
from .policy import WebPolicy, validate_host, validate_resolved_ips


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    ts: float


class _DdgHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._cur_href: str | None = None
        self._cur_title_parts: list[str] = []
        self._cur_snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: v for k, v in attrs}
        cls = (attrs_d.get("class") or "").strip()
        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self._cur_href = attrs_d.get("href") or None
            self._cur_title_parts = []
            self._cur_snippet_parts = []
        if ("result__snippet" in cls) and tag in ("a", "div", "span"):
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if self._in_snippet and tag in ("a", "div", "span"):
            self._in_snippet = False
            # Only finalize if we have a link and a title.
            if self._cur_href and self._cur_title_parts:
                href = self._cur_href
                title = " ".join("".join(self._cur_title_parts).split())
                snippet = " ".join("".join(self._cur_snippet_parts).split())
                self.results.append((href, title, snippet))
                self._cur_href = None
                self._cur_title_parts = []
                self._cur_snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._cur_title_parts.append(data)
        if self._in_snippet:
            self._cur_snippet_parts.append(data)


def _unwrap_ddg_redirect(href: str) -> str:
    try:
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            qs = urllib.parse.parse_qs(parsed.query)
            uddg = (qs.get("uddg") or [None])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
    except Exception:
        pass
    return href


def search(query: str, *, policy: WebPolicy) -> list[SearchResult]:
    if not policy.enabled:
        raise WebFetchError("Web access is disabled (SOL_WEB_ENABLED=false).")
    q = (query or "").strip()
    if not q:
        return []

    # Always validate DDG host/IP regardless of allow_all.
    ddg_host = validate_host("duckduckgo.com", policy=policy) if not policy.allow_all_hosts else "duckduckgo.com"
    validate_resolved_ips(ddg_host, policy=policy)

    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": policy.user_agent,
            "Accept": "text/html, */*;q=0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=policy.timeout_s) as resp:
            raw = resp.read(max(1, int(policy.max_bytes)))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
        raise WebFetchError(f"DDG HTTP {e.code}: {body[:4000]}")
    except Exception as e:
        raise WebFetchError(f"DDG request failed: {e}")

    html_text = raw.decode("utf-8", errors="replace")
    parser = _DdgHtmlParser()
    parser.feed(html_text)

    out: list[SearchResult] = []
    for href, title, snippet in parser.results:
        final_url = _unwrap_ddg_redirect(href)
        out.append(SearchResult(url=final_url, title=title or final_url, snippet=snippet, ts=time.time()))
        if len(out) >= max(1, int(policy.max_search_results)):
            break
    return out
