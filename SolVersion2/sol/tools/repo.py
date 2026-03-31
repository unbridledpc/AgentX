from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
import urllib.parse
import base64
from collections import deque
from pathlib import Path
from typing import Any

from sol.tools.base import Tool, ToolArgument, ToolExecutionError
from sol.tools.web import fetch_text


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _parse_repo_url(repo_url: str) -> tuple[str, str]:
    u = (repo_url or "").strip()
    if not u:
        raise ToolExecutionError("repo_url is required.")
    try:
        p = urllib.parse.urlparse(u)
    except Exception:
        raise ToolExecutionError("Malformed repo_url.")
    if p.scheme not in ("http", "https"):
        raise ToolExecutionError("repo_url must be http(s).")
    if (p.hostname or "").lower() != "github.com":
        raise ToolExecutionError("Only github.com repos are supported for repo_url parsing.")
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) < 2:
        raise ToolExecutionError("repo_url must look like https://github.com/<owner>/<repo>.")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return owner, repo


def _github_tree_api_url(*, owner: str, repo: str, branch: str) -> str:
    # Uses the Git Trees API. Requires allowlist for api.github.com in web.policy.
    b = (branch or "main").strip() or "main"
    return f"https://api.github.com/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(b, safe='')}?recursive=1"


def _raw_url(*, owner: str, repo: str, branch: str, path: str) -> str:
    b = (branch or "main").strip() or "main"
    p = (path or "").lstrip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{urllib.parse.quote(b, safe='')}/{p}"


def _github_contents_api_url(*, owner: str, repo: str, branch: str, path: str) -> str:
    b = (branch or "main").strip() or "main"
    p = (path or "").strip().lstrip("/")
    if p:
        p_q = urllib.parse.quote(p, safe="/")
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{p_q}?ref={urllib.parse.quote(b, safe='')}"
    return f"https://api.github.com/repos/{owner}/{repo}/contents?ref={urllib.parse.quote(b, safe='')}"


def _is_html_doctype(text: str) -> bool:
    s = (text or "").lstrip()[:64].lower()
    return s.startswith("<!doctype html") or s.startswith("<html")


def _fetch_json_value(url: str, *, ctx) -> tuple[Any | None, dict[str, Any]]:
    """Fetch a JSON response with basic truncation/non-JSON detection (best effort).

    Returns (data, meta) where data is None on known-recoverable issues.
    """
    try:
        r = fetch_text(url, ctx=ctx)
    except ToolExecutionError as e:
        msg = str(e) or e.__class__.__name__
        low = msg.lower()
        token_env = str(getattr(getattr(ctx.cfg, "web", None), "github_token_env", "") or "").strip()
        token_present = bool((os.environ.get(token_env) or "").strip()) if token_env else False
        token_configured = bool(token_env)
        # Detect GitHub API rate limiting (common on unauthenticated api.github.com requests).
        if ("http 403" in low or "http 429" in low) and "rate limit exceeded" in low:
            return None, {
                "url": url,
                "content_type": None,
                "truncated": False,
                "ts": float(time.time()),
                "partial": True,
                "error": "rate_limited",
                "rate_limited": True,
                "github_token_configured": token_configured,
                "github_token_present": token_present,
                "message": msg[:4000],
            }
        raise
    meta: dict[str, Any] = {"url": r.url, "content_type": r.content_type, "truncated": bool(r.truncated), "ts": float(r.ts)}
    ctype = (r.content_type or "").lower()
    if bool(r.truncated):
        meta["partial"] = True
        meta["error"] = "max_bytes"
        return None, meta
    if "application/json" not in ctype:
        meta["partial"] = True
        meta["error"] = "non_json_content_type"
        return None, meta
    if _is_html_doctype(r.text):
        meta["partial"] = True
        meta["error"] = "html_response"
        return None, meta
    try:
        return json.loads(r.text), meta
    except json.JSONDecodeError as e:
        if "unterminated string" in str(e).lower():
            meta["partial"] = True
            meta["error"] = "unterminated_string"
            return None, meta
        raise ToolExecutionError(f"Failed to parse JSON from {url}: {e}")

