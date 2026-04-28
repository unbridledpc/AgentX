from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import os
from collections import deque
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any

from agentx.tools.base import Tool, ToolArgument, ToolExecutionError
from agentx.core.html_extract import extract_text_and_meta
from agentx.core.evidence import classify_trust
from agentx.core.web_policy import WebPolicy, is_allowed_url, normalize_host, registrable_domain


class WebAccessDenied(PermissionError):
    pass


def _normalize_host(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def _validate_host(host: str, *, allow_all: bool, allowed_suffixes: tuple[str, ...]) -> str:
    h = _normalize_host(host)
    if not h:
        raise WebAccessDenied("Missing hostname.")
    if allow_all:
        return h
    for suffix in allowed_suffixes:
        s = _normalize_host(suffix)
        if not s:
            continue
        if h == s or h.endswith("." + s):
            return h
    raise WebAccessDenied("Host not in allowlist.")


def _validate_resolved_ips(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise WebAccessDenied("Resolved IP not allowed (private/loopback/reserved).")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if not data:
            return
        self._chunks.append(data)

    def get_text(self) -> str:
        raw = unescape("".join(self._chunks))
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        return raw.strip()


def _read_limited(resp, *, max_bytes: int) -> tuple[bytes, bool]:
    buf = bytearray()
    truncated = False
    while True:
        chunk = resp.read(min(64 * 1024, max_bytes - len(buf)))
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) >= max_bytes:
            truncated = True
            break
    return bytes(buf), truncated


def _decode_bytes(raw: bytes, content_type: str) -> str:
    m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type or "", re.IGNORECASE)
    if m:
        enc = m.group(1)
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class FetchResult:
    url: str
    content_type: str
    text: str
    truncated: bool
    ts: float
    meta: dict[str, Any] | None = None


def fetch_text(url: str, *, ctx) -> FetchResult:
    cfg = ctx.cfg
    if not cfg.web.enabled:
        raise WebAccessDenied("Web access disabled.")

    policy = WebPolicy(
        allow_all_hosts=bool(getattr(cfg.web, "policy_allow_all_hosts", False)),
        allowed_host_suffixes=tuple(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ()),
        allowed_domains=tuple(getattr(cfg.web, "policy_allowed_domains", ()) or ()),
        denied_domains=tuple(getattr(cfg.web, "policy_denied_domains", ()) or ()),
    )
    session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())

    u = (url or "").strip()
    ok, reason = is_allowed_url(u, policy=policy, session_allowed_domains=session_allowed)
    if not ok:
        raise WebAccessDenied(reason)
    parsed = urllib.parse.urlparse(u)
    host = _normalize_host(parsed.hostname or "")
    if cfg.web.block_private_networks:
        _validate_resolved_ips(host)

    current = u
    redirects = 0
    while True:
        headers = {
            "User-Agent": cfg.web.user_agent,
            "Accept": "text/html, text/plain, application/json;q=0.9, */*;q=0.1",
        }
        # GitHub API hardening + optional auth via env var (never stored in config).
        if host == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            token_env = str(getattr(cfg.web, "github_token_env", "") or "").strip()
            if token_env:
                tok = (os.environ.get(token_env) or "").strip()
                if tok:
                    headers["Authorization"] = f"Bearer {tok}"

        req = urllib.request.Request(
            current,
            headers=headers,
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=cfg.web.timeout_s) as resp:
                content_type = (resp.headers.get("Content-Type") or "").strip()
                status = getattr(resp, "status", 200)
                location = resp.headers.get("Location")
                raw, truncated = _read_limited(resp, max_bytes=max(1, int(cfg.web.max_bytes)))
                final_url = getattr(resp, "geturl", lambda: current)()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise ToolExecutionError(f"HTTP {e.code}: {body[:4000]}")
        except Exception as e:
            raise ToolExecutionError(f"Request failed: {e}")

        if 300 <= int(status) < 400:
            if not location:
                break
            redirects += 1
            if redirects > max(0, int(cfg.web.max_redirects)):
                raise ToolExecutionError("Too many redirects.")
            next_url = urllib.parse.urljoin(current, location)
            ok2, reason2 = is_allowed_url(next_url, policy=policy, session_allowed_domains=session_allowed)
            if not ok2:
                raise WebAccessDenied(f"Redirect blocked: {reason2}")
            next_parsed = urllib.parse.urlparse(next_url)
            next_host = _normalize_host(next_parsed.hostname or "")
            if cfg.web.block_private_networks:
                _validate_resolved_ips(next_host)
            current = next_url
            continue

        decoded = _decode_bytes(raw, content_type)
        meta: dict[str, Any] | None = None
        if "text/html" in (content_type or "").lower():
            try:
                text_out, meta = extract_text_and_meta(decoded)
            except Exception:
                # Fallback to earlier lightweight extractor.
                try:
                    parser = _TextExtractor()
                    parser.feed(decoded)
                    text_out = parser.get_text()
                except Exception:
                    text_out = decoded
                meta = {"title": None, "byline": None, "published_time": None, "extracted_with": "fallback:text_extractor", "word_count": None}
        else:
            text_out = decoded
            meta = {"title": None, "byline": None, "published_time": None, "extracted_with": "none", "word_count": None}

        if truncated:
            meta = dict(meta or {})
            meta["truncated"] = True

        return FetchResult(
            url=str(final_url or current),
            content_type=content_type or "application/octet-stream",
            text=text_out,
            truncated=truncated,
            ts=time.time(),
            meta=meta,
        )


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


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    engine: str
    score: float
    ts: float


