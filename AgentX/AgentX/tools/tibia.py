from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentx.core.forum_extract import extract_forum_text_and_meta
from agentx.core.web_policy import WebPolicy, is_allowed_url, normalize_host, registrable_domain
from agentx.tools.base import Tool, ToolArgument, ToolExecutionError

# Reuse hardened fetch + robots helpers from web.ingest_url (policy/redirect checked).
from agentx.tools.web_ingest_url import _fetch_html_checked, _parse_robots, _robots_allows, _robots_url
from agentx.tools.web import WebAccessDenied


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _invoke_tool(ctx, *, tool_name: str, tool_args: dict[str, Any], reason: str) -> Any:
    reg = getattr(ctx, "tool_registry", None)
    if reg is None:
        from agentx.tools.registry import build_default_registry

        reg = build_default_registry()
    tool, validated = reg.prepare_for_execution(tool_name, tool_args, reason=reason)
    return tool.run(ctx, validated)


def _policy_from_cfg(cfg) -> WebPolicy:
    return WebPolicy(
        allow_all_hosts=bool(getattr(cfg.web, "policy_allow_all_hosts", False)),
        allowed_host_suffixes=tuple(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ()),
        allowed_domains=tuple(getattr(cfg.web, "policy_allowed_domains", ()) or ()),
        denied_domains=tuple(getattr(cfg.web, "policy_denied_domains", ()) or ()),
    )


def _tibia_sources_cfg(cfg) -> tuple[dict[str, str], dict[str, bool], dict[str, Any]]:
    tib = getattr(cfg, "tibia", None)
    sources = getattr(tib, "sources", None) if tib else None
    domains = dict(getattr(sources, "domains", {}) or {}) if sources else {}
    enabled = dict(getattr(sources, "domain_enabled", {}) or {}) if sources else {}
    meta = {
        "enabled": bool(getattr(sources, "enabled", True)) if sources else True,
        "default_delay_ms": int(getattr(sources, "default_delay_ms", 500)) if sources else 500,
        "max_threads": int(getattr(sources, "max_threads", 5)) if sources else 5,
        "max_pages_per_thread": int(getattr(sources, "max_pages_per_thread", 5)) if sources else 5,
    }
    return domains, enabled, meta


def _pick_domain_key(host: str, *, domains: dict[str, str]) -> str | None:
    h = normalize_host(host)
    if not h:
        return None
    for k, dom in (domains or {}).items():
        d = normalize_host(dom)
        if not d:
            continue
        if h == d or h.endswith("." + d):
            return str(k)
    return None


def _looks_like_login_gate(html: str) -> bool:
    low = (html or "").lower()
    if "you must be logged in" in low or "you must log in" in low:
        return True
    if "log in" in low and ("password" in low or "remember me" in low):
        return True
    if 'action="/login' in low or "data-xf-init=\"login\"" in low:
        return True
    return False


@dataclass(frozen=True)
class ThreadScope:
    host: str
    domain_key: str
    domain: str
    thread_id: str | None
    thread_path_prefix: str

    def matches(self, url: str) -> bool:
        try:
            p = urllib.parse.urlparse(url)
        except Exception:
            return False
        h = normalize_host(p.hostname or "")
        # Allow redirects between bare and www. subdomains while staying within the configured registrable domain.
        if h != self.host:
            if not self.domain:
                return False
            if not (h == self.domain or h.endswith("." + self.domain)):
                return False
        path = (p.path or "").strip()
        if not path:
            return False
        if self.thread_id:
            # XenForo style: /threads/<slug>.<id>/... or /threads/<id>/...
            if "/threads/" not in path:
                return False
            return self.thread_id in path
        return path.startswith(self.thread_path_prefix)


