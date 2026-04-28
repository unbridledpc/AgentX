from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from agentx.core.fs_policy import FsPolicyError, validate_path
from agentx.core.journal import JournalError
from agentx.tools.base import Tool, ToolArgument, ToolExecutionError
from agentx.tools.web import WebAccessDenied, fetch_text


def _coerce_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except Exception:
        v = default
    return max(lo, min(v, hi))


class HermesBkFsListTool(Tool):
    name = "fs_list"
    description = "Hermes.BK-compatible alias for listing directories under allowed roots."
    args = (
        ToolArgument("path", str, "Path to list", required=True),
        ToolArgument("max_entries", int, "Maximum number of entries in output", required=False, default=50),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> str:
        max_entries = _coerce_int(args.get("max_entries"), default=50, lo=1, hi=2000)
        try:
            vp = validate_path(args["path"], cfg=ctx.cfg, for_write=False)
        except FsPolicyError as e:
            raise ToolExecutionError(str(e))

        base = vp.path
        if not base.exists():
            raise ToolExecutionError("Path not found.")
        if base.is_file():
            try:
                size = base.stat().st_size
                mtime = base.stat().st_mtime
            except Exception:
                size = None
                mtime = None
            return "\n".join(
                [
                    f"[fs_list] File: {base}",
                    f"Size: {size} bytes" if size is not None else "Size: <unknown>",
                    f"Modified: {time.ctime(mtime)}" if mtime is not None else "Modified: <unknown>",
                ]
            )

        if not base.is_dir():
            raise ToolExecutionError("Unsupported path type.")

        lines: list[str] = []
        try:
            entries = list(base.iterdir())
        except Exception as e:
            raise ToolExecutionError(f"Unable to list directory: {e}")

        entries_sorted = sorted(entries, key=lambda p: (not p.is_dir(), p.name.lower()))
        shown = entries_sorted[:max_entries]
        for p in shown:
            suffix = "/" if p.is_dir() else ""
            lines.append(f"{p.name}{suffix}")
        header = f"[fs_list] Directory: {base}\nEntries: {len(shown)} displayed of {len(entries_sorted)}"
        body = "\n".join(lines) if lines else "<empty>"
        return header + "\n" + body


class HermesBkHttpGetTool(Tool):
    name = "http_get"
    description = "Hermes.BK-compatible alias for fetching a URL (safe allowlist). Returns extracted text."
    args = (
        ToolArgument("url", str, "URL to fetch", required=True),
        ToolArgument("max_bytes", int, "Max bytes to return (clamped)", required=False, default=256_000),
        ToolArgument("timeout", int, "Timeout seconds (clamped)", required=False, default=10),
    )
    safety_flags = ("network",)

    def run(self, ctx, args: dict[str, Any]) -> str:
        if not ctx.cfg.web.enabled:
            raise ToolExecutionError("Web access disabled.")
        url = (args.get("url") or "").strip()
        if not url:
            raise ToolExecutionError("url is required.")

        # We reuse the WebFetch allowlist / private-network blocking via fetch_text().
        try:
            res = fetch_text(url, cfg=ctx.cfg)
        except WebAccessDenied as e:
            raise ToolExecutionError(str(e))
        except Exception as e:
            raise ToolExecutionError(f"Fetch failed: {e}")

        max_bytes = _coerce_int(args.get("max_bytes"), default=256_000, lo=1024, hi=int(ctx.cfg.web.max_bytes))
        timeout = _coerce_int(args.get("timeout"), default=10, lo=1, hi=int(max(1, ctx.cfg.web.timeout_s)))

        # fetch_text already used cfg.web.timeout_s; we still surface the requested timeout to avoid surprises.
        text = res.text
        raw = text.encode("utf-8", errors="ignore")
        truncated = False
        if len(raw) > max_bytes:
            text = raw[:max_bytes].decode("utf-8", errors="replace")
            truncated = True

        lines = [
            "[http_get] 200 OK",
            f"Url: {res.url}",
            f"Timeout: {timeout}s (configured={ctx.cfg.web.timeout_s}s)",
            f"Length: {len(raw)} bytes",
            f"Content-Type: {res.content_type or '<unknown>'}",
        ]
        if truncated:
            lines.append(f"...response truncated to {len(text.encode('utf-8', errors='ignore'))} bytes")
        lines.append("Body:")
        lines.append(text or "<empty>")
        return "\n".join(lines)


def _resolve_read_path(ctx, raw: str) -> Path:
    p = (raw or "").strip() or "."
    target = Path(p)
    if not target.is_absolute():
        target = (ctx.cfg.root_dir / target).resolve()
    try:
        validate_path(str(target), cfg=ctx.cfg, for_write=False)
    except FsPolicyError as e:
        raise ToolExecutionError(str(e))
    return target


class RepoTreeTool(Tool):
    name = "repo_tree"
    description = "Print a directory tree (allowed roots only)."
    args = (
        ToolArgument("path", str, "Base path", required=False, default="."),
        ToolArgument("max_depth", int, "Max depth", required=False, default=4),
        ToolArgument("max_entries", int, "Max entries", required=False, default=500),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        base = _resolve_read_path(ctx, args.get("path") or ".")
        if not base.exists() or not base.is_dir():
            raise ToolExecutionError("Directory not found.")
        max_depth = _coerce_int(args.get("max_depth"), default=4, lo=0, hi=25)
        max_entries = _coerce_int(args.get("max_entries"), default=500, lo=1, hi=10_000)

        lines: list[str] = []
        count = 0

        def walk(dir_path: Path, depth: int, prefix: str) -> None:
            nonlocal count
            if count >= max_entries or depth > max_depth:
                return
            try:
                children = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except Exception:
                return
            for child in children:
                if count >= max_entries:
                    return
                name = child.name + ("/" if child.is_dir() else "")
                lines.append(prefix + name)
                count += 1
                if child.is_dir():
                    walk(child, depth + 1, prefix + "  ")

        lines.append(str(base))
        walk(base, 0, "  ")
        return {"path": str(base), "max_depth": max_depth, "max_entries": max_entries, "entries": lines, "truncated": count >= max_entries}


class RepoGrepTool(Tool):
    name = "repo_grep"
    description = "Search for a substring in files (allowed roots only)."
    args = (
        ToolArgument("query", str, "Query substring", required=True),
        ToolArgument("path", str, "Base directory", required=False, default="."),
        ToolArgument("case_sensitive", bool, "Case sensitive", required=False, default=False),
        ToolArgument("max_hits", int, "Max hits", required=False, default=200),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        query = (args.get("query") or "").strip()
        if not query:
            return {"hits": []}
        base = _resolve_read_path(ctx, args.get("path") or ".")
        if not base.exists() or not base.is_dir():
            raise ToolExecutionError("Directory not found.")
        case_sensitive = bool(args.get("case_sensitive") or False)
        max_hits = _coerce_int(args.get("max_hits"), default=200, lo=1, hi=5000)

        hits: list[dict[str, Any]] = []
        q = query if case_sensitive else query.lower()
        for p in base.rglob("*"):
            if len(hits) >= max_hits:
                break
            if not p.is_file():
                continue
            try:
                if p.stat().st_size > ctx.cfg.fs.max_read_bytes:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            hay = text if case_sensitive else text.lower()
            idx = hay.find(q)
            if idx == -1:
                continue
            line_no = hay[:idx].count("\n") + 1
            hits.append({"path": str(p), "line": line_no})

        return {"query": query, "base": str(base), "hits": hits, "truncated": len(hits) >= max_hits}


class QtStyleScanTool(Tool):
    name = "qt_style_scan"
    description = "Scan files for style patterns (useful for QSS/Tailwind audits)."
    args = (
        ToolArgument("path", str, "Base directory", required=False, default="."),
        ToolArgument("patterns", list, "List of substrings to search for", required=False, default=["box-shadow"]),
        ToolArgument("max_hits", int, "Max hits", required=False, default=200),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        base = _resolve_read_path(ctx, args.get("path") or ".")
        if not base.exists() or not base.is_dir():
            raise ToolExecutionError("Directory not found.")
        patterns = args.get("patterns") or ["box-shadow"]
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ToolExecutionError("patterns must be a list of strings.")
        max_hits = _coerce_int(args.get("max_hits"), default=200, lo=1, hi=5000)
        pats = [p for p in (s.strip() for s in patterns) if p]
        if not pats:
            return {"hits": []}

        hits: list[dict[str, Any]] = []
        for p in base.rglob("*"):
            if len(hits) >= max_hits:
                break
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".qss", ".css", ".ts", ".tsx", ".js", ".jsx", ".html", ".py"):
                continue
            try:
                if p.stat().st_size > ctx.cfg.fs.max_read_bytes:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pat in pats:
                idx = text.find(pat)
                if idx == -1:
                    continue
                line_no = text[:idx].count("\n") + 1
                hits.append({"path": str(p), "line": line_no, "pattern": pat})
                if len(hits) >= max_hits:
                    break

        return {"base": str(base), "patterns": pats, "hits": hits, "truncated": len(hits) >= max_hits}


class RunPyCompileTool(Tool):
    name = "run_py_compile"
    description = "Syntax-check Python files without writing .pyc."
    args = (
        ToolArgument("paths", list, "Paths to .py files/dirs", required=False, default=["."]),
        ToolArgument("max_files", int, "Max files to check", required=False, default=2000),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        paths = args.get("paths") or ["."]
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ToolExecutionError("paths must be a list of strings.")
        max_files = _coerce_int(args.get("max_files"), default=2000, lo=1, hi=50_000)

        files: list[Path] = []
        for raw in paths:
            base = _resolve_read_path(ctx, raw)
            if base.is_file() and base.suffix.lower() == ".py":
                files.append(base)
                continue
            if base.is_dir():
                for p in base.rglob("*.py"):
                    files.append(p)
                    if len(files) >= max_files:
                        break
        files = files[:max_files]

        errors: list[dict[str, Any]] = []
        for p in files:
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
                compile(src, str(p), "exec")
            except SyntaxError as e:
                errors.append({"path": str(p), "line": e.lineno, "offset": e.offset, "msg": e.msg})
            except Exception as e:
                errors.append({"path": str(p), "line": None, "offset": None, "msg": str(e)})

        return {"checked": len(files), "errors": errors, "ok": len(errors) == 0}


class RunPytestTool(Tool):
    name = "run_pytest"
    description = "Run pytest (supervised only)."
    args = (
        ToolArgument("args", str, "Pytest args string (e.g. -q)", required=False, default="-q"),
        ToolArgument("cwd", str, "Working directory", required=False, default="."),
    )
    safety_flags = ("exec",)
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        if ctx.cfg.mode == "unattended":
            raise ToolExecutionError("run_pytest is disabled in unattended mode.")
        cwd = _resolve_read_path(ctx, args.get("cwd") or ".")
        if not cwd.exists() or not cwd.is_dir():
            raise ToolExecutionError("cwd not found.")
        try:
            import os
            import shlex
            import pytest
        except Exception as e:
            raise ToolExecutionError(f"pytest not available: {e}")

        argv = shlex.split(args.get("args") or "-q")
        # Reduce file writes from cache/pyc.
        base_args = ["-p", "no:cacheprovider"]
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        started = time.time()
        try:
            old_cwd = Path.cwd()
            os.chdir(str(cwd))
            code = pytest.main(base_args + argv)
        finally:
            os.chdir(str(old_cwd))
        ended = time.time()
        return {"exit_code": int(code), "duration_s": float(ended - started), "cwd": str(cwd)}


@dataclass
class _Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: List[str]  # each starts with ' ', '+', '-'


@dataclass
class _FilePatch:
    a_path: str
    b_path: str
    hunks: List[_Hunk]


_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DEV_NULL = "/dev/null"


def _clean_rel_path(p: str) -> str:
    p = (p or "").strip()
    if p == _DEV_NULL:
        return p
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p


def _parse_unified_diff(patch_text: str) -> List[_FilePatch]:
    lines = (patch_text or "").splitlines()
    i = 0
    out: List[_FilePatch] = []
    current: Optional[_FilePatch] = None
    hunks: List[_Hunk] = []

    def flush() -> None:
        nonlocal current, hunks
        if current is None:
            return
        current.hunks = hunks
        out.append(current)
        current = None
        hunks = []

    while i < len(lines):
        line = lines[i]
        m = _DIFF_GIT_RE.match(line)
        if m:
            flush()
            current = _FilePatch(a_path=_clean_rel_path(m.group(1)), b_path=_clean_rel_path(m.group(2)), hunks=[])
            i += 1
            continue

        if current is None:
            i += 1
            continue

        if line.startswith("--- "):
            current.a_path = _clean_rel_path(line[4:].strip())
            i += 1
            continue
        if line.startswith("+++ "):
            current.b_path = _clean_rel_path(line[4:].strip())
            i += 1
            continue

        hm = _HUNK_RE.match(line)
        if hm:
            old_start = int(hm.group(1))
            old_len = int(hm.group(2) or "1")
            new_start = int(hm.group(3))
            new_len = int(hm.group(4) or "1")
            hunk_lines: List[str] = []
            i += 1
            while i < len(lines):
                l = lines[i]
                if l.startswith("diff --git "):
                    break
                if _HUNK_RE.match(l):
                    break
                if l.startswith("\\ No newline at end of file"):
                    i += 1
                    continue
                if l and l[0] in (" ", "+", "-"):
                    hunk_lines.append(l)
                    i += 1
                    continue
                # ignore metadata lines like "index ..."
                i += 1
            hunks.append(_Hunk(old_start, old_len, new_start, new_len, hunk_lines))
            continue

        i += 1

    flush()
    return out


def _apply_hunks(original: List[str], hunks: List[_Hunk]) -> List[str]:
    buf = original[:]
    offset = 0
    for h in hunks:
        idx = (h.old_start - 1) + offset
        if idx < 0:
            idx = 0

        expected_old: List[str] = []
        new_block: List[str] = []
        for l in h.lines:
            tag = l[0]
            payload = l[1:]
            if tag in (" ", "-"):
                expected_old.append(payload)
            if tag in (" ", "+"):
                new_block.append(payload)

        if buf[idx : idx + len(expected_old)] != expected_old:
            found = -1
            start = max(0, idx - 50)
            end = min(len(buf), idx + 50)
            for j in range(start, end + 1):
                if buf[j : j + len(expected_old)] == expected_old:
                    found = j
                    break
            if found == -1:
                raise ValueError("hunk context does not match target file")
            idx = found

        buf[idx : idx + len(expected_old)] = new_block
        offset += len(new_block) - len(expected_old)
    return buf


def _resolve_patch_target(ctx, rel_path: str) -> Path:
    p = (rel_path or "").strip()
    if not p or p == _DEV_NULL:
        raise ToolExecutionError("Invalid patch path.")
    target = Path(p)
    if not target.is_absolute():
        target = (ctx.cfg.root_dir / target).resolve()
    try:
        validate_path(str(target), cfg=ctx.cfg, for_write=True)
    except FsPolicyError as e:
        raise ToolExecutionError(str(e))
    return target


def _patch_preview(ctx, patch_text: str) -> tuple[bool, str]:
    patches = _parse_unified_diff(patch_text)
    if not patches:
        return False, "Invalid patch: no file diffs found"

    for fp in patches:
        target = fp.b_path if fp.b_path != _DEV_NULL else fp.a_path
        if target in ("", _DEV_NULL):
            return False, "Invalid patch: unsupported /dev/null target"

        try:
            abs_path = _resolve_patch_target(ctx, target)
        except Exception as exc:
            return False, str(exc)

        if not abs_path.exists():
            return False, f"Patch target does not exist: {target}"
        if abs_path.is_dir():
            return False, f"Patch target is a directory: {target}"

        text = abs_path.read_text(encoding="utf-8", errors="replace")
        try:
            _apply_hunks(text.splitlines(), fp.hunks)
        except Exception as exc:
            return False, f"Patch does not apply cleanly to {target}: {exc}"

    return True, "ok"


class PatchPreviewTool(Tool):
    name = "patch_preview"
    description = "Preview a unified diff for clean application (no writes)."
    args = (ToolArgument("patch_text", str, "Unified diff text", required=True),)
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        ok, msg = _patch_preview(ctx, args.get("patch_text") or "")
        if not ok:
            raise ToolExecutionError(msg)
        return {"success": True}


class PatchApplyTool(Tool):
    name = "patch_apply"
    description = "Apply a unified diff with journaling + rollback on failure."
    destructive = True
    args = (
        ToolArgument("patch_text", str, "Unified diff text", required=True),
        ToolArgument("backup", bool, "Keep rollback artifacts (always true in AgentX)", required=False, default=True),
        ToolArgument("reason", str, "Reason for applying this patch", required=False, default=""),
    )
    safety_flags = ("filesystem", "write")
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        patch_text = args.get("patch_text") or ""
        ok, msg = _patch_preview(ctx, patch_text)
        if not ok:
            raise ToolExecutionError(msg)

        patches = _parse_unified_diff(patch_text)
        applied: list[dict[str, Any]] = []
        restored: list[str] = []
        try:
            for fp in patches:
                target_rel = fp.b_path if fp.b_path != _DEV_NULL else fp.a_path
                abs_path = _resolve_patch_target(ctx, target_rel)
                original_text = abs_path.read_text(encoding="utf-8", errors="replace")
                original_lines = original_text.splitlines()
                new_lines = _apply_hunks(original_lines, fp.hunks)
                new_text = "\n".join(new_lines)
                if original_text.endswith("\n"):
                    new_text += "\n"

                rec = ctx.journal.record_write(
                    target=str(abs_path),
                    new_text=new_text,
                    reason=(args.get("reason") or "").strip() or "patch_apply",
                )
                applied.append(rec)
            return {"success": True, "applied_files": [rec.get("path") for rec in applied]}
        except Exception as e:
            # Best-effort rollback of already-applied files.
            for rec in reversed(applied):
                backup_path = rec.get("backup_path")
                target_path = rec.get("path")
                if not backup_path or not target_path:
                    continue
                try:
                    # backup artifacts live under AgentX/data/rollback and may be on a different drive.
                    # Use a copy-based restore to work across drives.
                    src = Path(backup_path)
                    dst = Path(target_path)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(src.read_bytes())
                    restored.append(str(target_path))
                except Exception:
                    continue
            raise ToolExecutionError(f"Patch apply failed: {e}. Rolled back: {len(restored)} file(s).")


def register_hermesbk_tools(reg) -> None:
    """Register Hermes.BK-compatible tool names (aliases + devtools) into the given registry."""

    for tool in (
        HermesBkFsListTool(),
        HermesBkHttpGetTool(),
        RepoTreeTool(),
        RepoGrepTool(),
        QtStyleScanTool(),
        RunPyCompileTool(),
        RunPytestTool(),
        PatchPreviewTool(),
        PatchApplyTool(),
    ):
        reg.register(tool)