class SearchProvider:
    name: str

    def search(self, query: str, *, k: int, timeout_s: float, cfg) -> list[SearchResult]:  # pragma: no cover
        raise NotImplementedError()


def _canonicalize_url_for_dedupe(url: str) -> str:
    """Normalize a URL for dedupe/ranking (strip fragments + common tracking params)."""
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parsed = urllib.parse.urlsplit(u)
    except Exception:
        return u
    if parsed.scheme not in ("http", "https"):
        return u

    # Drop common trackers, preserve ordering deterministically.
    qsl = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    for k, v in qsl:
        kk = (k or "").strip()
        if not kk:
            continue
        low = kk.lower()
        if low.startswith("utm_") or low in ("gclid", "fbclid", "yclid", "mc_cid", "mc_eid"):
            continue
        kept.append((kk, v))
    query = urllib.parse.urlencode(kept, doseq=True)

    # Normalize host casing.
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    return urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))  # no fragment


def _domain(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def _is_denied_domain(url: str, *, denied_domains: tuple[str, ...]) -> bool:
    if not denied_domains:
        return False
    host = _domain(urllib.parse.urlparse(url).hostname or "")
    if not host:
        return False
    for d in denied_domains:
        dd = _domain(d)
        if not dd:
            continue
        if host == dd or host.endswith("." + dd):
            return True
    return False


def _rank_heuristic(*, url: str, title: str, snippet: str, provider_score: float, prefer_primary: bool) -> float:
    """Compute a stable rank score in [0, 1]. Prefer conservative, deterministic heuristics."""
    trust = classify_trust(url)
    base = {"primary": 0.75, "secondary": 0.55, "unknown": 0.35}[trust]
    score = base

    host = _domain(urllib.parse.urlparse(url).hostname or "")
    if "whitehouse.gov" in host or "usa.gov" in host:
        score += 0.10
    if host.endswith(".gov"):
        score += 0.08 if prefer_primary else 0.05
    if host.endswith(".edu"):
        score += 0.03

    # Neutral-to-slightly-downweight Wikipedia so it doesn't dominate verification.
    if host.endswith("wikipedia.org"):
        score -= 0.03 if prefer_primary else 0.01

    low = (title + " " + snippet).lower()
    if any(k in low for k in ("opinion", "blog", "medium.com", "substack", "wordpress")):
        score -= 0.06

    # Provider-local score contribution (already normalized by provider; fallback to 0.5).
    try:
        ps = float(provider_score)
    except Exception:
        ps = 0.5
    ps = max(0.0, min(ps, 1.0))
    score = score * 0.85 + ps * 0.15

    return max(0.0, min(score, 0.99))


def _diversify_by_engine(items: list[dict[str, Any]], *, max_total: int) -> list[dict[str, Any]]:
    """Reduce long streaks from a single engine without breaking global top ranking."""
    ordered = list(items)
    ordered.sort(key=lambda x: (-float(x.get("rank_score") or 0.0), str(x.get("url") or "")))

    out: list[dict[str, Any]] = []
    last_engine: str | None = None
    while ordered and len(out) < max_total:
        pick_idx = 0
        for i, it in enumerate(ordered):
            eng = str(it.get("engine") or "").strip().lower() or "unknown"
            if last_engine is None or eng != last_engine:
                pick_idx = i
                break
        chosen = ordered.pop(pick_idx)
        out.append(chosen)
        last_engine = str(chosen.get("engine") or "").strip().lower() or "unknown"
    return out


def _build_fetch_allowed(
    results: list[dict[str, Any]],
    *,
    allow_all_hosts: bool,
    allowed_host_suffixes: tuple[str, ...],
    denied_domains: tuple[str, ...],
) -> list[str]:
    out: list[str] = []
    for it in results:
        url = str(it.get("url") or "").strip()
        if not url:
            continue
        if _is_denied_domain(url, denied_domains=denied_domains):
            continue
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            continue
        host = (parsed.hostname or "").strip().lower().rstrip(".")
        if not host:
            continue
        # Avoid feeding provider URLs back into fetch.
        if host.endswith("duckduckgo.com"):
            continue
        if allow_all_hosts:
            out.append(url)
            continue
        for s in allowed_host_suffixes:
            ss = (s or "").strip().lower().rstrip(".")
            if not ss:
                continue
            if host == ss or host.endswith("." + ss):
                out.append(url)
                break
    # Stable de-dupe.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    return deduped


class DuckDuckGoSearchProvider(SearchProvider):
    name = "duckduckgo"

    def search(self, query: str, *, k: int, timeout_s: float, cfg) -> list[SearchResult]:
        if not cfg.web.enabled:
            raise WebAccessDenied("Web access disabled.")
        q = (query or "").strip()
        if not q:
            return []
        ddg_host = "duckduckgo.com"
        if not cfg.web.allow_all_hosts:
            _validate_host(ddg_host, allow_all=False, allowed_suffixes=cfg.web.allowed_host_suffixes)
        if cfg.web.block_private_networks:
            _validate_resolved_ips(ddg_host)

        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
        req = urllib.request.Request(
            url,
            headers={"User-Agent": cfg.web.user_agent, "Accept": "text/html, */*;q=0.1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
                raw = resp.read(max(1, int(cfg.web.max_bytes)))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise ToolExecutionError(f"DDG HTTP {e.code}: {body[:4000]}")
        except Exception as e:
            raise ToolExecutionError(f"DDG request failed: {e}")

        html_text = raw.decode("utf-8", errors="replace")
        parser = _DdgHtmlParser()
        parser.feed(html_text)
        out: list[SearchResult] = []
        for href, title, snippet in parser.results:
            out.append(
                SearchResult(
                    url=_unwrap_ddg_redirect(href),
                    title=(title or href).strip() or href,
                    snippet=(snippet or "").strip(),
                    engine=self.name,
                    score=0.5,
                    ts=time.time(),
                )
            )
            if len(out) >= max(1, int(k)):
                break
        return out


class SearxngSearchProvider(SearchProvider):
    name = "searxng"

    def __init__(self, *, base_url: str, categories: str) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.categories = (categories or "").strip() or "general"

    def search(self, query: str, *, k: int, timeout_s: float, cfg) -> list[SearchResult]:
        if not cfg.web.enabled:
            raise WebAccessDenied("Web access disabled.")
        q = (query or "").strip()
        if not q:
            return []
        if not self.base_url:
            return []
        try:
            parsed = urllib.parse.urlparse(self.base_url)
        except Exception:
            raise ToolExecutionError("Invalid searxng base_url.")
        host = parsed.hostname or ""
        if not host:
            raise ToolExecutionError("Invalid searxng base_url (missing host).")
        if parsed.scheme not in ("http", "https"):
            raise WebAccessDenied("searxng base_url must be http(s).")
        if not cfg.web.allow_all_hosts:
            _validate_host(host, allow_all=False, allowed_suffixes=cfg.web.allowed_host_suffixes)
        if cfg.web.block_private_networks:
            # Allow loopback-local SearxNG explicitly (common dev setup) without opening private network access broadly.
            if normalize_host(host) not in ("127.0.0.1", "localhost"):
                _validate_resolved_ips(host)

        params = {"q": q, "format": "json", "categories": self.categories}
        url = self.base_url + "/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": cfg.web.user_agent, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
                raw = resp.read(max(1, int(cfg.web.max_bytes)))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise ToolExecutionError(f"SearxNG HTTP {e.code}: {body[:4000]}")
        except Exception as e:
            raise ToolExecutionError(f"SearxNG request failed: {e}")

        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:
            raise ToolExecutionError(f"SearxNG JSON parse failed: {e}")
        items = data.get("results")
        out: list[SearchResult] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                url_s = str(it.get("url") or "").strip()
                if not url_s:
                    continue
                title = str(it.get("title") or url_s).strip() or url_s
                snippet = str(it.get("content") or it.get("snippet") or "").strip()
                out.append(SearchResult(url=url_s, title=title, snippet=snippet, engine=self.name, score=0.6, ts=time.time()))
                if len(out) >= max(1, int(k)):
                    break
        return out


class BingSearchProvider(SearchProvider):
    name = "bing"

    def __init__(self, *, api_key: str, endpoint: str) -> None:
        self.api_key = (api_key or "").strip()
        self.endpoint = (endpoint or "").strip() or "https://api.bing.microsoft.com/v7.0/search"

    def search(self, query: str, *, k: int, timeout_s: float, cfg) -> list[SearchResult]:
        if not cfg.web.enabled:
            raise WebAccessDenied("Web access disabled.")
        if not self.api_key:
            return []
        q = (query or "").strip()
        if not q:
            return []
        try:
            parsed = urllib.parse.urlparse(self.endpoint)
        except Exception:
            raise ToolExecutionError("Invalid Bing endpoint.")
        host = parsed.hostname or ""
        if not host:
            raise ToolExecutionError("Invalid Bing endpoint (missing host).")
        if parsed.scheme not in ("http", "https"):
            raise WebAccessDenied("Bing endpoint must be http(s).")
        if not cfg.web.allow_all_hosts:
            _validate_host(host, allow_all=False, allowed_suffixes=cfg.web.allowed_host_suffixes)
        if cfg.web.block_private_networks:
            _validate_resolved_ips(host)

        params = {"q": q, "count": str(max(1, int(k)))}
        url = self.endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": cfg.web.user_agent,
                "Accept": "application/json",
                "Ocp-Apim-Subscription-Key": self.api_key,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
                raw = resp.read(max(1, int(cfg.web.max_bytes)))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise ToolExecutionError(f"Bing HTTP {e.code}: {body[:4000]}")
        except Exception as e:
            raise ToolExecutionError(f"Bing request failed: {e}")
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:
            raise ToolExecutionError(f"Bing JSON parse failed: {e}")
        web_pages = data.get("webPages") if isinstance(data, dict) else None
        items = web_pages.get("value") if isinstance(web_pages, dict) else None
        out: list[SearchResult] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                url_s = str(it.get("url") or "").strip()
                if not url_s:
                    continue
                title = str(it.get("name") or url_s).strip() or url_s
                snippet = str(it.get("snippet") or "").strip()
                out.append(SearchResult(url=url_s, title=title, snippet=snippet, engine=self.name, score=0.7, ts=time.time()))
                if len(out) >= max(1, int(k)):
                    break
        return out


def _build_search_providers(*, cfg, names: list[str]) -> tuple[list[SearchProvider], list[dict[str, str]]]:
    providers: list[SearchProvider] = []
    failed: list[dict[str, str]] = []
    for raw in names:
        name = (raw or "").strip().lower()
        if not name:
            continue
        if name in ("ddg", "duck", "duckduckgo"):
            providers.append(DuckDuckGoSearchProvider())
        elif name in ("searx", "searxng"):
            providers.append(SearxngSearchProvider(base_url=getattr(cfg.web, "search_searxng_base_url", ""), categories=getattr(cfg.web, "search_searxng_categories", "general")))
        elif name == "bing":
            providers.append(BingSearchProvider(api_key=getattr(cfg.web, "search_bing_api_key", ""), endpoint=getattr(cfg.web, "search_bing_endpoint", "")))
        else:
            # Keep both keys for backwards compatibility with older UIs that expect `name`.
            failed.append({"provider": name, "name": name, "error": "Unknown provider"})
    return providers, failed


def meta_search(
    query: str,
    *,
    ctx,
    providers: list[str],
    timeout_s: float,
    k_per_provider: int,
    max_total_results: int,
    prefer_primary: bool,
) -> dict[str, Any]:
    """Meta-search across providers, merge/dedupe/rank, and return a non-breaking output shape."""
    q = (query or "").strip()
    if not q:
        return {
            "query": q,
            "results": [],
            "providers_used": [],
            "providers_failed": [],
            "meta": {"providers_used": [], "providers_failed": []},
            "fetch_allowed": [],
            "fetch_blocked": [],
        }
    cfg = ctx.cfg
    prov_instances, failed = _build_search_providers(cfg=cfg, names=providers)
    used: list[str] = []
    raw_results: list[SearchResult] = []
    for p in prov_instances:
        try:
            items = p.search(q, k=max(1, int(k_per_provider)), timeout_s=float(timeout_s), cfg=cfg)
            used.append(p.name)
            raw_results.extend(items or [])
        except Exception as e:
            prov = getattr(p, "name", "unknown")
            # Keep both keys for backwards compatibility with older UIs that expect `name`.
            failed.append({"provider": prov, "name": prov, "error": str(e)})

    # Normalize + dedupe by canonical URL, keeping the best-ranked instance.
    policy = WebPolicy(
        allow_all_hosts=bool(getattr(cfg.web, "policy_allow_all_hosts", False)),
        allowed_host_suffixes=tuple(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ()),
        allowed_domains=tuple(getattr(cfg.web, "policy_allowed_domains", ()) or ()),
        denied_domains=tuple(getattr(cfg.web, "policy_denied_domains", ()) or ()),
    )
    deduped: dict[str, dict[str, Any]] = {}
    for r in raw_results:
        url = (r.url or "").strip()
        if not url:
            continue
        canon = _canonicalize_url_for_dedupe(url)
        if not canon:
            continue
        trust_hint = classify_trust(url)
        rank_score = _rank_heuristic(url=url, title=r.title, snippet=r.snippet, provider_score=r.score, prefer_primary=prefer_primary)
        it = {
            "url": url,
            "title": (r.title or url).strip() or url,
            "snippet": (r.snippet or "").strip(),
            "ts": float(r.ts or time.time()),
            "engine": (r.engine or "").strip() or "unknown",
            "provider": (r.engine or "").strip() or "unknown",
            "rank_score": float(rank_score),
            "trust_hint": trust_hint,
            "_canon": canon,
        }
        prev = deduped.get(canon)
        if not prev or float(it["rank_score"]) > float(prev.get("rank_score") or 0.0):
            deduped[canon] = it

    merged = list(deduped.values())
    merged.sort(key=lambda x: (-float(x.get("rank_score") or 0.0), str(x.get("_canon") or "")))
    diversified = _diversify_by_engine(merged, max_total=max(1, int(max_total_results)))
    # Domain diversity: limit early dominance by a single registrable domain.
    domain_cap = 2
    picked: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    pending = list(diversified)
    for it in list(pending):
        if len(picked) >= max(1, int(max_total_results)):
            break
        host = normalize_host(urllib.parse.urlparse(str(it.get("url") or "")).hostname or "")
        dom = registrable_domain(host) or host
        if counts.get(dom, 0) >= domain_cap:
            continue
        counts[dom] = counts.get(dom, 0) + 1
        picked.append(it)
    # Fill remaining slots if we skipped too much.
    if len(picked) < max(1, int(max_total_results)):
        for it in pending:
            if it in picked:
                continue
            picked.append(it)
            if len(picked) >= max(1, int(max_total_results)):
                break
    diversified = picked[: max(1, int(max_total_results))]
    for it in diversified:
        it.pop("_canon", None)

    session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
    fetch_allowed: list[str] = []
    fetch_blocked: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for it in diversified:
        url = str(it.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        ok, reason = is_allowed_url(url, policy=policy, session_allowed_domains=session_allowed)
        if ok:
            fetch_allowed.append(url)
        else:
            fetch_blocked.append({"url": url, "reason": reason})

    return {
        "query": q,
        "results": diversified,
        "providers_used": used,
        "providers_failed": failed,
        "meta": {"providers_used": used, "providers_failed": failed},
        "fetch_allowed": fetch_allowed,
        "fetch_blocked": fetch_blocked,
    }


def ddg_search(query: str, *, cfg) -> list[dict[str, Any]]:
    if not cfg.web.enabled:
        raise WebAccessDenied("Web access disabled.")
    q = (query or "").strip()
    if not q:
        return []
    # Backward-compat wrapper for older callers: use the DDG provider.
    prov = DuckDuckGoSearchProvider()
    out: list[dict[str, Any]] = []
    for r in prov.search(q, k=max(1, int(cfg.web.max_search_results)), timeout_s=float(cfg.web.timeout_s), cfg=cfg):
        out.append({"url": r.url, "title": r.title, "snippet": r.snippet, "ts": r.ts})
    return out


class WebFetchTool(Tool):
    name = "web.fetch"
    description = "Fetch a web page (safe allowlist) and return extracted text"
    args = (
        ToolArgument("url", str, "URL to fetch", required=True),
        ToolArgument("store", bool, "Deprecated (memory is handled by the Agent)", required=False, default=False),
        ToolArgument("reason", str, "Reason for fetching", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        res = fetch_text(args["url"], ctx=ctx)
        meta = dict(res.meta or {})
        # Keep tool output bounded; full content can be ingested via web.ingest_url.
        text = res.text or ""
        if len(text) > 8000:
            text = text[:8000] + "\n...truncated for tool output...\n"
            meta["output_truncated"] = True
        out: dict[str, Any] = {
            "url": res.url,
            "content_type": res.content_type,
            "text": text,
            "truncated": bool(res.truncated),
            "ts": res.ts,
            "meta": meta,
        }
        if args.get("store"):
            out["note"] = "store=true is deprecated; web content is stored by the Agent memory hook."
        return out


class WebSearchTool(Tool):
    name = "web.search"
    description = "Meta-search across configured providers (safe allowlist), merge/dedupe, and return ranked results"
    args = (
        ToolArgument("query", str, "Search query", required=True),
        ToolArgument("k", int, "Deprecated alias for max_total_results (kept for backwards compatibility)", required=False, default=0),
        ToolArgument("providers", list, "Optional provider names override (e.g. ['searxng','duckduckgo'])", required=False, default=[]),
        ToolArgument("k_per_provider", int, "Max results per provider", required=False, default=0),
        ToolArgument("max_total_results", int, "Max total results after merge/dedupe", required=False, default=0),
        ToolArgument("timeout_s", (int, float), "Timeout seconds per provider request", required=False, default=0.0),
        ToolArgument("prefer_primary", bool, "Bias ranking toward primary sources (.gov/etc)", required=False, default=False),
        ToolArgument("if_no_primary", bool, "Agent-internal: skip this search if primary sources already found", required=False, default=False),
        ToolArgument("reason", str, "Reason for searching", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        cfg = ctx.cfg
        providers = [str(x) for x in (args.get("providers") or []) if isinstance(x, str) and x.strip()]
        if not providers:
            providers = list(getattr(cfg.web, "search_providers", ()) or ("duckduckgo",))
        k_per_provider = int(args.get("k_per_provider") or 0) or int(getattr(cfg.web, "search_k_per_provider", 8))
        max_total = int(args.get("max_total_results") or 0) or int(args.get("k") or 0) or int(getattr(cfg.web, "search_max_total_results", int(cfg.web.max_search_results)))
        timeout_s = float(args.get("timeout_s") or 0.0) or float(getattr(cfg.web, "search_timeout_s", float(cfg.web.timeout_s)))
        prefer_primary = bool(args.get("prefer_primary") or False)
        return meta_search(
            args["query"],
            ctx=ctx,
            providers=providers,
            timeout_s=timeout_s,
            k_per_provider=max(1, min(k_per_provider, 50)),
            max_total_results=max(1, min(max_total, 50)),
            prefer_primary=prefer_primary,
        )


def _host_allowed(host: str, *, allowed_domains: tuple[str, ...]) -> bool:
    h = _normalize_host(host)
    for dom in allowed_domains:
        d = _normalize_host(dom)
        if not d:
            continue
        if h == d or h.endswith("." + d):
            return True
    return False


def _extract_links(html_text: str, base_url: str) -> list[str]:
    # Best-effort link extraction. Keeps it stdlib-only.
    urls: list[str] = []
    for m in re.finditer(r'href\\s*=\\s*["\\\']([^"\\\']+)["\\\']', html_text, flags=re.IGNORECASE):
        href = (m.group(1) or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith(("mailto:", "javascript:")):
            continue
        try:
            abs_url = urllib.parse.urljoin(base_url, href)
        except Exception:
            continue
        urls.append(abs_url)
    # Deterministic: preserve first occurrences.
    seen = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _fetch_html(url: str, *, ctx) -> tuple[str, str, float]:
    """Fetch raw HTML (still policy-checked) and return (final_url, html_text, ts)."""
    cfg = ctx.cfg
    if not cfg.web.enabled:
        raise WebAccessDenied("Web access disabled.")

    u = (url or "").strip()
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise WebAccessDenied("Only http/https URLs are allowed.")
    if not parsed.netloc:
        raise WebAccessDenied("URL must include a hostname.")

    host = _normalize_host(parsed.hostname or "")
    if cfg.web.block_private_networks:
        _validate_resolved_ips(host)

    policy = WebPolicy(
        allow_all_hosts=bool(getattr(cfg.web, "policy_allow_all_hosts", False)),
        allowed_host_suffixes=tuple(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ()),
        allowed_domains=tuple(getattr(cfg.web, "policy_allowed_domains", ()) or ()),
        denied_domains=tuple(getattr(cfg.web, "policy_denied_domains", ()) or ()),
    )
    session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
    ok, reason = is_allowed_url(u, policy=policy, session_allowed_domains=session_allowed)
    if not ok:
        raise WebAccessDenied(reason)

    req = urllib.request.Request(
        u,
        headers={
            "User-Agent": cfg.web.user_agent,
            "Accept": "text/html, */*;q=0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.web.timeout_s) as resp:
            content_type = (resp.headers.get("Content-Type") or "").strip()
            raw, _truncated = _read_limited(resp, max_bytes=max(1, int(cfg.web.max_bytes)))
            final_url = getattr(resp, "geturl", lambda: u)()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
        raise ToolExecutionError(f"HTTP {e.code}: {body[:4000]}")
    except Exception as e:
        raise ToolExecutionError(f"Request failed: {e}")

    html_text = _decode_bytes(raw, content_type or "")
    return final_url, html_text, time.time()


class WebCrawlTool(Tool):
    name = "web.crawl"
    description = "Crawl a site within an allowlisted domain and return extracted text (untrusted)"
    args = (
        ToolArgument("start_url", str, "Start URL", required=True),
        ToolArgument("allowed_domains", list, "Optional allowlisted domains (defaults from config)", required=False, default=[]),
        ToolArgument("max_pages", int, "Max pages to fetch (clamped)", required=False, default=50),
        ToolArgument("max_depth", int, "Max link depth (clamped)", required=False, default=2),
        ToolArgument("delay_ms", int, "Delay between requests (clamped)", required=False, default=500),
        ToolArgument("reason", str, "Reason for crawling", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        start_url = (args.get("start_url") or "").strip()
        if not start_url:
            raise ToolExecutionError("start_url is required.")

        policy = WebPolicy(
            allow_all_hosts=bool(getattr(ctx.cfg.web, "policy_allow_all_hosts", False)),
            allowed_host_suffixes=tuple(getattr(ctx.cfg.web, "policy_allowed_host_suffixes", ()) or ()),
            allowed_domains=tuple(getattr(ctx.cfg.web, "policy_allowed_domains", ()) or ()),
            denied_domains=tuple(getattr(ctx.cfg.web, "policy_denied_domains", ()) or ()),
        )
        session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
        ok, reason = is_allowed_url(start_url, policy=policy, session_allowed_domains=session_allowed)
        if not ok:
            raise ToolExecutionError(f"Start URL blocked by policy: {reason}")

        parsed = urllib.parse.urlparse(start_url)
        host = _normalize_host(parsed.hostname or "")
        if not host:
            raise ToolExecutionError("start_url must include a hostname.")

        cfg_domains = tuple(ctx.cfg.web.allowed_domains or ())
        if not cfg_domains:
            cfg_domains = tuple(getattr(ctx.cfg.web, "policy_allowed_domains", ()) or ())

        provided = args.get("allowed_domains") or []
        allowed_domains = cfg_domains
        if isinstance(provided, list) and provided:
            allowed_domains = tuple(str(x).strip().lower().rstrip(".") for x in provided if str(x).strip())

        if not _host_allowed(host, allowed_domains=allowed_domains):
            raise ToolExecutionError("Start URL domain not allowed for crawl.")

        max_pages = max(1, min(int(args.get("max_pages") or ctx.cfg.web.crawl_max_pages_default), 200))
        max_depth = max(0, min(int(args.get("max_depth") or 2), 5))
        delay_ms = max(0, min(int(args.get("delay_ms") or ctx.cfg.web.crawl_delay_ms_default), 5000))

        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        seen: set[str] = set()
        pages: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        while queue and len(pages) < max_pages:
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            try:
                final_url, html_text, ts = _fetch_html(url, ctx=ctx)
                final_host = _normalize_host(urllib.parse.urlparse(final_url).hostname or "")
                if not _host_allowed(final_host, allowed_domains=allowed_domains):
                    raise ToolExecutionError("Crawl refused a redirect outside allowed domains.")

                # Extract readable text + basic metadata using the shared HTML extractor.
                meta: dict[str, Any] | None = None
                try:
                    text, meta = extract_text_and_meta(html_text)
                except Exception:
                    # Fallback to earlier lightweight extractor.
                    try:
                        extractor = _TextExtractor()
                        extractor.feed(html_text)
                        text = extractor.get_text()
                    except Exception:
                        text = re.sub(r"\s+", " ", html_text)[:2000]
                    meta = {"title": None, "byline": None, "published_time": None, "extracted_with": "fallback:text_extractor", "word_count": None}

                pages.append({"url": final_url, "text": (text or "")[:8000], "meta": meta, "ts": ts})

                if depth < max_depth:
                    for link in _extract_links(html_text, final_url):
                        lp = urllib.parse.urlparse(link)
                        if lp.scheme not in ("http", "https"):
                            continue
                        lh = _normalize_host(lp.hostname or "")
                        if not lh:
                            continue
                        if not _host_allowed(lh, allowed_domains=allowed_domains):
                            continue
                        ok_link, _reason = is_allowed_url(link, policy=policy, session_allowed_domains=session_allowed)
                        if not ok_link:
                            continue
                        queue.append((link, depth + 1))
            except Exception as e:
                failures.append({"url": url, "error": str(e)})

            if delay_ms:
                time.sleep(delay_ms / 1000.0)

        return {
            "start_url": start_url,
            "allowed_domains": list(allowed_domains),
            "pages_fetched": len(pages),
            "pages": pages,
            "failures": failures,
        }