def _thread_scope(start_url: str, *, domains: dict[str, str]) -> ThreadScope | None:
    try:
        p = urllib.parse.urlparse(start_url)
    except Exception:
        return None
    host = normalize_host(p.hostname or "")
    if not host:
        return None
    key = _pick_domain_key(host, domains=domains)
    if not key:
        return None
    dom = normalize_host(domains.get(key) or "")
    path = (p.path or "/").strip()

    thread_id: str | None = None
    # Try to extract numeric thread id from a XenForo-like URL.
    # Examples:
    # - /threads/foo-bar.12345/
    # - /threads/12345/
    m = re.search(r"/threads/[^/]*?(\d+)(?:/|$)", path)
    if m:
        thread_id = m.group(1)

    # Fallback: lock scope to the /threads/<segment>/ prefix.
    prefix = path
    if "/threads/" in path:
        parts = path.split("/")
        try:
            idx = parts.index("threads")
        except ValueError:
            idx = -1
        if idx >= 0 and idx + 1 < len(parts):
            prefix = "/".join(parts[: idx + 2]).rstrip("/") + "/"
    else:
        prefix = path.rstrip("/") + "/"

    return ThreadScope(host=host, domain_key=key, domain=dom, thread_id=thread_id, thread_path_prefix=prefix)


def _find_next_page_url(html: str, *, base_url: str) -> str | None:
    s = html or ""
    # rel="next"
    m = re.search(r'rel\s*=\s*["\']next["\'][^>]*href\s*=\s*["\']([^"\']+)["\']', s, flags=re.IGNORECASE)
    if m:
        return urllib.parse.urljoin(base_url, (m.group(1) or "").strip())
    # XenForo-ish "next" button
    m2 = re.search(
        r'class\s*=\s*["\'][^"\']*(pageNav-jump--next|pageNavSimple-el--next)[^"\']*["\'][^>]*href\s*=\s*["\']([^"\']+)["\']',
        s,
        flags=re.IGNORECASE,
    )
    if m2:
        return urllib.parse.urljoin(base_url, (m2.group(2) or "").strip())
    # Last resort: anchor text "Next"
    m3 = re.search(r'href\s*=\s*["\']([^"\']+)["\'][^>]*>\s*(next|›|»)\s*<', s, flags=re.IGNORECASE)
    if m3:
        return urllib.parse.urljoin(base_url, (m3.group(1) or "").strip())
    return None