def _is_recoverable_github_list_error(err: str) -> bool:
    low = (err or "").lower()
    return any(
        k in low
        for k in (
            "max_bytes",
            "unterminated_string",
            "non_json_content_type",
            "html_response",
            "json truncated",
            "unterminated string",
            "response was truncated",
            "truncated",
        )
    )


def _encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8", errors="ignore")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(token: str) -> dict[str, Any]:
    s = (token or "").strip()
    if not s:
        return {}
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    try:
        raw = base64.urlsafe_b64decode((s + pad).encode("ascii"))
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        raise ToolExecutionError(f"Invalid cursor: {e}")
    if not isinstance(obj, dict):
        raise ToolExecutionError("Invalid cursor: expected a JSON object.")
    return obj


def _fetch_json(url: str, *, ctx) -> dict[str, Any]:
    obj, meta = _fetch_json_value(url, ctx=ctx)
    if obj is None:
        # Structured partial result: callers may fall back to other strategies.
        return {
            "ok": False,
            "partial": True,
            "error": meta.get("error"),
            "rate_limited": bool(meta.get("rate_limited") or False),
            "github_token_configured": bool(meta.get("github_token_configured") or False),
            "github_token_present": bool(meta.get("github_token_present") or False),
            "url": meta.get("url") or url,
            "content_type": meta.get("content_type"),
            "truncated": bool(meta.get("truncated")),
            "ts": meta.get("ts"),
        }
    if not isinstance(obj, dict):
        raise ToolExecutionError(f"Expected JSON object from {url}.")
    return obj


def _list_contents_bfs(
    *,
    owner: str,
    repo: str,
    branch: str,
    root_path: str,
    file_pattern: str,
    max_files: int,
    ctx,
) -> tuple[list[dict[str, str]], bool, list[dict[str, str]]]:
    """Fallback listing strategy using GitHub Contents API (BFS, capped)."""
    root = (root_path or "").strip().lstrip("/")
    queue: deque[str] = deque([root])
    seen: set[str] = set()
    files: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    partial = False

    while queue and len(files) < max(0, int(max_files)):
        cur = queue.popleft()
        if cur in seen:
            continue
        seen.add(cur)

        url = _github_contents_api_url(owner=owner, repo=repo, branch=branch, path=cur)
        try:
            data, meta = _fetch_json_value(url, ctx=ctx)
        except Exception as e:
            partial = True
            errors.append({"url": url, "error": str(e)})
            continue

        if data is None:
            partial = True
            errors.append({"url": url, "error": str(meta.get("error") or "unknown")})
            continue

        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            items = [data]
        else:
            partial = True
            errors.append({"url": url, "error": "unexpected_json_shape"})
            continue

        items.sort(key=lambda d: str(d.get("path") or "").lower())
        for it in items:
            typ = str(it.get("type") or "").lower()
            p = str(it.get("path") or "").strip().lstrip("/")
            if not p:
                continue
            if typ == "dir":
                queue.append(p)
                continue
            if typ != "file":
                continue
            if not fnmatch.fnmatch(p.lower(), (file_pattern or "").lower()):
                continue
            files.append({"path": p, "raw_url": _raw_url(owner=owner, repo=repo, branch=branch, path=p)})
            if len(files) >= max(0, int(max_files)):
                break

    if queue:
        partial = True
    files.sort(key=lambda d: d.get("path", "").lower())
    return files, partial, errors


def _fetch_file_text(url: str, *, ctx) -> dict[str, Any]:
    r = fetch_text(url, ctx=ctx)
    return {"url": r.url, "content_type": r.content_type, "text": r.text, "truncated": r.truncated, "ts": r.ts}


