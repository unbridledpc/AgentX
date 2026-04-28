from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Any

from agentx.core.html_extract import extract_readable_text, extract_tibia_monster
from agentx.core.web_policy import WebPolicy, is_allowed_url, normalize_host, registrable_domain
from agentx.tools.base import Tool, ToolArgument, ToolExecutionError

# Reuse the existing fetch/crawl primitives so policy, redirect handling, and byte caps remain consistent.
from agentx.tools.web import _extract_links, _fetch_html


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in patterns or []:
        if not isinstance(p, str):
            continue
        s = p.strip()
        if not s:
            continue
        try:
            out.append(re.compile(s, flags=re.IGNORECASE))
        except re.error as e:
            raise ToolExecutionError(f"Invalid regex pattern {s!r}: {e}")
    return out


def _matches_any(url: str, pats: list[re.Pattern[str]]) -> bool:
    if not pats:
        return True
    return any(p.search(url) for p in pats)


def _matches_none(url: str, pats: list[re.Pattern[str]]) -> bool:
    if not pats:
        return True
    return not any(p.search(url) for p in pats)


class WebIngestCrawlTool(Tool):
    name = "web.ingest_crawl"
    description = "Crawl within policy + scope, extract readable/structured text, and write an ingest manifest for Agent memory ingestion"
    args = (
        ToolArgument("start_url", str, "Start URL", required=True),
        ToolArgument("max_pages", int, "Max pages to fetch (default 50, hard-capped)", required=False, default=50),
        ToolArgument("max_depth", int, "Max link depth (default 2, hard-capped)", required=False, default=2),
        ToolArgument("delay_ms", int, "Delay between requests (default 250ms, clamped)", required=False, default=250),
        ToolArgument("include_patterns", list, "Regex allowlist applied to URLs (any match)", required=False, default=[]),
        ToolArgument("exclude_patterns", list, "Regex denylist applied to URLs (any match)", required=False, default=[]),
        ToolArgument("tag_prefix", str, "Tag prefix (default: untrusted:web)", required=False, default="untrusted:web"),
        ToolArgument("collection", str, "Collection name (used in tags)", required=False, default="tibia"),
        ToolArgument("extract_mode", str, "Extraction mode: readable_text|tibia_monster", required=False, default="tibia_monster"),
        ToolArgument("write_manifest", bool, "Write a manifest under data/ingest/manifests", required=False, default=True),
        ToolArgument("reason", str, "Reason for ingestion crawl", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        start_url = (args.get("start_url") or "").strip()
        if not start_url:
            raise ToolExecutionError("start_url is required.")

        max_pages = int(args.get("max_pages") or 50)
        max_depth = int(args.get("max_depth") or 2)
        delay_ms = int(args.get("delay_ms") or 250)
        max_pages = max(1, min(max_pages, 200))
        max_depth = max(0, min(max_depth, 5))
        delay_ms = max(0, min(delay_ms, 5000))

        extract_mode = (args.get("extract_mode") or "tibia_monster").strip()
        if extract_mode not in ("readable_text", "tibia_monster"):
            raise ToolExecutionError("extract_mode must be one of: readable_text, tibia_monster")

        include_pats = _compile_patterns(args.get("include_patterns") if isinstance(args.get("include_patterns"), list) else [])
        exclude_pats = _compile_patterns(args.get("exclude_patterns") if isinstance(args.get("exclude_patterns"), list) else [])

        cfg = ctx.cfg
        policy = WebPolicy(
            allow_all_hosts=bool(getattr(cfg.web, "policy_allow_all_hosts", False)),
            allowed_host_suffixes=tuple(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ()),
            allowed_domains=tuple(getattr(cfg.web, "policy_allowed_domains", ()) or ()),
            denied_domains=tuple(getattr(cfg.web, "policy_denied_domains", ()) or ()),
        )
        session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())

        ok, why = is_allowed_url(start_url, policy=policy, session_allowed_domains=session_allowed)
        if not ok:
            raise ToolExecutionError(f"Start URL blocked by policy: {why}")

        start_host = normalize_host(urllib.parse.urlparse(start_url).hostname or "")
        if not start_host:
            raise ToolExecutionError("start_url must include a hostname.")
        start_regdom = registrable_domain(start_host) or start_host

        # Crawl scope: within the start registrable domain, plus any explicitly allowed domains (policy + session).
        explicit_domains = set(str(d).strip().lower().rstrip(".") for d in (policy.allowed_domains or ()))
        explicit_domains |= set(str(d).strip().lower().rstrip(".") for d in (session_allowed or ()))
        allowed_regdoms = {start_regdom}
        for d in sorted(explicit_domains):
            rd = registrable_domain(d) or d
            if rd:
                allowed_regdoms.add(rd)

        visited = 0
        pages_ingested = 0
        skipped: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        pages: list[dict[str, Any]] = []

        queue: deque[tuple[str, int]] = deque([(start_url, 0)])
        seen: set[str] = set()

        while queue and visited < max_pages:
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            url_s = (url or "").strip()
            if not url_s:
                continue

            # URL-level include/exclude patterns.
            if not _matches_any(url_s, include_pats):
                skipped.append({"url": url_s, "reason": "Excluded by include_patterns."})
                continue
            if not _matches_none(url_s, exclude_pats):
                skipped.append({"url": url_s, "reason": "Excluded by exclude_patterns."})
                continue

            # Policy gate (fail-closed). This duplicates tool fetch policy checks intentionally.
            ok2, why2 = is_allowed_url(url_s, policy=policy, session_allowed_domains=session_allowed)
            if not ok2:
                skipped.append({"url": url_s, "reason": why2})
                continue

            host = normalize_host(urllib.parse.urlparse(url_s).hostname or "")
            regdom = registrable_domain(host) or host
            if regdom and regdom not in allowed_regdoms:
                skipped.append({"url": url_s, "reason": "Outside crawl scope (registrable domain mismatch)."})
                continue

            try:
                final_url, html_text, ts = _fetch_html(url_s, ctx=ctx)
            except Exception as e:
                errors.append({"url": url_s, "error": str(e)})
                continue

            visited += 1
            if delay_ms:
                time.sleep(delay_ms / 1000.0)

            # Expand links (BFS).
            if depth < max_depth:
                for link in _extract_links(html_text, final_url):
                    try:
                        p = urllib.parse.urlparse(link)
                    except Exception:
                        continue
                    if p.scheme not in ("http", "https"):
                        continue
                    link_host = normalize_host(p.hostname or "")
                    link_regdom = registrable_domain(link_host) or link_host
                    if link_regdom and link_regdom not in allowed_regdoms:
                        continue
                    if link not in seen:
                        queue.append((link, depth + 1))

            # Extract content.
            if extract_mode == "readable_text":
                raw_text = extract_readable_text(html_text)
                structured = None
                content_type = "page"
                confidence = 0.35 if raw_text else 0.1
            else:
                structured = extract_tibia_monster(html_text, url=final_url)
                raw_text = str(structured.get("raw_text") or "")
                content_type = "monster" if structured.get("name") else "page"
                try:
                    confidence = float(structured.get("confidence") or 0.2)
                except Exception:
                    confidence = 0.2

            raw_text = (raw_text or "").strip()
            if not raw_text:
                skipped.append({"url": final_url, "reason": "No extractable text."})
                continue

            # Hard cap extracted text length (keeps manifest bounded and memory ingestion predictable).
            if len(raw_text) > 200_000:
                raw_text = raw_text[:200_000] + "\n...truncated...\n"

            content_sha256 = hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest()
            pages_ingested += 1
            pages.append(
                {
                    "url": final_url,
                    "ts": float(ts),
                    "extract_mode": extract_mode,
                    "content_type": content_type,
                    "raw_text": raw_text,
                    "structured": structured if isinstance(structured, dict) else None,
                    "confidence": float(confidence),
                    "content_sha256": content_sha256,
                    "doc_id": None,  # Filled by the Agent ingestion hook.
                    "dedupe": None,  # Filled by the Agent ingestion hook.
                }
            )

        ts_out = time.time()
        write_manifest = bool(args.get("write_manifest", True))
        manifest_path: str | None = None
        if write_manifest:
            ingest_dir = Path(cfg.paths.data_dir) / "ingest" / "manifests"
            stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(ts_out))
            hid = hashlib.sha256(f"{start_url}|{ts_out}".encode("utf-8", errors="ignore")).hexdigest()[:12]
            manifest_id = f"{stamp}_{hid}"
            path = ingest_dir / f"{manifest_id}.json"
            _atomic_write_json(
                path,
                {
                    "id": manifest_id,
                    "ts": ts_out,
                    "tool": self.name,
                    "args": {k: args.get(k) for k in ("start_url", "max_pages", "max_depth", "delay_ms", "include_patterns", "exclude_patterns", "tag_prefix", "collection", "extract_mode", "write_manifest")},
                    "start_url": start_url,
                    "scope": {"start_regdom": start_regdom, "allowed_regdoms": sorted(allowed_regdoms)},
                    "pages_visited": int(visited),
                    "pages_ingested": int(pages_ingested),
                    "docs_ingested": 0,
                    "skipped": list(skipped),
                    "errors": list(errors),
                    "pages": pages,
                },
            )
            manifest_path = str(path)

        return {
            "start_url": start_url,
            "pages_visited": int(visited),
            "pages_ingested": int(pages_ingested),
            "docs_ingested": 0,
            "skipped": list(skipped),
            "errors": list(errors),
            "manifest_path": manifest_path,
            "ts": float(ts_out),
        }