def _distill_agentx_notes(*, domain: str, domain_key: str, thread_title: str | None, start_url: str, pages: list[dict[str, Any]]) -> str:
    title = (thread_title or "").strip() or "<unknown thread>"
    lines: list[str] = []
    lines.append(f"AGENTX NOTES (tibia forums) — {domain_key} ({domain})")
    lines.append(f"Thread: {title}")
    lines.append(f"Start URL: {start_url}")
    lines.append(f"Retrieved: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
    lines.append("")

    # Summary: first substantial paragraph from page 1.
    first_text = ""
    if pages and isinstance(pages[0], dict):
        first_text = str(pages[0].get("text") or "")
    paras = [p.strip() for p in re.split(r"\n{2,}", first_text) if p.strip()]
    summary = ""
    for p in paras:
        if len(p) >= 200:
            summary = p[:1200].strip()
            break
    if not summary and paras:
        summary = paras[0][:800].strip()
    if summary:
        lines.append("Summary:")
        lines.append(summary)
        lines.append("")

    # Key takeaways: heuristic sentence/line picks.
    takeaways: list[str] = []
    for pg in pages:
        txt = str(pg.get("text") or "")
        for ln in (txt.splitlines() if txt else []):
            s = ln.strip()
            if not s or len(s) < 20:
                continue
            low = s.lower()
            if any(k in low for k in ("important", "note:", "gotcha", "warning", "make sure", "you must", "recommend", "works on", "doesn't work", "fix", "solution")):
                takeaways.append(s)
            if len(takeaways) >= 12:
                break
        if len(takeaways) >= 12:
            break
    if takeaways:
        lines.append("Key takeaways:")
        for t in takeaways[:10]:
            lines.append(f"- {t}")
        lines.append("")

    # Code snippets: pull first N fenced blocks.
    snippets: list[str] = []
    for pg in pages:
        txt = str(pg.get("text") or "")
        for m in re.finditer(r"```\\n(.*?)\\n```", txt, flags=re.DOTALL):
            block = (m.group(1) or "").strip()
            if not block:
                continue
            snippets.append(block)
            if len(snippets) >= 8:
                break
        if len(snippets) >= 8:
            break
    if snippets:
        lines.append("Code snippets:")
        for i, b in enumerate(snippets[:5], start=1):
            lines.append(f"[snippet {i}]")
            lines.append("```")
            # Keep bounded.
            lines.append(b[:4000])
            lines.append("```")
            lines.append("")

    lines.append("Links:")
    for pg in pages[:10]:
        u = str(pg.get("url") or "").strip()
        pn = pg.get("page_num")
        if u:
            lines.append(f"- page {pn}: {u}" if pn else f"- {u}")
    return "\n".join(lines).strip() + "\n"


class TibiaSearchSourcesTool(Tool):
    name = "tibia.search_sources"
    description = "Search Tibia/TFS forum sources (otland.net, tibiaking.com) via web.search with site: filters"
    args = (
        ToolArgument("query", str, "Search query", required=True),
        ToolArgument("k", int, "Results per domain (default 5)", required=False, default=5),
        ToolArgument("reason", str, "Reason for searching", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        q = str(args.get("query") or "").strip()
        if not q:
            raise ToolExecutionError("query is required.")
        domains, domain_enabled, meta = _tibia_sources_cfg(ctx.cfg)
        if not bool(meta.get("enabled")):
            return {"ok": True, "status": "disabled", "query": q, "results": [], "ts": time.time()}

        k = max(1, min(int(args.get("k") or 5), 20))
        enabled_domains = [(k2, v2) for (k2, v2) in domains.items() if domain_enabled.get(k2, True)]

        out: list[dict[str, Any]] = []
        providers_failed: list[dict[str, Any]] = []
        for key, dom in enabled_domains:
            site_q = f"site:{dom} {q}"
            try:
                res = _invoke_tool(
                    ctx,
                    tool_name="web.search",
                    tool_args={"query": site_q, "k": k},
                    reason=f"tibia.search_sources ({key})",
                )
            except Exception as e:
                providers_failed.append({"domain_key": key, "domain": dom, "error": str(e)})
                continue
            items = res.get("results") if isinstance(res, dict) else None
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                url = str(it.get("url") or "").strip()
                if not url:
                    continue
                host = normalize_host(urllib.parse.urlparse(url).hostname or "")
                if not (host == dom or host.endswith("." + dom)):
                    continue
                out.append(
                    {
                        "title": str(it.get("title") or url).strip(),
                        "url": url,
                        "snippet": str(it.get("snippet") or "").strip(),
                        "score": float(it.get("rank_score") or 0.0),
                        "domain": dom,
                        "domain_key": key,
                    }
                )

        out.sort(key=lambda r: (-float(r.get("score") or 0.0), str(r.get("url") or "")))
        return {
            "ok": True,
            "status": "ok",
            "query": q,
            "domains": [{"key": k2, "domain": v2, "enabled": bool(domain_enabled.get(k2, True))} for (k2, v2) in domains.items()],
            "results": out[: max(1, int(len(enabled_domains) * k))],
            "providers_failed": providers_failed,
            "ts": time.time(),
        }


class TibiaIngestThreadTool(Tool):
    name = "tibia.ingest_thread"
    description = "Ingest a single forum thread (bounded pages, robots-aware) and write a manifest/pages for Agent ingestion"
    args = (
        ToolArgument("start_url", str, "Thread URL (otland.net or tibiaking.com)", required=True),
        ToolArgument("max_pages", int, "Max pages to ingest (default from config)", required=False, default=0),
        ToolArgument("delay_ms", int, "Delay between page fetches (default from config)", required=False, default=0),
        ToolArgument("reason", str, "Reason for ingestion", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        start_url = str(args.get("start_url") or "").strip()
        if not start_url:
            raise ToolExecutionError("start_url is required.")

        domains, domain_enabled, meta = _tibia_sources_cfg(ctx.cfg)
        if not bool(meta.get("enabled")):
            return {"ok": True, "status": "disabled", "start_url": start_url, "ts": time.time()}

        host = normalize_host(urllib.parse.urlparse(start_url).hostname or "")
        key = _pick_domain_key(host, domains=domains)
        if not key or not domain_enabled.get(key, True):
            return {"ok": True, "status": "blocked", "start_url": start_url, "blocked": [{"url": start_url, "reason": "Domain not enabled for tibia sources."}], "ts": time.time()}

        policy = _policy_from_cfg(ctx.cfg)
        session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
        ok_policy, why = is_allowed_url(start_url, policy=policy, session_allowed_domains=session_allowed)
        if not ok_policy:
            dom = domains.get(key) or host
            return {
                "ok": True,
                "status": "blocked",
                "start_url": start_url,
                "blocked": [{"url": start_url, "reason": str(why), "suggestion": {"action": "allow_domain", "domain": dom}}],
                "ts": time.time(),
            }

        max_pages_cfg = int(meta.get("max_pages_per_thread") or 5)
        delay_cfg = int(meta.get("default_delay_ms") or 500)
        max_pages = int(args.get("max_pages") or 0) or max_pages_cfg
        delay_ms = int(args.get("delay_ms") or 0) or delay_cfg
        max_pages = max(1, min(max_pages, 20))
        delay_ms = max(0, min(delay_ms, 5000))

        ts0 = time.time()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(ts0))
        hid = hashlib.sha256(f"tibia|thread|{start_url}|{ts0}".encode("utf-8", errors="ignore")).hexdigest()[:12]
        manifest_id = f"tibia_{stamp}_{hid}"
        base_dir = Path(ctx.cfg.paths.data_dir) / "ingest" / manifest_id
        base_dir.mkdir(parents=True, exist_ok=True)

        scope = _thread_scope(start_url, domains=domains)
        if not scope:
            return {"ok": True, "status": "blocked", "start_url": start_url, "blocked": [{"url": start_url, "reason": "Unsupported thread URL for configured domains."}], "ts": time.time()}

        # robots.txt cache by registrable domain.
        robots_disallow: dict[str, list[str]] = {}

        def robots_allows(u: str) -> bool:
            reg = registrable_domain(normalize_host(urllib.parse.urlparse(u).hostname or "")) or scope.domain
            if reg not in robots_disallow:
                try:
                    ru = _robots_url(u)
                    ok_r, _why_r = is_allowed_url(ru, policy=policy, session_allowed_domains=session_allowed)
                    if not ok_r:
                        robots_disallow[reg] = []
                    else:
                        rob = _fetch_html_checked(ru, ctx=ctx)
                        robots_disallow[reg] = _parse_robots(rob.html, user_agent=str(ctx.cfg.web.user_agent))
                except Exception:
                    robots_disallow[reg] = []
            return _robots_allows(u, disallow=robots_disallow.get(reg, []))

        pages: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        status = "ok"
        thread_title: str | None = None

        current = start_url
        for i in range(1, max_pages + 1):
            if not robots_allows(current):
                blocked.append({"url": current, "reason": "Blocked by robots.txt (best-effort)."})
                status = "blocked"
                break
            if not scope.matches(current):
                blocked.append({"url": current, "reason": "URL out of thread scope."})
                status = "blocked"
                break
            try:
                r = _fetch_html_checked(current, ctx=ctx)
            except WebAccessDenied as e:
                dom = domains.get(key) or host
                blocked.append({"url": current, "reason": str(e), "suggestion": {"action": "allow_domain", "domain": dom}})
                status = "blocked"
                break
            except Exception as e:
                errors.append({"url": current, "error": str(e)})
                status = "error"
                break

            if int(r.status) in (401, 403):
                blocked.append({"url": r.url, "reason": f"HTTP {r.status} (auth likely required)."})
                status = "auth_required"
                break
            if _looks_like_login_gate(r.html):
                blocked.append({"url": r.url, "reason": "Login/auth required (detected by page content)."})
                status = "auth_required"
                break

            text, meta_out = extract_forum_text_and_meta(r.html)
            title = str(meta_out.get("title") or "").strip() if isinstance(meta_out, dict) else ""
            if title and not thread_title:
                thread_title = title
            if not text.strip():
                errors.append({"url": r.url, "error": "No extractable text."})
                status = "error"
                break
            if len(text) > 200_000:
                text = text[:200_000] + "\n...truncated...\n"

            file_name = f"page_{i:03d}.txt"
            (base_dir / file_name).write_text(text, encoding="utf-8")
            pages.append(
                {
                    "url": r.url,
                    "ts": float(r.ts),
                    "page_num": i,
                    "file": file_name,
                    "title": title or None,
                    "bytes": int(r.bytes),
                    "content_type": str(r.content_type or ""),
                    "domain": scope.domain,
                    "domain_key": scope.domain_key,
                    "thread_title": thread_title,
                    "thread_id": scope.thread_id,
                    "tags": ["tibia", "tfs", f"tibia:source:{scope.domain_key}", "tibia:forum", "tibia:thread"],
                }
            )

            nxt = _find_next_page_url(r.html, base_url=r.url)
            if not nxt:
                break
            if not scope.matches(nxt):
                break
            current = nxt
            if delay_ms:
                time.sleep(delay_ms / 1000.0)

        # Distill a note doc (high signal) and include it as a separate ingestable page.
        if pages:
            pages_with_text: list[dict[str, Any]] = []
            for p in pages:
                try:
                    fn = str(p.get("file") or "")
                    if not fn or not fn.startswith("page_"):
                        continue
                    text = (base_dir / fn).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    text = ""
                pages_with_text.append({**p, "text": text})

            note_text = _distill_agentx_notes(
                domain=scope.domain,
                domain_key=scope.domain_key,
                thread_title=thread_title,
                start_url=start_url,
                pages=pages_with_text,
            )
            note_file = "note.txt"
            (base_dir / note_file).write_text(note_text, encoding="utf-8")
            pages.append(
                {
                    "url": f"note:tibia:{scope.domain_key}:{manifest_id}",
                    "ts": float(time.time()),
                    "page_num": None,
                    "file": note_file,
                    "title": f"AgentX Notes: {thread_title or scope.domain_key}",
                    "bytes": int(len(note_text.encode("utf-8", errors="ignore"))),
                    "content_type": "text/plain",
                    "domain": scope.domain,
                    "domain_key": scope.domain_key,
                    "thread_title": thread_title,
                    "thread_id": scope.thread_id,
                    "kind": "note",
                    "tags": ["tibia", "tfs", f"tibia:source:{scope.domain_key}", "notes:tibia", f"notes:tibia:{scope.domain_key}"],
                }
            )

        ts1 = time.time()
        manifest = {
            "id": manifest_id,
            "ts": ts0,
            "ts_end": ts1,
            "duration_ms": int(max(0.0, (ts1 - ts0) * 1000.0)),
            "tool": self.name,
            "start_url": start_url,
            "domain": scope.domain,
            "domain_key": scope.domain_key,
            "thread_title": thread_title,
            "thread_id": scope.thread_id,
            "max_pages": int(max_pages),
            "delay_ms": int(delay_ms),
            "respect_robots": True,
            "policy_snapshot": {
                "allow_all_hosts": bool(getattr(policy, "allow_all_hosts", False)),
                "allowed_domains": list(getattr(policy, "allowed_domains", ()) or ()),
                "allowed_suffixes": list(getattr(policy, "allowed_host_suffixes", ()) or ()),
                "denied_domains": list(getattr(policy, "denied_domains", ()) or ()),
                "session_allowed_domains": list(session_allowed),
            },
            "status": status,
            "partial": bool(errors or blocked),
            "pages_ok": int(len([p for p in pages if isinstance(p, dict) and str(p.get("file") or "").startswith("page_")])),
            "pages_failed": int(len(errors)),
            "pages": pages,
            "blocked": blocked,
            "errors": errors,
            "docs_ingested": 0,
            "docs_skipped": 0,
            "chunks_total": 0,
        }
        _atomic_write_json(base_dir / "manifest.json", manifest)

        return {
            "ok": True,
            "status": status,
            "start_url": start_url,
            "manifest_id": manifest_id,
            "domain": scope.domain,
            "domain_key": scope.domain_key,
            "thread_title": thread_title,
            "pages_ok": manifest["pages_ok"],
            "pages_failed": manifest["pages_failed"],
            "partial": bool(manifest["partial"]),
            "blocked": blocked,
            "errors": errors,
            "ts": ts0,
        }


class TibiaLearnTool(Tool):
    name = "tibia.learn"
    description = "Search + ingest bounded forum threads from configured Tibia sources, writing per-thread manifests for Agent ingestion"
    args = (
        ToolArgument("query", str, "Research query", required=True),
        ToolArgument("max_threads", int, "Max threads to ingest (default from config)", required=False, default=0),
        ToolArgument("max_pages_per_thread", int, "Max pages per thread (default from config)", required=False, default=0),
        ToolArgument("delay_ms", int, "Delay between page fetches (default from config)", required=False, default=0),
        ToolArgument("reason", str, "Reason for research", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        q = str(args.get("query") or "").strip()
        if not q:
            raise ToolExecutionError("query is required.")
        domains, domain_enabled, meta = _tibia_sources_cfg(ctx.cfg)
        if not bool(meta.get("enabled")):
            return {"ok": True, "status": "disabled", "query": q, "manifest_ids": [], "threads": [], "ts": time.time()}

        max_threads_cfg = int(meta.get("max_threads") or 5)
        max_pages_cfg = int(meta.get("max_pages_per_thread") or 5)
        delay_cfg = int(meta.get("default_delay_ms") or 500)
        max_threads = int(args.get("max_threads") or 0) or max_threads_cfg
        max_pages = int(args.get("max_pages_per_thread") or 0) or max_pages_cfg
        delay_ms = int(args.get("delay_ms") or 0) or delay_cfg
        max_threads = max(1, min(max_threads, 20))
        max_pages = max(1, min(max_pages, 20))
        delay_ms = max(0, min(delay_ms, 5000))

        search_out = TibiaSearchSourcesTool().run(ctx, {"query": q, "k": 8, "reason": str(args.get("reason") or "")})
        results = search_out.get("results") if isinstance(search_out, dict) else []
        threads: list[str] = []
        if isinstance(results, list):
            for it in results:
                if not isinstance(it, dict):
                    continue
                url = str(it.get("url") or "").strip()
                if not url:
                    continue
                if "/threads/" not in url:
                    continue
                host = normalize_host(urllib.parse.urlparse(url).hostname or "")
                key = _pick_domain_key(host, domains=domains)
                if not key or not domain_enabled.get(key, True):
                    continue
                threads.append(url)
                if len(threads) >= max_threads:
                    break
        # Deterministic dedupe.
        seen: set[str] = set()
        threads_u: list[str] = []
        for u in threads:
            if u in seen:
                continue
            seen.add(u)
            threads_u.append(u)

        manifest_ids: list[str] = []
        thread_reports: list[dict[str, Any]] = []
        for u in threads_u:
            out = TibiaIngestThreadTool().run(ctx, {"start_url": u, "max_pages": max_pages, "delay_ms": delay_ms, "reason": str(args.get("reason") or "")})
            mid = out.get("manifest_id") if isinstance(out, dict) else None
            if isinstance(mid, str) and mid.strip():
                manifest_ids.append(mid)
            thread_reports.append(
                {
                    "start_url": u,
                    "status": out.get("status") if isinstance(out, dict) else "error",
                    "manifest_id": mid,
                    "domain_key": out.get("domain_key") if isinstance(out, dict) else None,
                    "thread_title": out.get("thread_title") if isinstance(out, dict) else None,
                    "pages_ok": out.get("pages_ok") if isinstance(out, dict) else None,
                    "partial": out.get("partial") if isinstance(out, dict) else None,
                }
            )

        return {
            "ok": True,
            "status": "ok",
            "query": q,
            "manifest_ids": manifest_ids,
            "threads": thread_reports,
            "ts": time.time(),
        }
