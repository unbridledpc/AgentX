from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
import os
import urllib.error
import urllib.parse
import urllib.request
from html import unescape as _html_unescape
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sol.core.html_extract import extract_text_and_meta
from sol.core.web_policy import WebPolicy, is_allowed_url, normalize_host, registrable_domain
from sol.tools.base import Tool, ToolArgument, ToolExecutionError
from sol.tools.web import WebAccessDenied, _read_limited, _validate_resolved_ips


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _decode_bytes(raw: bytes, content_type: str) -> str:
    m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type or "", re.IGNORECASE)
    if m:
        enc = m.group(1)
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def _policy_from_cfg(cfg) -> WebPolicy:
    return WebPolicy(
        allow_all_hosts=bool(getattr(cfg.web, "policy_allow_all_hosts", False)),
        allowed_host_suffixes=tuple(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ()),
        allowed_domains=tuple(getattr(cfg.web, "policy_allowed_domains", ()) or ()),
        denied_domains=tuple(getattr(cfg.web, "policy_denied_domains", ()) or ()),
    )


def _extract_links(html_text: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', html_text or "", flags=re.IGNORECASE):
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
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


@dataclass(frozen=True)
class HtmlFetchResult:
    url: str
    status: int
    content_type: str
    html: str
    bytes: int
    ts: float


def _fetch_html_checked(url: str, *, ctx) -> HtmlFetchResult:
    """Fetch HTML with web.policy + redirect checks (fails closed)."""
    cfg = ctx.cfg
    if not cfg.web.enabled:
        raise WebAccessDenied("Web access disabled.")

    u = (url or "").strip()
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise WebAccessDenied("Only http/https URLs are allowed.")
    if not parsed.netloc:
        raise WebAccessDenied("URL must include a hostname.")

    policy = _policy_from_cfg(cfg)
    session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
    ok, why = is_allowed_url(u, policy=policy, session_allowed_domains=session_allowed)
    if not ok:
        raise WebAccessDenied(why)

    host = normalize_host(parsed.hostname or "")
    if cfg.web.block_private_networks:
        _validate_resolved_ips(host)

    current = u
    redirects = 0
    while True:
        req = urllib.request.Request(
            current,
            headers={
                "User-Agent": cfg.web.user_agent,
                "Accept": "text/html, */*;q=0.1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=cfg.web.timeout_s) as resp:
                status = int(getattr(resp, "status", 200))
                content_type = (resp.headers.get("Content-Type") or "").strip()
                location = resp.headers.get("Location")
                raw, truncated = _read_limited(resp, max_bytes=max(1, int(cfg.web.max_bytes)))
                final_url = getattr(resp, "geturl", lambda: current)()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise ToolExecutionError(f"HTTP {e.code}: {body[:2000]}")
        except Exception as e:
            raise ToolExecutionError(f"Request failed: {e}")

        if 300 <= status < 400:
            if not location:
                raise ToolExecutionError("Redirect without Location header.")
            redirects += 1
            if redirects > max(0, int(cfg.web.max_redirects)):
                raise ToolExecutionError("Too many redirects.")
            next_url = urllib.parse.urljoin(current, location)
            ok2, why2 = is_allowed_url(next_url, policy=policy, session_allowed_domains=session_allowed)
            if not ok2:
                raise WebAccessDenied(f"Redirect blocked: {why2}")
            next_parsed = urllib.parse.urlparse(next_url)
            next_host = normalize_host(next_parsed.hostname or "")
            if cfg.web.block_private_networks:
                _validate_resolved_ips(next_host)
            current = next_url
            continue

        html = _decode_bytes(raw, content_type or "")
        if truncated and len(html) > 200_000:
            html = html[:200_000] + "\n...truncated...\n"
        return HtmlFetchResult(url=str(final_url or current), status=status, content_type=content_type or "", html=html, bytes=len(raw), ts=time.time())


def _robots_url(url: str) -> str:
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    return urllib.parse.urljoin(base, "/robots.txt")


def _parse_robots(text: str, *, user_agent: str) -> list[str]:
    """Very small robots.txt parser (best-effort, conservative).

    Supports:
    - User-agent: *
    - Disallow: /prefix
    """
    ua = (user_agent or "").strip().lower()
    disallow: list[str] = []
    active = False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("user-agent:"):
            v = line.split(":", 1)[1].strip().lower()
            active = (v == "*") or (ua and v and v in ua)
            continue
        if active and line.lower().startswith("disallow:"):
            v = line.split(":", 1)[1].strip()
            if v:
                disallow.append(v)
    return disallow


def _robots_allows(url: str, *, disallow: list[str]) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return True
    path = p.path or "/"
    for d in disallow:
        if d == "/":
            return False
        if path.startswith(d):
            return False
    return True


def _is_github_repo_root(url: str) -> tuple[bool, str | None, str | None]:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False, None, None
    if normalize_host(p.hostname or "") != "github.com":
        return False, None, None
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2:
        return False, None, None
    owner, repo = parts[0], parts[1]
    # Repo root or anything under it (we still treat it as a repo).
    return True, owner, repo


def _detect_adapter(start_url: str) -> str:
    try:
        p = urllib.parse.urlparse(start_url)
    except Exception:
        return "generic"
    host = normalize_host(p.hostname or "")
    path = p.path or ""
    if host == "github.com":
        return "github"
    if host in ("reddit.com", "www.reddit.com", "old.reddit.com"):
        return "reddit"
    if host.endswith("wikipedia.org") or host.endswith("fandom.com") or "/wiki/" in path or "mediawiki" in host:
        return "mediawiki"
    return "generic"


def _host_for_url(url: str) -> str:
    try:
        return normalize_host(urllib.parse.urlparse(url).hostname or "")
    except Exception:
        return ""


def _blocked_entry(*, url: str, reason: str, suggest_allow_domain: bool) -> dict[str, Any]:
    host = _host_for_url(url)
    out: dict[str, Any] = {"url": url, "reason": reason}
    if host:
        out["host"] = host
        if suggest_allow_domain:
            out["suggestion"] = {"action": "allow_domain", "domain": host}
    return out


def _parse_github_branch_and_subpath(url: str) -> tuple[str | None, str | None]:
    """Backward-compatible parse of GitHub URLs for (branch, subpath).

    Supports:
    - https://github.com/<owner>/<repo>
    - https://github.com/<owner>/<repo>/tree/<branch>/<path...>
    - https://github.com/<owner>/<repo>/blob/<branch>/<path...>
    """

    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return None, None
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2:
        return None, None
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        branch = parts[3]
        rest = "/".join(parts[4:]).strip("/") if len(parts) > 4 else ""
        return branch or None, rest or None
    return None, None


def _parse_github_ref_kind_and_path(url: str) -> tuple[str | None, str | None, str | None]:
    """Parse GitHub URLs for (kind, branch, path).

    kind: "tree" | "blob" | None
    """
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return None, None, None
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2:
        return None, None, None
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        kind = parts[2]
        branch = parts[3]
        rest = "/".join(parts[4:]).strip("/") if len(parts) > 4 else ""
        return kind, (branch or None), (rest or None)
    return None, None, None


def _glob_any(path: str, globs: tuple[str, ...]) -> bool:
    p = (path or "").strip().lstrip("/")
    if not p:
        return False
    for g in globs or ():
        gg = (g or "").strip()
        if not gg:
            continue
        if fnmatch.fnmatchcase(p.lower(), gg.lower()):
            return True
    return False


def _score_repo_path(path: str, *, prefer_docs: bool) -> int:
    p = (path or "").lstrip("/").strip()
    low = p.lower()
    score = 0
    if low.startswith(("docs/", "doc/", "documentation/")):
        score += 90 if prefer_docs else 70
    if low.startswith(".github/"):
        score += 10
    if low in ("readme.md", "readme.rst", "readme.txt") or low.startswith("readme."):
        score += 120
    if low.endswith(".md"):
        score += 60
    if low.endswith((".txt", ".rst")):
        score += 45
    if low.endswith((".toml", ".yaml", ".yml", ".json")):
        score += 35
    if low in ("pyproject.toml", "requirements.txt", "package.json", "cargo.toml", "go.mod"):
        score += 75
    # Prefer shorter, more top-level docs.
    score -= min(30, low.count("/") * 5)
    return score


def _github_select_candidate_paths(
    *,
    tree: list[dict[str, Any]],
    subpath: str | None,
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
    prefer_docs: bool,
    max_files: int,
) -> tuple[list[str], dict[str, int]]:
    prefix = (subpath or "").strip().strip("/")
    if prefix:
        prefix = prefix + "/"

    stats: dict[str, int] = {"files_considered": 0, "files_filtered_out": 0}
    out: list[tuple[int, str]] = []
    for item in tree or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "blob":
            continue
        path = str(item.get("path") or "").lstrip("/")
        if not path:
            continue
        if prefix and not path.startswith(prefix):
            continue
        stats["files_considered"] += 1
        if _glob_any(path, exclude_globs):
            stats["files_filtered_out"] += 1
            continue
        if include_globs and not _glob_any(path, include_globs):
            stats["files_filtered_out"] += 1
            continue
        # Avoid obvious binary content.
        low = path.lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip")):
            stats["files_filtered_out"] += 1
            continue
        # Avoid minified artifacts.
        if ".min." in low or low.endswith(".map"):
            stats["files_filtered_out"] += 1
            continue
        out.append((_score_repo_path(path, prefer_docs=prefer_docs), path))

    out.sort(key=lambda t: (-t[0], t[1].lower()))
    return [p for _s, p in out[: max(1, int(max_files))]], stats


def _fetch_json_checked(url: str, *, ctx) -> tuple[dict[str, Any], str, float]:
    """Fetch JSON with web.policy + redirect checks (fails closed)."""
    cfg = ctx.cfg
    if not cfg.web.enabled:
        raise WebAccessDenied("Web access disabled.")

    u = (url or "").strip()
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise WebAccessDenied("Only http/https URLs are allowed.")
    if not parsed.netloc:
        raise WebAccessDenied("URL must include a hostname.")

    policy = _policy_from_cfg(cfg)
    session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
    ok, why = is_allowed_url(u, policy=policy, session_allowed_domains=session_allowed)
    if not ok:
        raise WebAccessDenied(why)

    host = normalize_host(parsed.hostname or "")
    if cfg.web.block_private_networks:
        _validate_resolved_ips(host)

    current = u
    redirects = 0
    while True:
        headers = {
            "User-Agent": cfg.web.user_agent,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
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
                status = int(getattr(resp, "status", 200))
                location = resp.headers.get("Location")
                raw, _truncated = _read_limited(resp, max_bytes=max(1, int(cfg.web.max_bytes)))
                final_url = getattr(resp, "geturl", lambda: current)()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise ToolExecutionError(f"HTTP {e.code}: {body[:2000]}")
        except Exception as e:
            raise ToolExecutionError(f"Request failed: {e}")

        if 300 <= status < 400:
            if not location:
                raise ToolExecutionError("Redirect without Location header.")
            redirects += 1
            if redirects > max(0, int(cfg.web.max_redirects)):
                raise ToolExecutionError("Too many redirects.")
            next_url = urllib.parse.urljoin(current, location)
            ok2, why2 = is_allowed_url(next_url, policy=policy, session_allowed_domains=session_allowed)
            if not ok2:
                raise WebAccessDenied(f"Redirect blocked: {why2}")
            current = next_url
            continue

        try:
            data = json.loads(_decode_bytes(raw, "application/json"))
        except Exception as e:
            raise ToolExecutionError(f"JSON parse failed: {e}")
        if not isinstance(data, dict):
            raise ToolExecutionError("JSON response is not an object.")
        return data, str(final_url or current), time.time()


def _github_default_branch(owner: str, repo: str, *, ctx) -> str | None:
    data, _final, _ts = _fetch_json_checked(f"https://api.github.com/repos/{owner}/{repo}", ctx=ctx)
    b = data.get("default_branch")
    if isinstance(b, str) and b.strip():
        return b.strip()
    return None


def _github_tree(owner: str, repo: str, branch: str, *, ctx) -> list[dict[str, Any]]:
    data, _final, _ts = _fetch_json_checked(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1", ctx=ctx)
    tree = data.get("tree")
    if not isinstance(tree, list):
        raise ToolExecutionError("GitHub tree response missing tree[].")
    out: list[dict[str, Any]] = []
    for item in tree:
        if isinstance(item, dict):
            out.append(item)
    return out


def _github_raw_candidates(owner: str, repo: str) -> list[str]:
    # Prefer README + docs README; try main then master.
    bases = []
    for branch in ("main", "master"):
        bases.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md")
        bases.append(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/docs/README.md")
    return bases


def _github_contents_url(owner: str, repo: str, *, path: str, ref: str) -> str:
    p = (path or "").strip().lstrip("/")
    if p:
        p_q = urllib.parse.quote(p, safe="/")
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{p_q}?ref={urllib.parse.quote(ref, safe='')}"
    return f"https://api.github.com/repos/{owner}/{repo}/contents?ref={urllib.parse.quote(ref, safe='')}"


def _github_is_preferred_doc_file(path: str) -> bool:
    p = (path or "").strip().lstrip("/")
    if not p:
        return False
    low = p.lower()
    name = low.rsplit("/", 1)[-1]

    if name.startswith("readme"):
        return True
    if name in (
        "license",
        "license.md",
        "copying",
        "copying.md",
        "contributing.md",
        "code_of_conduct.md",
        "security.md",
        "changelog.md",
        "install.md",
        "authors",
    ):
        return True
    if low.endswith((".md", ".rst", ".txt")):
        return True
    if name in (
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "cargo.toml",
        "go.mod",
        "makefile",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
    ):
        return True
    return False


def _github_list_candidate_paths_contents(
    *,
    owner: str,
    repo: str,
    ref: str,
    subpath: str | None,
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
    prefer_docs: bool,
    max_files: int,
    max_depth: int,
    max_dirs: int,
    ctx,
) -> tuple[list[str], list[dict[str, str]], dict[str, int]]:
    """List candidate docs-ish files via GitHub Contents API (bounded BFS).

    This avoids requiring a full recursive tree listing (which can exceed max_bytes).
    Returns (paths, errors, stats).
    """
    errors: list[dict[str, str]] = []
    stats: dict[str, int] = {"dirs_visited": 0, "max_depth_reached": 0, "files_considered": 0, "files_filtered_out": 0}

    max_files_i = max(1, int(max_files))
    max_depth_i = max(0, int(max_depth))
    max_dirs_i = max(1, int(max_dirs))

    prefix = (subpath or "").strip().strip("/")
    start_dirs: list[tuple[str, int]] = []
    if prefix:
        start_dirs.append((prefix, 0))
    else:
        start_dirs.extend([("", 0), ("docs", 1), ("doc", 1), ("documentation", 1), (".github", 1)])

    allowed_top_dirs = {"docs", "doc", "documentation", ".github"}
    seen_dirs: set[str] = set()
    queue: deque[tuple[str, int]] = deque(start_dirs)
    scored: list[tuple[int, str]] = []

    while queue and len(scored) < max_files_i * 4 and stats["dirs_visited"] < max_dirs_i:
        cur, depth = queue.popleft()
        cur_norm = (cur or "").strip().lstrip("/")
        if cur_norm in seen_dirs:
            continue
        seen_dirs.add(cur_norm)
        stats["dirs_visited"] += 1
        stats["max_depth_reached"] = max(stats["max_depth_reached"], int(depth))

        url = _github_contents_url(owner, repo, path=cur_norm, ref=ref)
        data, final_url, _ts, err = _fetch_json_checked_soft(url, ctx=ctx)
        if data is None:
            # Missing optional docs dirs is common; treat 404 as non-fatal/noise only for those.
            if err and err.startswith("http_404"):
                if not prefix and cur_norm in ("docs", "doc", "documentation", ".github"):
                    continue
            errors.append({"url": final_url, "error": err or "unknown"})
            continue

        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            items = [data]
        else:
            errors.append({"url": final_url, "error": "unexpected_json_shape"})
            continue

        items.sort(key=lambda d: str(d.get("path") or "").lower())
        for it in items:
            typ = str(it.get("type") or "").lower()
            p = str(it.get("path") or "").strip().lstrip("/")
            if not p:
                continue
            if typ == "dir":
                if depth >= max_depth_i:
                    continue
                # Only descend into docs-like dirs unless the user provided a subpath.
                if prefix:
                    if p.startswith(prefix.rstrip("/") + "/"):
                        queue.append((p, depth + 1))
                else:
                    top = p.split("/", 1)[0].lower()
                    if top in allowed_top_dirs:
                        queue.append((p, depth + 1))
                continue
            if typ != "file":
                continue

            stats["files_considered"] += 1
            if _glob_any(p, exclude_globs):
                stats["files_filtered_out"] += 1
                continue
            if include_globs and not _glob_any(p, include_globs):
                stats["files_filtered_out"] += 1
                continue
            low = p.lower()
            if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip")):
                stats["files_filtered_out"] += 1
                continue
            if ".min." in low or low.endswith(".map"):
                stats["files_filtered_out"] += 1
                continue
            scored.append((_score_repo_path(p, prefer_docs=prefer_docs), p))

    scored.sort(key=lambda t: (-int(t[0]), str(t[1]).lower()))
    return [p for _s, p in scored[: max(0, max_files_i)]], errors, stats


def _github_tree_url(owner: str, repo: str, ref: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(ref, safe='')}?recursive=1"


def _github_tree_soft(*, owner: str, repo: str, ref: str, ctx) -> tuple[list[dict[str, Any]] | None, str, str | None]:
    """Best-effort Trees API fetch (never raises).

    Returns (tree|None, final_url, err_code|None).
    """
    url = _github_tree_url(owner, repo, ref)
    data, final_url, _ts, err = _fetch_json_checked_soft(url, ctx=ctx)
    if data is None:
        return None, final_url, err or "unknown"
    if not isinstance(data, dict):
        return None, final_url, "unexpected_json_shape"
    tree = data.get("tree")
    if not isinstance(tree, list):
        return None, final_url, "missing_tree"
    out: list[dict[str, Any]] = [t for t in tree if isinstance(t, dict)]
    return out, final_url, None


def _looks_like_html(text: str) -> bool:
    s = (text or "").lstrip()[:64].lower()
    return s.startswith("<!doctype html") or s.startswith("<html")


def _fetch_json_checked_soft(url: str, *, ctx) -> tuple[Any | None, str, float, str | None]:
    """Best-effort JSON fetch.

    Returns (data|None, final_url, ts, error|None). When data is None, error is a short machine-friendly code.
    """
    cfg = ctx.cfg
    if not cfg.web.enabled:
        return None, url, time.time(), "web_disabled"

    u = (url or "").strip()
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, u, time.time(), "bad_url"

    policy = _policy_from_cfg(cfg)
    session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())
    ok, why = is_allowed_url(u, policy=policy, session_allowed_domains=session_allowed)
    if not ok:
        return None, u, time.time(), f"blocked:{why}"

    host = normalize_host(parsed.hostname or "")
    if cfg.web.block_private_networks:
        _validate_resolved_ips(host)

    current = u
    redirects = 0
    while True:
        req = urllib.request.Request(
            current,
            headers={
                "User-Agent": cfg.web.user_agent,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=cfg.web.timeout_s) as resp:
                status = int(getattr(resp, "status", 200))
                content_type = (resp.headers.get("Content-Type") or "").strip()
                location = resp.headers.get("Location")
                raw, truncated = _read_limited(resp, max_bytes=max(1, int(cfg.web.max_bytes)))
                final_url = getattr(resp, "geturl", lambda: current)()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            return None, current, time.time(), f"http_{e.code}:{body[:200]}"
        except Exception as e:
            return None, current, time.time(), f"request_failed:{e}"

        if 300 <= status < 400:
            if not location:
                return None, str(final_url or current), time.time(), "redirect_no_location"
            redirects += 1
            if redirects > max(0, int(cfg.web.max_redirects)):
                return None, str(final_url or current), time.time(), "too_many_redirects"
            next_url = urllib.parse.urljoin(current, location)
            ok2, why2 = is_allowed_url(next_url, policy=policy, session_allowed_domains=session_allowed)
            if not ok2:
                return None, next_url, time.time(), f"blocked_redirect:{why2}"
            current = next_url
            continue

        decoded = _decode_bytes(raw, content_type or "application/json")
        if truncated:
            return None, str(final_url or current), time.time(), "max_bytes"
        if "application/json" not in (content_type or "").lower():
            return None, str(final_url or current), time.time(), "non_json_content_type"
        if _looks_like_html(decoded):
            return None, str(final_url or current), time.time(), "html_response"
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError as e:
            if "unterminated string" in str(e).lower():
                return None, str(final_url or current), time.time(), "unterminated_string"
            return None, str(final_url or current), time.time(), f"json_parse:{e}"
        return data, str(final_url or current), time.time(), None


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in patterns or []:
        if not isinstance(p, str):
            continue
        s = p.strip()
        if not s:
            continue
        out.append(re.compile(s, flags=re.IGNORECASE))
    return out


def _matches_any(url: str, pats: list[re.Pattern[str]]) -> bool:
    if not pats:
        return True
    return any(p.search(url) for p in pats)


def _matches_none(url: str, pats: list[re.Pattern[str]]) -> bool:
    if not pats:
        return True
    return not any(p.search(url) for p in pats)


def _strip_tags(html_text: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", html_text or "")
    t = re.sub(r"(?is)<[^>]+>", " ", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return _html_unescape(t).strip()


def _clean_html_for_text(html_text: str) -> str:
    # Cheap pre-clean to improve robustness across sites; extract_text_and_meta does the heavy lifting.
    t = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", "", html_text or "")
    t = re.sub(r"(?is)<(nav|footer|header|aside).*?>.*?</\\1>", "", t)
    return t


def _mediawiki_is_allowed_link(u: str, *, base_host: str) -> bool:
    try:
        p = urllib.parse.urlparse(u)
    except Exception:
        return False
    if normalize_host(p.hostname or "") != base_host:
        return False
    if p.scheme not in ("http", "https"):
        return False

    path = p.path or ""
    qs = urllib.parse.parse_qs(p.query or "")

    # Avoid edit/history/etc.
    action = (qs.get("action") or [None])[0]
    if isinstance(action, str) and action.lower() in ("edit", "history", "diff", "submit"):
        return False
    if "oldid" in qs or "diff" in qs:
        return False

    title = (qs.get("title") or [None])[0]
    title_s = str(title or "")

    # Prefer /wiki/ namespace (or title= in /w/index.php).
    if path.startswith("/wiki/"):
        tail = path[len("/wiki/") :]
        # Reject non-article namespaces.
        if any(tail.startswith(ns) for ns in ("Special:", "File:", "Template:", "Help:", "Talk:", "User:", "Portal:", "Draft:", "MediaWiki:")):
            return False
        return True
    if path.startswith("/w/index.php") and title_s:
        if any(title_s.startswith(ns) for ns in ("Special:", "File:", "Template:", "Help:", "Talk:", "User:", "Portal:", "Draft:", "MediaWiki:")):
            return False
        return True
    return False


def _to_old_reddit(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return url
    host = normalize_host(p.hostname or "")
    if host in ("reddit.com", "www.reddit.com"):
        return urllib.parse.urlunparse((p.scheme or "https", "old.reddit.com", p.path, p.params, p.query, p.fragment))
    return url


def _extract_reddit_post_text(html_text: str, *, max_comments: int) -> tuple[str, dict[str, Any]]:
    html_text = html_text or ""
    clean = _clean_html_for_text(html_text)

    title = None
    m = re.search(r'(?is)<a[^>]+class="title[^"]*"[^>]*>(.*?)</a>', clean)
    if m:
        title = _strip_tags(m.group(1))

    commentarea_idx = clean.lower().find('class="commentarea"')
    if commentarea_idx == -1:
        commentarea_idx = clean.lower().find('id="comments"')
    pre = clean if commentarea_idx == -1 else clean[:commentarea_idx]
    post_body = ""
    m2 = re.search(r'(?is)<div[^>]+class="md"[^>]*>(.*?)</div>', pre)
    if m2:
        post_body = _strip_tags(m2.group(1))

    comments_section = clean if commentarea_idx == -1 else clean[commentarea_idx:]
    comment_blocks = re.findall(r'(?is)<div[^>]+class="md"[^>]*>(.*?)</div>', comments_section)
    comments: list[str] = []
    for blk in comment_blocks:
        t = _strip_tags(blk)
        if not t:
            continue
        if post_body and t == post_body:
            continue
        comments.append(t)
        if len(comments) >= max(0, int(max_comments)):
            break

    parts: list[str] = []
    if title:
        parts.append(f"Title: {title}")
    if post_body:
        parts.append("")
        parts.append("Post:")
        parts.append(post_body)
    if comments:
        parts.append("")
        parts.append(f"Top comments ({len(comments)}):")
        for i, c in enumerate(comments, start=1):
            parts.append("")
            parts.append(f"[{i}] {c}")
    text_out = "\n".join(parts).strip()
    meta = {"adapter": "reddit", "title": title, "comments_extracted": len(comments)}
    return text_out, meta


class WebIngestUrlTool(Tool):
    name = "web.ingest_url"
    description = "Fetch or crawl a URL within web.policy, write an ingest manifest + page texts to disk (Agent ingests into Memory)"
    args = (
        ToolArgument("start_url", str, "Start URL", required=True),
        ToolArgument("mode", str, "Ingest mode: auto|repo|single|crawl", required=False, default="auto"),
        ToolArgument("max_pages", int, "Max pages to fetch (default 25, clamped)", required=False, default=25),
        ToolArgument("max_depth", int, "Max link depth (default 2, clamped)", required=False, default=2),
        ToolArgument("delay_ms", int, "Delay between requests (default 250ms, clamped)", required=False, default=250),
        ToolArgument("include_patterns", list, "Regex allowlist applied to URLs (any match)", required=False, default=[]),
        ToolArgument("exclude_patterns", list, "Regex denylist applied to URLs (any match)", required=False, default=[]),
        ToolArgument("include_globs", list, "Repo-path glob allowlist for GitHub repo ingestion (any match); overrides config", required=False, default=None),
        ToolArgument("exclude_globs", list, "Repo-path glob denylist for GitHub repo ingestion (any match); overrides config", required=False, default=None),
        ToolArgument("respect_robots", bool, "Respect robots.txt Disallow rules (best-effort)", required=False, default=True),
        ToolArgument("reason", str, "Reason for ingestion", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        start_url = (args.get("start_url") or "").strip()
        if not start_url:
            raise ToolExecutionError("start_url is required.")
        mode = (args.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "repo", "single", "crawl"):
            raise ToolExecutionError("mode must be one of: auto, repo, single, crawl")

        max_pages = max(1, min(int(args.get("max_pages") or 25), 200))
        max_depth = max(0, min(int(args.get("max_depth") or 2), 5))
        delay_ms = max(0, min(int(args.get("delay_ms") or 250), 5000))
        respect_robots = bool(args.get("respect_robots", True))

        include_pats = _compile_patterns(args.get("include_patterns") if isinstance(args.get("include_patterns"), list) else [])
        exclude_pats = _compile_patterns(args.get("exclude_patterns") if isinstance(args.get("exclude_patterns"), list) else [])

        policy = _policy_from_cfg(ctx.cfg)
        session_allowed = tuple(getattr(ctx, "web_session_allowed_domains", ()) or ())

        ts0 = time.time()
        manifest_id = hashlib.sha256(f"{start_url}|{ts0}".encode("utf-8", errors="ignore")).hexdigest()[:16]
        base_dir = Path(ctx.cfg.paths.data_dir) / "ingest" / manifest_id
        base_dir.mkdir(parents=True, exist_ok=True)

        blocked: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        pages_out: list[dict[str, Any]] = []
        providers_used: list[str] = []
        providers_failed: list[str] = []
        crawl_stats: dict[str, Any] = {"urls_visited": 0, "max_depth_reached": 0}
        repo_info: dict[str, Any] | None = None

        adapter = _detect_adapter(start_url)

        # Fail-closed on policy: do not fetch when blocked, but still write an audited manifest.
        start_allowed, start_block_reason = is_allowed_url(start_url, policy=policy, session_allowed_domains=session_allowed)
        if not start_allowed:
            blocked.append(_blocked_entry(url=start_url, reason=str(start_block_reason), suggest_allow_domain=True))

        # Determine effective mode (adapter-aware).
        effective = mode
        is_repo, owner, repo = _is_github_repo_root(start_url)
        gh_kind, gh_branch, gh_subpath = _parse_github_ref_kind_and_path(start_url) if is_repo else (None, None, None)
        if effective == "auto":
            if adapter == "github" and is_repo:
                effective = "repo"
            elif adapter == "mediawiki":
                effective = "crawl"
            elif adapter == "reddit":
                effective = "single"
            else:
                effective = "crawl" if max_pages > 1 and max_depth > 0 else "single"

        # robots.txt cache by registrable domain.
        robots_disallow: dict[str, list[str]] = {}

        def policy_check(u: str) -> tuple[bool, str]:
            ok2, why2 = is_allowed_url(u, policy=policy, session_allowed_domains=session_allowed)
            return ok2, why2

        def robots_allows(u: str) -> bool:
            if not respect_robots:
                return True
            host = normalize_host(urllib.parse.urlparse(u).hostname or "")
            reg = registrable_domain(host) or host
            if not reg:
                return True
            if reg not in robots_disallow:
                try:
                    ru = _robots_url(u)
                    ok3, why3 = policy_check(ru)
                    if not ok3:
                        # If robots is blocked by policy, proceed without robots info (fail-closed would block everything).
                        robots_disallow[reg] = []
                    else:
                        rob = _fetch_html_checked(ru, ctx=ctx)
                        robots_disallow[reg] = _parse_robots(rob.html, user_agent=str(ctx.cfg.web.user_agent))
                except Exception:
                    robots_disallow[reg] = []
            return _robots_allows(u, disallow=robots_disallow.get(reg, []))

        def ingest_one(u: str, *, index: int, want_links: bool) -> list[str]:
            ok4, why4 = policy_check(u)
            if not ok4:
                blocked.append(_blocked_entry(url=u, reason=str(why4), suggest_allow_domain=True))
                return []
            if not robots_allows(u):
                blocked.append(_blocked_entry(url=u, reason="Blocked by robots.txt (best-effort).", suggest_allow_domain=False))
                return []
            if not _matches_any(u, include_pats) or not _matches_none(u, exclude_pats):
                blocked.append(_blocked_entry(url=u, reason="Filtered by include/exclude patterns.", suggest_allow_domain=False))
                return []
            try:
                r = _fetch_html_checked(u, ctx=ctx)
                html = _clean_html_for_text(r.html)
                try:
                    text, meta = extract_text_and_meta(html)
                except Exception:
                    text, meta = "", {"title": None, "byline": None, "published_time": None, "extracted_with": "fallback", "word_count": None}
                text = (text or "").strip()
                if not text:
                    text = re.sub(r"\s+", " ", html)[:2000]
                title = meta.get("title") if isinstance(meta, dict) else None
                full_path = base_dir / f"page_{index:03d}.txt"
                full_path.write_text(text, encoding="utf-8")
                excerpt = text[:2000]
                pages_out.append(
                    {
                        "url": r.url,
                        "status": int(r.status),
                        "bytes": int(r.bytes),
                        "content_type": r.content_type,
                        "title": title,
                        "meta": meta,
                        "text_excerpt": excerpt,
                        "ts": float(r.ts),
                        "file": full_path.name,
                    }
                )
                if want_links:
                    return _extract_links(r.html, r.url)
            except Exception as e:
                errors.append({"url": u, "error": str(e)})
            return []

        def ingest_text_url(
            u: str,
            *,
            index: int,
            title_hint: str | None,
            extra_fields: dict[str, Any] | None = None,
            ignore_http_404: bool = False,
        ) -> str:
            # Repo/raw ingestion uses plain text endpoints; robots.txt isn't meaningful here.
            ok4, why4 = policy_check(u)
            if not ok4:
                blocked.append(_blocked_entry(url=u, reason=str(why4), suggest_allow_domain=True))
                return "blocked"
            if not _matches_any(u, include_pats) or not _matches_none(u, exclude_pats):
                blocked.append(_blocked_entry(url=u, reason="Filtered by include/exclude patterns.", suggest_allow_domain=False))
                return "filtered"
            try:
                from sol.tools.web import fetch_text as _fetch_text

                r = _fetch_text(u, ctx=ctx)
                text = (r.text or "").strip()
                if not text:
                    raise ToolExecutionError("Empty response.")
                meta = r.meta if isinstance(r.meta, dict) else None
                title = (meta or {}).get("title") if meta else None
                if not title and title_hint:
                    title = str(title_hint)
                full_path = base_dir / f"page_{index:03d}.txt"
                full_path.write_text(text, encoding="utf-8")
                pages_out.append(
                    {
                        "url": r.url,
                        "status": 200,
                        "bytes": len(text.encode("utf-8", errors="ignore")),
                        "content_type": r.content_type,
                        "title": title,
                        "meta": meta,
                        "text_excerpt": text[:2000],
                        "ts": float(r.ts),
                        "file": full_path.name,
                        **(extra_fields or {}),
                    }
                )
                return "ok"
            except WebAccessDenied as e:
                blocked.append(_blocked_entry(url=u, reason=str(e), suggest_allow_domain=True))
                return "blocked"
            except Exception as e:
                msg = str(e)
                if ignore_http_404 and msg.lower().startswith("http 404"):
                    return "missing"
                errors.append({"url": u, "error": msg})
                return "error"

        if start_allowed:
            if adapter == "github" and effective == "repo" and owner and repo:
                # GitHub: prefer Contents API BFS for folder/file URLs, with Trees API as an optional optimization.
                include_globs_arg = args.get("include_globs") if isinstance(args.get("include_globs"), list) else None
                exclude_globs_arg = args.get("exclude_globs") if isinstance(args.get("exclude_globs"), list) else None
                include_globs = tuple(str(s).strip() for s in (include_globs_arg if include_globs_arg is not None else (getattr(ctx.cfg.web, "ingest_include_globs", ()) or ())) if str(s).strip())
                exclude_globs = tuple(str(s).strip() for s in (exclude_globs_arg if exclude_globs_arg is not None else (getattr(ctx.cfg.web, "ingest_exclude_globs", ()) or ())) if str(s).strip())
                prefer_docs = bool(getattr(ctx.cfg.web, "ingest_prefer_docs", True))

                max_files_repo_cfg = int(getattr(ctx.cfg.web, "ingest_max_files_repo", getattr(ctx.cfg.web, "ingest_max_files", 80)) or 50)
                max_files_repo = max(1, min(max_files_repo_cfg, 500))
                max_files = max(1, min(max_pages, max_files_repo))

                max_depth_repo = int(getattr(ctx.cfg.web, "ingest_max_depth_repo", 3) or 3)
                max_dirs_repo = int(getattr(ctx.cfg.web, "ingest_max_dirs_repo", 200) or 200)

                branch = (gh_branch or "").strip() or None
                if not branch:
                    api = f"https://api.github.com/repos/{owner}/{repo}"
                    data, final_url, _ts, err = _fetch_json_checked_soft(api, ctx=ctx)
                    if isinstance(data, dict):
                        providers_used.append("github_api")
                        b = data.get("default_branch")
                        if isinstance(b, str) and b.strip():
                            branch = b.strip()
                    elif err and err.startswith("blocked:"):
                        providers_failed.append("github_api")
                        blocked.append(_blocked_entry(url=final_url, reason=err.split(":", 1)[1], suggest_allow_domain=True))
                    elif err:
                        providers_failed.append("github_api")
                        errors.append({"url": final_url, "error": err})
                branch = branch or "main"

                listing_method: str | None = None
                listing_stats: dict[str, Any] = {}
                candidates: list[str] = []
                prefer_contents_first = bool(gh_subpath) and (gh_kind in ("tree", "blob"))

                def _record_list_errors(list_errors: list[dict[str, str]]) -> None:
                    for e in list_errors:
                        u = str(e.get("url") or "")
                        err = str(e.get("error") or "")
                        if err.startswith("blocked:"):
                            blocked.append(_blocked_entry(url=u, reason=err.split(":", 1)[1], suggest_allow_domain=True))
                        else:
                            errors.append({"url": u, "error": err})

                # Strategy A: Contents API BFS rooted at subpath for /tree/ and /blob/ URLs (and any explicit subpath).
                if prefer_contents_first:
                    paths, list_errors, bfs_stats = _github_list_candidate_paths_contents(
                        owner=owner,
                        repo=repo,
                        ref=branch,
                        subpath=gh_subpath,
                        include_globs=include_globs,
                        exclude_globs=exclude_globs,
                        prefer_docs=prefer_docs,
                        max_files=max_files,
                        max_depth=max_depth_repo,
                        max_dirs=max_dirs_repo,
                        ctx=ctx,
                    )
                    listing_stats.update(bfs_stats)
                    _record_list_errors(list_errors)
                    if paths:
                        providers_used.append("github_contents")
                        listing_method = "contents_bfs"
                        candidates = paths
                    else:
                        providers_failed.append("github_contents")

                # Strategy B: Trees recursive as an optimization (or fallback when contents produced no candidates).
                if prefer_contents_first and not candidates:
                    tree, tree_url, tree_err = _github_tree_soft(owner=owner, repo=repo, ref=branch, ctx=ctx)
                    if tree is not None:
                        providers_used.append("github_trees")
                        listing_method = "trees_recursive"
                        listing_stats["tree_items"] = len(tree)
                        candidates, tree_stats = _github_select_candidate_paths(
                            tree=tree,
                            subpath=gh_subpath,
                            include_globs=include_globs,
                            exclude_globs=exclude_globs,
                            prefer_docs=prefer_docs,
                            max_files=max_files,
                        )
                        listing_stats.update(tree_stats)
                    else:
                        if tree_err and tree_err.startswith("blocked:"):
                            blocked.append(_blocked_entry(url=tree_url, reason=tree_err.split(":", 1)[1], suggest_allow_domain=True))
                        else:
                            providers_failed.append("github_trees")
                            errors.append({"url": tree_url, "error": f"github_trees:{tree_err or 'unknown'}"})

                # Repo root: try Trees first (fast when it fits), then fallback to Contents BFS.
                if not prefer_contents_first and not candidates:
                    tree, tree_url, tree_err = _github_tree_soft(owner=owner, repo=repo, ref=branch, ctx=ctx)
                    if tree is not None:
                        providers_used.append("github_trees")
                        listing_method = "trees_recursive"
                        listing_stats["tree_items"] = len(tree)
                        candidates, tree_stats = _github_select_candidate_paths(
                            tree=tree,
                            subpath=None,
                            include_globs=include_globs,
                            exclude_globs=exclude_globs,
                            prefer_docs=prefer_docs,
                            max_files=max_files,
                        )
                        listing_stats.update(tree_stats)
                    else:
                        if tree_err and tree_err.startswith("blocked:"):
                            blocked.append(_blocked_entry(url=tree_url, reason=tree_err.split(":", 1)[1], suggest_allow_domain=True))
                        else:
                            providers_failed.append("github_trees")
                            errors.append({"url": tree_url, "error": f"github_trees:{tree_err or 'unknown'}"})

                    if not candidates:
                        paths, list_errors, bfs_stats = _github_list_candidate_paths_contents(
                            owner=owner,
                            repo=repo,
                            ref=branch,
                            subpath=None,
                            include_globs=include_globs,
                            exclude_globs=exclude_globs,
                            prefer_docs=prefer_docs,
                            max_files=max_files,
                            max_depth=max_depth_repo,
                            max_dirs=max_dirs_repo,
                            ctx=ctx,
                        )
                        listing_stats.update(bfs_stats)
                        _record_list_errors(list_errors)
                        if paths:
                            providers_used.append("github_contents")
                            listing_method = "contents_bfs"
                            candidates = paths
                        else:
                            providers_failed.append("github_contents")

                if not candidates:
                    listing_method = listing_method or "seed_only"
                    candidates = ["README.md"]

                # Dedup while preserving order.
                seen_paths: set[str] = set()
                chosen: list[str] = []
                for p in candidates:
                    pp = (p or "").strip().lstrip("/")
                    if not pp or pp in seen_paths:
                        continue
                    seen_paths.add(pp)
                    chosen.append(pp)
                    if len(chosen) >= max_files:
                        break

                # If the user pointed at a repo subpath, optionally include the root README for context
                # (but do not override explicit include_globs like **/*.lua).
                chosen_items: list[tuple[str, bool]] = [(p, False) for p in chosen]
                has_readme = any((p.rsplit("/", 1)[-1].lower().startswith("readme")) for p, _ in chosen_items)
                if gh_subpath and not has_readme and not include_globs:
                    chosen_items.insert(0, ("README.md", True))
                    seen_paths.add("README.md")
                chosen_items = chosen_items[:max_files]

                # Normalize listing stats keys for UI/manifest consumers.
                listing_stats.setdefault("dirs_visited", 0)
                listing_stats.setdefault("max_depth_reached", 0)
                listing_stats.setdefault("files_considered", 0)
                listing_stats.setdefault("files_filtered_out", 0)

                repo_info = {
                    "owner": owner,
                    "repo": repo,
                    "repo_full": f"{owner}/{repo}",
                    "branch": branch,
                    "subpath": gh_subpath or None,
                    "listing_method": listing_method or "seed_only",
                    "listing_stats": listing_stats,
                    "caps": {"max_files": max_files, "max_depth_repo": max_depth_repo, "max_dirs_repo": max_dirs_repo},
                    "filters": {"include_globs": list(include_globs), "exclude_globs": list(exclude_globs)},
                }

                files_fetched = 0
                files_failed = 0
                files_blocked = 0
                for i, (path, ignore_404) in enumerate(chosen_items, start=1):
                    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path.lstrip('/')}"
                    crawl_stats["urls_visited"] = int(crawl_stats.get("urls_visited") or 0) + 1
                    extra = {
                        "repo": {
                            "full": f"{owner}/{repo}",
                            "path": path,
                            "source_url": f"https://github.com/{owner}/{repo}/blob/{branch}/{path.lstrip('/')}",
                            "branch": branch,
                        }
                    }
                    st = ingest_text_url(
                        raw,
                        index=i,
                        title_hint=path,
                        extra_fields=extra,
                        ignore_http_404=(listing_method == "seed_only") or bool(ignore_404),
                    )
                    if st == "ok":
                        files_fetched += 1
                    elif st == "blocked":
                        files_blocked += 1
                    elif st == "error":
                        files_failed += 1
                    if delay_ms:
                        time.sleep(delay_ms / 1000.0)

                # Enrich listing stats with fetch results.
                if isinstance(repo_info.get("listing_stats"), dict):
                    repo_info["listing_stats"] = {
                        **repo_info["listing_stats"],
                        "files_fetched": int(files_fetched),
                        "files_failed": int(files_failed),
                        "files_blocked": int(files_blocked),
                    }
            elif adapter == "reddit":
                # Reddit: prefer old.reddit.com and extract post + top comments into a single page.
                u = _to_old_reddit(start_url)
                ok_u, why_u = policy_check(u)
                if not ok_u:
                    blocked.append(_blocked_entry(url=u, reason=str(why_u), suggest_allow_domain=True))
                elif not robots_allows(u):
                    blocked.append(_blocked_entry(url=u, reason="Blocked by robots.txt (best-effort).", suggest_allow_domain=False))
                else:
                    try:
                        r = _fetch_html_checked(u, ctx=ctx)
                        text, extra_meta = _extract_reddit_post_text(r.html, max_comments=min(30, int(max_pages)))
                        if not text.strip():
                            raise ToolExecutionError("Empty extracted text.")
                        full_path = base_dir / "page_001.txt"
                        full_path.write_text(text, encoding="utf-8")
                        pages_out.append(
                            {
                                "url": r.url,
                                "status": int(r.status),
                                "bytes": int(r.bytes),
                                "content_type": r.content_type,
                                "title": (extra_meta or {}).get("title"),
                                "meta": extra_meta,
                                "text_excerpt": text[:2000],
                                "ts": float(r.ts),
                                "file": full_path.name,
                            }
                        )
                        crawl_stats["urls_visited"] = int(crawl_stats.get("urls_visited") or 0) + 1
                        crawl_stats["max_depth_reached"] = max(int(crawl_stats.get("max_depth_reached") or 0), 0)
                    except WebAccessDenied as e:
                        blocked.append(_blocked_entry(url=u, reason=str(e), suggest_allow_domain=True))
                    except Exception as e:
                        errors.append({"url": u, "error": str(e)})
            elif adapter == "mediawiki" and effective != "single":
                # MediaWiki: crawl within same host and /wiki/ namespace.
                base_host = normalize_host(urllib.parse.urlparse(start_url).hostname or "")
                queue2: deque[tuple[str, int]] = deque([(start_url, 0)])
                seen2: set[str] = set()
                idx2 = 0
                while queue2 and idx2 < max_pages:
                    u, depth = queue2.popleft()
                    if u in seen2:
                        continue
                    if not _mediawiki_is_allowed_link(u, base_host=base_host):
                        seen2.add(u)
                        continue
                    seen2.add(u)
                    crawl_stats["urls_visited"] = int(crawl_stats.get("urls_visited") or 0) + 1
                    crawl_stats["max_depth_reached"] = max(int(crawl_stats.get("max_depth_reached") or 0), int(depth))

                    idx2 += 1
                    links = ingest_one(u, index=idx2, want_links=(depth < max_depth))
                    if delay_ms:
                        time.sleep(delay_ms / 1000.0)

                    if depth >= max_depth:
                        continue
                    for link in links:
                        if link in seen2:
                            continue
                        if not _mediawiki_is_allowed_link(link, base_host=base_host):
                            continue
                        queue2.append((link, depth + 1))
            elif effective == "single":
                ingest_one(start_url, index=1, want_links=False)
            else:
                # Generic crawl within same registrable domain as start_url.
                start_host = normalize_host(urllib.parse.urlparse(start_url).hostname or "")
                start_reg = registrable_domain(start_host) or start_host
                queue: deque[tuple[str, int]] = deque([(start_url, 0)])
                seen: set[str] = set()
                idx = 0
                while queue and idx < max_pages:
                    u, depth = queue.popleft()
                    if u in seen:
                        continue
                    seen.add(u)
                    crawl_stats["urls_visited"] = int(crawl_stats.get("urls_visited") or 0) + 1
                    crawl_stats["max_depth_reached"] = max(int(crawl_stats.get("max_depth_reached") or 0), int(depth))
                    host = normalize_host(urllib.parse.urlparse(u).hostname or "")
                    reg = registrable_domain(host) or host
                    if start_reg and reg and reg != start_reg:
                        blocked.append(_blocked_entry(url=u, reason="Outside crawl scope (registrable domain mismatch).", suggest_allow_domain=False))
                        continue

                    idx += 1
                    links = ingest_one(u, index=idx, want_links=(depth < max_depth))
                    if delay_ms:
                        time.sleep(delay_ms / 1000.0)

                    if depth >= max_depth:
                        continue
                    for link in links:
                        if link in seen:
                            continue
                        p = urllib.parse.urlparse(link)
                        if p.scheme not in ("http", "https"):
                            continue
                        queue.append((link, depth + 1))

        pages_ok = len(pages_out)
        pages_failed = len(errors)
        partial = bool(blocked or errors)

        ts1 = time.time()
        tried = max(int(crawl_stats.get("urls_visited") or 0), int(pages_ok + pages_failed))
        crawl_stats["urls_visited"] = tried
        crawl_stats["pages_written"] = int(pages_ok)
        crawl_stats["pages_failed"] = int(pages_failed)

        policy_snapshot = {
            "allow_all_hosts": bool(getattr(policy, "allow_all_hosts", False)),
            "allowed_domains": list(getattr(policy, "allowed_domains", ()) or ()),
            "allowed_suffixes": list(getattr(policy, "allowed_host_suffixes", ()) or ()),
            "denied_domains": list(getattr(policy, "denied_domains", ()) or ()),
            "session_allowed_domains": list(session_allowed),
        }

        manifest = {
            "id": manifest_id,
            "ts": ts0,
            "ts_end": ts1,
            "duration_ms": int(max(0.0, (ts1 - ts0) * 1000.0)),
            "tool": self.name,
            "start_url": start_url,
            "adapter": adapter,
            "mode": effective,
            "requested_mode": mode,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "delay_ms": delay_ms,
            "respect_robots": respect_robots,
            "include_patterns": [p.pattern for p in include_pats],
            "exclude_patterns": [p.pattern for p in exclude_pats],
            "providers_used": providers_used,
            "providers_failed": providers_failed,
            "crawl_stats": crawl_stats,
            "policy_snapshot": policy_snapshot,
            "repo": repo_info,
            "partial": bool(partial),
            "pages_ok": int(pages_ok),
            "pages_failed": int(pages_failed),
            "pages": pages_out,
            "blocked": blocked,
            "errors": errors,
        }
        _atomic_write_json(base_dir / "manifest.json", manifest)

        return {
            "start_url": start_url,
            "adapter": adapter,
            "mode": effective,
            "requested_mode": mode,
            "partial": bool(partial),
            "pages_ok": int(pages_ok),
            "pages_failed": int(pages_failed),
            "blocked_count": len(blocked),
            "errors_count": len(errors),
            "crawl_stats": dict(crawl_stats),
            "repo": repo_info,
            "pages": [
                {
                    "url": p.get("url"),
                    "status": p.get("status"),
                    "bytes": p.get("bytes"),
                    "content_type": p.get("content_type"),
                    "title": p.get("title"),
                    "text_excerpt": p.get("text_excerpt"),
                    "ts": p.get("ts"),
                }
                for p in pages_out
            ],
            "blocked": list(blocked),
            "errors": list(errors),
            "manifest_id": manifest_id,
        }