class RepoTreeTool(Tool):
    name = "repo.tree"
    description = "List GitHub repo files under a path (tries Trees; falls back to bounded Contents BFS with cursor)"
    args = (
        ToolArgument("repo_url", str, "GitHub repo URL (https://github.com/owner/repo)", required=True),
        ToolArgument("path", str, "Repo sub-path prefix (e.g. data/monster/monsters)", required=False, default=""),
        ToolArgument("path_prefix", str, "Alias for path (optional)", required=False, default=""),
        ToolArgument("branch", str, "Branch or tag name (default: main)", required=False, default="main"),
        ToolArgument("max_entries", int, "Max entries to return (default 200)", required=False, default=200),
        ToolArgument("recursive", bool, "Recurse into subdirectories (default false)", required=False, default=False),
        ToolArgument("cursor", str, "Continuation cursor for pagination (optional)", required=False, default=""),
        ToolArgument("continuation_token", str, "Alias for cursor (optional)", required=False, default=""),
        ToolArgument("reason", str, "Reason for listing repo files", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _parse_repo_url(str(args.get("repo_url") or ""))
        branch = str(args.get("branch") or "main")
        raw_path = str(args.get("path") or "").strip() or str(args.get("path_prefix") or "").strip()
        prefix = raw_path.lstrip("/").rstrip("/")
        max_entries = max(1, min(int(args.get("max_entries") or 200), 2000))
        recursive = bool(args.get("recursive") or False)
        cursor_raw = (args.get("cursor") or "").strip() or (args.get("continuation_token") or "").strip()

        base_repo_url = f"https://github.com/{owner}/{repo}"
        out_entries: list[dict[str, Any]] = []
        out_files: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        partial = False
        method = "contents_dir" if not recursive else "trees_recursive"
        top_error: str | None = None
        rate_limited = False
        token_env = str(getattr(getattr(ctx.cfg, "web", None), "github_token_env", "") or "").strip()
        token_present = bool((os.environ.get(token_env) or "").strip()) if token_env else False
        token_configured = bool(token_env)
        next_cursor: str | None = None

        def add_entry(path_s: str, typ: str) -> None:
            nonlocal out_entries, out_files
            p = (path_s or "").strip().lstrip("/")
            if not p:
                return
            rec: dict[str, Any] = {"path": p, "type": typ}
            if typ == "file":
                rec["raw_url"] = _raw_url(owner=owner, repo=repo, branch=branch, path=p)
                out_files.append({"path": p, "raw_url": rec["raw_url"]})
            out_entries.append(rec)

        def run_contents_dir(path_s: str) -> tuple[list[dict[str, Any]], str | None]:
            nonlocal rate_limited, top_error, partial
            url = _github_contents_api_url(owner=owner, repo=repo, branch=branch, path=path_s)
            data, meta = _fetch_json_value(url, ctx=ctx)
            if data is None:
                err = str(meta.get("error") or "unknown")
                if err == "rate_limited":
                    rate_limited = True
                    partial = True
                    top_error = top_error or "rate_limited"
                return [], err
            items: list[dict[str, Any]] = []
            if isinstance(data, list):
                items = [x for x in data if isinstance(x, dict)]
            elif isinstance(data, dict):
                items = [data]
            else:
                return [], "unexpected_json_shape"
            items.sort(key=lambda d: str(d.get("path") or "").lower())
            return items, None

        def run_contents_bfs(*, cursor_obj: dict[str, Any] | None) -> None:
            nonlocal partial, method, top_error, next_cursor
            method = "contents_bfs"

            max_depth = 5 if recursive else 0
            max_dirs = 200

            if cursor_obj:
                if str(cursor_obj.get("v") or "") != "1":
                    raise ToolExecutionError("Invalid cursor: unsupported version.")
                if str(cursor_obj.get("owner") or "") != owner or str(cursor_obj.get("repo") or "") != repo:
                    raise ToolExecutionError("Invalid cursor: repo mismatch.")
                if str(cursor_obj.get("branch") or "") != branch:
                    raise ToolExecutionError("Invalid cursor: branch mismatch.")
                if str(cursor_obj.get("path") or "") != prefix:
                    raise ToolExecutionError("Invalid cursor: path mismatch.")
                if bool(cursor_obj.get("recursive")) != bool(recursive):
                    raise ToolExecutionError("Invalid cursor: recursive mismatch.")

                queue = deque(
                    [
                        (str(x.get("path") or ""), int(x.get("depth") or 0))
                        for x in (cursor_obj.get("queue") or [])
                        if isinstance(x, dict) and str(x.get("path") or "").strip()
                    ]
                )
                pending = deque(
                    [
                        (str(x.get("path") or ""), str(x.get("type") or ""), int(x.get("depth") or 0))
                        for x in (cursor_obj.get("pending") or [])
                        if isinstance(x, dict) and str(x.get("path") or "").strip()
                    ]
                )
                seen_dirs = set(str(x) for x in (cursor_obj.get("seen_dirs") or []) if isinstance(x, str) and x.strip())
            else:
                queue = deque([(prefix, 0)])
                pending = deque()
                seen_dirs = set()

            # Drain pending entries first (these came from a previous mid-directory cutoff).
            while pending and len(out_entries) < max_entries:
                p, typ, d = pending.popleft()
                add_entry(p, typ)
                if recursive and typ == "dir" and d < max_depth:
                    queue.append((p, d + 1))

            while queue and len(out_entries) < max_entries and len(seen_dirs) < max_dirs:
                cur, depth = queue.popleft()
                cur = (cur or "").strip().lstrip("/").rstrip("/")
                if cur in seen_dirs:
                    continue
                seen_dirs.add(cur)

                try:
                    items, err = run_contents_dir(cur)
                except Exception as e:
                    partial = True
                    errors.append({"url": _github_contents_api_url(owner=owner, repo=repo, branch=branch, path=cur), "error": str(e)})
                    continue
                if err:
                    if err == "rate_limited":
                        # Stop early to avoid spamming the API.
                        break
                    partial = True
                    if top_error is None:
                        top_error = err
                    errors.append({"url": _github_contents_api_url(owner=owner, repo=repo, branch=branch, path=cur), "error": err})
                    continue

                for it in items:
                    typ = str(it.get("type") or "").lower()
                    p = str(it.get("path") or "").strip().lstrip("/")
                    if not p:
                        continue
                    if prefix and not (p == prefix or p.startswith(prefix + "/")):
                        continue
                    if typ == "dir":
                        if len(out_entries) >= max_entries:
                            pending.append((p, "dir", depth))
                            continue
                        add_entry(p, "dir")
                        if recursive and depth < max_depth:
                            queue.append((p, depth + 1))
                        continue
                    if typ == "file":
                        if len(out_entries) >= max_entries:
                            pending.append((p, "file", depth))
                            continue
                        add_entry(p, "file")
                        continue
                    # ignore symlinks/submodules

            if pending or queue or len(seen_dirs) >= max_dirs:
                partial = True
                if len(seen_dirs) >= max_dirs and top_error is None:
                    top_error = "max_dirs"
                next_cursor = _encode_cursor(
                    {
                        "v": 1,
                        "method": "contents_bfs",
                        "owner": owner,
                        "repo": repo,
                        "branch": branch,
                        "path": prefix,
                        "recursive": bool(recursive),
                        "queue": [{"path": p, "depth": d} for (p, d) in list(queue)[:1000]],
                        "pending": [{"path": p, "type": t, "depth": d} for (p, t, d) in list(pending)[:1000]],
                        "seen_dirs": list(sorted(seen_dirs))[:max_dirs],
                    }
                )

        def run_contents_dir_paged(*, cursor_obj: dict[str, Any] | None) -> None:
            nonlocal partial, method, top_error, next_cursor
            method = "contents_dir"
            offset = 0
            if cursor_obj:
                if str(cursor_obj.get("v") or "") != "1":
                    raise ToolExecutionError("Invalid cursor: unsupported version.")
                if str(cursor_obj.get("owner") or "") != owner or str(cursor_obj.get("repo") or "") != repo:
                    raise ToolExecutionError("Invalid cursor: repo mismatch.")
                if str(cursor_obj.get("branch") or "") != branch:
                    raise ToolExecutionError("Invalid cursor: branch mismatch.")
                if str(cursor_obj.get("path") or "") != prefix:
                    raise ToolExecutionError("Invalid cursor: path mismatch.")
                if bool(cursor_obj.get("recursive")) is not False:
                    raise ToolExecutionError("Invalid cursor: recursive mismatch.")
                try:
                    offset = max(0, int(cursor_obj.get("offset") or 0))
                except Exception:
                    offset = 0

            items, err = run_contents_dir(prefix)
            if err:
                if err == "rate_limited":
                    return
                partial = True
                top_error = err
                errors.append({"url": _github_contents_api_url(owner=owner, repo=repo, branch=branch, path=prefix), "error": err})
                return

            page = items[offset : offset + max_entries]
            for it in page:
                typ = str(it.get("type") or "").lower()
                p = str(it.get("path") or "").strip().lstrip("/")
                if typ == "dir":
                    add_entry(p, "dir")
                elif typ == "file":
                    add_entry(p, "file")

            if offset + max_entries < len(items):
                partial = True
                top_error = top_error or "max_entries"
                next_cursor = _encode_cursor(
                    {
                        "v": 1,
                        "method": "contents_dir",
                        "owner": owner,
                        "repo": repo,
                        "branch": branch,
                        "path": prefix,
                        "recursive": False,
                        "offset": offset + max_entries,
                    }
                )

        def run_trees_paged(*, cursor_obj: dict[str, Any] | None) -> None:
            nonlocal partial, method, top_error, next_cursor, rate_limited
            method = "trees_recursive"
            offset = 0
            if cursor_obj:
                if str(cursor_obj.get("v") or "") != "1":
                    raise ToolExecutionError("Invalid cursor: unsupported version.")
                if str(cursor_obj.get("owner") or "") != owner or str(cursor_obj.get("repo") or "") != repo:
                    raise ToolExecutionError("Invalid cursor: repo mismatch.")
                if str(cursor_obj.get("branch") or "") != branch:
                    raise ToolExecutionError("Invalid cursor: branch mismatch.")
                if str(cursor_obj.get("path") or "") != prefix:
                    raise ToolExecutionError("Invalid cursor: path mismatch.")
                if bool(cursor_obj.get("recursive")) is not True:
                    raise ToolExecutionError("Invalid cursor: recursive mismatch.")
                try:
                    offset = max(0, int(cursor_obj.get("offset") or 0))
                except Exception:
                    offset = 0

            api = _github_tree_api_url(owner=owner, repo=repo, branch=branch)
            tree = _fetch_json(api, ctx=ctx)
            # Structured partial from _fetch_json means recoverable listing failure (e.g., max_bytes).
            if bool(tree.get("partial")) and tree.get("ok") is False:
                partial = True
                top_error = str(tree.get("error") or "unknown")
                errors.append({"url": api, "error": top_error})
                if str(tree.get("error") or "") == "rate_limited":
                    rate_limited = True
                    # Do not fall back; other GitHub endpoints will likely also be rate-limited.
                    return
                run_contents_bfs(cursor_obj=None)
                return

            if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
                raise ToolExecutionError("GitHub API response missing 'tree' list.")
            items_all = [x for x in (tree.get("tree") or []) if isinstance(x, dict)]
            items_all.sort(key=lambda d: str(d.get("path") or "").lower())

            filtered: list[tuple[str, str]] = []
            for it in items_all:
                typ = str(it.get("type") or "").lower()
                p = str(it.get("path") or "").strip().lstrip("/")
                if not p:
                    continue
                if prefix and not (p == prefix or p.startswith(prefix + "/")):
                    continue
                if typ == "tree":
                    filtered.append((p, "dir"))
                elif typ == "blob":
                    filtered.append((p, "file"))

            page = filtered[offset : offset + max_entries]
            for p, typ in page:
                add_entry(p, typ)

            if offset + max_entries < len(filtered):
                partial = True
                top_error = top_error or "max_entries"
                next_cursor = _encode_cursor(
                    {
                        "v": 1,
                        "method": "trees_recursive",
                        "owner": owner,
                        "repo": repo,
                        "branch": branch,
                        "path": prefix,
                        "recursive": True,
                        "offset": offset + max_entries,
                    }
                )

        if cursor_raw:
            cur = _decode_cursor(cursor_raw)
            cm = str(cur.get("method") or "")
            if cm == "contents_dir":
                run_contents_dir_paged(cursor_obj=cur)
            elif cm == "trees_recursive":
                run_trees_paged(cursor_obj=cur)
            else:
                run_contents_bfs(cursor_obj=cur)
        else:
            if not recursive:
                run_contents_dir_paged(cursor_obj=None)
            else:
                # Try trees (paged). If it fails recoverably, it will fall back to BFS.
                run_trees_paged(cursor_obj=None)

        # Stable ordering for consumers.
        out_entries.sort(key=lambda d: str(d.get("path") or "").lower())
        out_files.sort(key=lambda d: str(d.get("path") or "").lower())

        return {
            "ok": True,
            "partial": bool(partial),
            "error": top_error,
            "rate_limited": bool(rate_limited),
            "github_token_configured": bool(token_configured),
            "github_token_present": bool(token_present),
            "method": method,
            "next_cursor": next_cursor,
            "repo_url": base_repo_url,
            "branch": branch,
            "path_prefix": prefix,
            "path": prefix,
            "entries": out_entries,
            "files": out_files,
            "count": len(out_entries),
            "ts": time.time(),
            "errors": errors,
        }


class RepoFetchFileTool(Tool):
    name = "repo.fetch_file"
    description = "Fetch a raw GitHub file (text-like) via raw.githubusercontent.com"
    args = (
        ToolArgument("raw_url", str, "Raw GitHub file URL (https://raw.githubusercontent.com/...)", required=False, default=""),
        ToolArgument("repo_url", str, "GitHub repo URL (https://github.com/owner/repo)", required=False, default=""),
        ToolArgument("branch", str, "Branch or tag name (default: main)", required=False, default="main"),
        ToolArgument("path", str, "Repo file path (e.g. README.md)", required=False, default=""),
        ToolArgument("reason", str, "Reason for fetching file content", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        raw_url = (args.get("raw_url") or "").strip()
        repo_url = (args.get("repo_url") or "").strip()
        branch = (args.get("branch") or "main").strip() or "main"
        path = (args.get("path") or "").strip().lstrip("/")

        u = raw_url
        if not u and repo_url and path:
            owner, repo = _parse_repo_url(repo_url)
            u = _raw_url(owner=owner, repo=repo, branch=branch, path=path)
        if not u:
            raise ToolExecutionError("Provide either raw_url, or (repo_url + path [+branch]).")

        # Conservative allowlist: this tool is for inspecting text-like files.
        ext = Path(urllib.parse.urlparse(u).path).suffix.lower()
        allowed_exts = {
            ".md",
            ".txt",
            ".rst",
            ".toml",
            ".yaml",
            ".yml",
            ".json",
            ".ini",
            ".cfg",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".lua",
            ".xml",
        }
        if ext and ext not in allowed_exts:
            raise ToolExecutionError(f"Refusing to fetch non-text-like file type: {ext}")

        return _fetch_file_text(u, ctx=ctx)


class RepoIngestTool(Tool):
    name = "repo.ingest"
    description = "Fetch XML files from a GitHub repo path and write an ingest manifest for Agent memory ingestion"
    args = (
        ToolArgument("repo_url", str, "GitHub repo URL (https://github.com/owner/repo)", required=True),
        ToolArgument("path", str, "Repo sub-path prefix containing XML files", required=False, default=""),
        ToolArgument("branch", str, "Branch or tag name (default: main)", required=False, default="main"),
        ToolArgument("file_pattern", str, "Glob pattern (default: *.xml)", required=False, default="*.xml"),
        ToolArgument("collection", str, "Collection name for memory tags (default: tibia.monsters)", required=False, default="tibia.monsters"),
        ToolArgument("source", str, "Source tag (default: forgottenserver)", required=False, default="forgottenserver"),
        ToolArgument("write_manifest", bool, "Write manifest under data/ingest/manifests", required=False, default=True),
        ToolArgument("reason", str, "Reason for ingestion", required=False, default=""),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _parse_repo_url(str(args.get("repo_url") or ""))
        branch = str(args.get("branch") or "main")
        prefix = str(args.get("path") or "").strip().lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        pat = str(args.get("file_pattern") or "*.xml").strip() or "*.xml"
        collection = str(args.get("collection") or "tibia.monsters").strip() or "tibia.monsters"
        source = str(args.get("source") or "forgottenserver").strip() or "forgottenserver"

        errors: list[dict[str, str]] = []
        method = "trees_recursive"
        partial = False

        files: list[dict[str, Any]] = []
        tree_tool = RepoTreeTool()
        try:
            tree = tree_tool.run(
                ctx,
                {
                    "repo_url": f"https://github.com/{owner}/{repo}",
                    "path": prefix.rstrip("/"),
                    "branch": branch,
                    # Repo ingestion needs a recursive view of the path.
                    "recursive": True,
                    # Keep this high; ingestion is still bounded by file_pattern and fetch limits below.
                    "max_entries": 2000,
                },
            )
            raw_files = tree.get("files")
            if not isinstance(raw_files, list):
                raise ToolExecutionError("repo.tree output missing files list.")
            files = raw_files
            # Propagate listing method/partial/errors when available.
            if isinstance(tree.get("method"), str):
                method = str(tree.get("method") or method)
            if bool(tree.get("partial")):
                partial = True
            if isinstance(tree.get("errors"), list):
                for e in tree.get("errors") or []:
                    if isinstance(e, dict) and (e.get("url") or e.get("error")):
                        errors.append({"url": str(e.get("url") or ""), "error": str(e.get("error") or "")})
        except Exception as e:
            # Controlled fallback: Git Trees API can exceed max_bytes for large repos.
            errors.append({"url": _github_tree_api_url(owner=owner, repo=repo, branch=branch), "error": str(e)})
            method = "contents_bfs"
            bfs_files, bfs_partial, bfs_errors = _list_contents_bfs(
                owner=owner,
                repo=repo,
                branch=branch,
                root_path=prefix.rstrip("/"),
                file_pattern=pat,
                max_files=500,
                ctx=ctx,
            )
            files = bfs_files
            partial = bool(bfs_partial)
            errors.extend(bfs_errors)

        picked: list[dict[str, Any]] = []
        for f in files:
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            raw_url = str(f.get("raw_url") or "")
            if not p or not raw_url:
                continue
            if not fnmatch.fnmatch(p.lower(), pat.lower()):
                continue
            picked.append({"path": p, "raw_url": raw_url})

        picked.sort(key=lambda d: str(d.get("path") or "").lower())
        docs: list[dict[str, Any]] = []
        fetched = 0
        for f in picked:
            try:
                res = _fetch_file_text(str(f["raw_url"]), ctx=ctx)
                text = str(res.get("text") or "")
                sha = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                docs.append({"path": f["path"], "raw_url": res.get("url") or f["raw_url"], "xml": text, "content_sha256": sha, "doc_ids": {}, "dedupe": {}, "ts": float(res.get("ts") or time.time())})
                fetched += 1
            except Exception as e:
                errors.append({"url": str(f.get("raw_url") or ""), "error": str(e)})

        if errors or fetched != len(picked):
            partial = True

        ts_out = time.time()
        manifest_path: str | None = None
        if bool(args.get("write_manifest", True)):
            ingest_dir = Path(ctx.cfg.paths.data_dir) / "ingest" / "manifests"
            stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(ts_out))
            hid = hashlib.sha256(f"{owner}/{repo}|{prefix}|{branch}|{ts_out}".encode("utf-8", errors="ignore")).hexdigest()[:12]
            manifest_id = f"{stamp}_repo_{hid}"
            path = ingest_dir / f"{manifest_id}.json"
            _atomic_write_json(
                path,
                {
                    "id": manifest_id,
                    "ts": ts_out,
                    "tool": self.name,
                    "args": {k: args.get(k) for k in ("repo_url", "path", "branch", "file_pattern", "collection", "source", "write_manifest")},
                    "start_url": f"https://github.com/{owner}/{repo}",
                    "repo": {"owner": owner, "name": repo, "branch": branch, "path": prefix.rstrip("/"), "pattern": pat},
                    "collection": collection,
                    "source": source,
                    "ok": True,
                    "partial": bool(partial),
                    "method": method,
                    "files_total": len(picked),
                    "files_fetched": fetched,
                    "docs_ingested": 0,
                    "docs_skipped": 0,
                    "errors": errors,
                    "docs": docs,
                },
            )
            manifest_path = str(path)

        return {
            "repo_url": f"https://github.com/{owner}/{repo}",
            "path": prefix.rstrip("/"),
            "branch": branch,
            "file_pattern": pat,
            "collection": collection,
            "source": source,
            "ok": True,
            "partial": bool(partial),
            "method": method,
            "files_total": len(picked),
            "files_fetched": fetched,
            "errors": errors,
            "manifest_path": manifest_path,
            "ts": float(ts_out),
        }
