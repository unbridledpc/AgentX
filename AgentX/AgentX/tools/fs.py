from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from agentx.core.fs_policy import FsPolicyError, validate_path
from agentx.tools.base import Tool, ToolArgument, ToolExecutionError


class FsListTool(Tool):
    name = "fs.list"
    description = "List files/directories under allowed roots"
    args = (
        ToolArgument("path", str, "Directory path to list", required=True),
        ToolArgument("recursive", bool, "Recurse", required=False, default=False),
        ToolArgument("max_entries", int, "Max entries", required=False, default=200),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        try:
            vp = validate_path(args["path"], cfg=ctx.cfg, for_write=False)
        except FsPolicyError as e:
            raise ToolExecutionError(str(e))
        base = vp.path
        if not base.exists() or not base.is_dir():
            raise ToolExecutionError("Directory not found.")
        max_entries = max(1, min(int(args.get("max_entries") or 200), 2000))
        recursive = bool(args.get("recursive") or False)
        out: list[dict[str, Any]] = []
        it = base.rglob("*") if recursive else base.iterdir()
        for i, p in enumerate(it):
            if i >= max_entries:
                break
            try:
                out.append(
                    {
                        "path": str(p),
                        "name": p.name,
                        "is_dir": p.is_dir(),
                        "size": None if p.is_dir() else p.stat().st_size,
                    }
                )
            except Exception:
                continue
        return {"path": str(base), "recursive": recursive, "entries": out, "truncated": len(out) >= max_entries}


class FsReadTool(Tool):
    name = "fs.read_text"
    description = "Read a UTF-8 text file under allowed roots"
    args = (ToolArgument("path", str, "File path to read", required=True),)
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        try:
            vp = validate_path(args["path"], cfg=ctx.cfg, for_write=False)
        except FsPolicyError as e:
            raise ToolExecutionError(str(e))
        p = vp.path
        if not p.exists() or not p.is_file():
            raise ToolExecutionError("File not found.")
        raw = p.read_bytes()
        if len(raw) > ctx.cfg.fs.max_read_bytes:
            raise ToolExecutionError(f"File too large ({len(raw)} bytes), max={ctx.cfg.fs.max_read_bytes}.")
        return {"path": str(p), "content": raw.decode("utf-8", errors="replace"), "bytes": len(raw)}


class FsWriteTool(Tool):
    name = "fs.write_text"
    description = "Write a UTF-8 text file under allowed roots (journaled)"
    args = (
        ToolArgument("path", str, "File path to write", required=True),
        ToolArgument("content", str, "Text content", required=True),
        ToolArgument("reason", str, "Reason for this write", required=False, default=""),
    )
    safety_flags = ("filesystem", "write")
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        if ctx.cfg.mode == "unattended":
            # In unattended mode we still allow writes, but we keep strict policy and journaling.
            pass
        reason = (args.get("reason") or "").strip()
        # Preflight overwrite detection happens before any write.
        # We also validate/resolve the path here to avoid ambiguous relative paths.
        try:
            vp = validate_path(args["path"], cfg=ctx.cfg, for_write=True)
        except FsPolicyError as e:
            raise ToolExecutionError(str(e))
        _ = bool(os.path.exists(str(vp.path)) or os.path.islink(str(vp.path)))
        return ctx.journal.record_write(target=vp.path, new_text=args["content"], reason=reason)


class FsMoveTool(Tool):
    name = "fs.move"
    description = "Move/rename a file or directory under allowed roots (journaled)"
    args = (
        ToolArgument("src", str, "Source path", required=True),
        ToolArgument("dst", str, "Destination path", required=True),
        ToolArgument("overwrite", bool, "Overwrite destination if exists", required=False, default=False),
        ToolArgument("reason", str, "Reason for this move", required=False, default=""),
    )
    safety_flags = ("filesystem", "write")
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        return ctx.journal.record_move(
            src=args["src"],
            dst=args["dst"],
            reason=(args.get("reason") or "").strip(),
            overwrite=bool(args.get("overwrite") or False),
        )


class FsDeleteTool(Tool):
    name = "fs.delete"
    description = "Delete files/directories under allowed roots (journaled + rollback)"
    destructive = True
    args = (
        ToolArgument("paths", list, "List of paths to delete", required=True),
        ToolArgument("reason", str, "Reason for deletion", required=False, default=""),
    )
    safety_flags = ("filesystem", "delete")
    requires_confirmation = True

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        paths = args.get("paths") or []
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ToolExecutionError("paths must be a list of strings.")

        if ctx.cfg.mode == "unattended" and len(paths) > ctx.cfg.fs.max_delete_count:
            raise ToolExecutionError(
                f"Unattended mode: refusing to delete {len(paths)} paths (max_delete_count={ctx.cfg.fs.max_delete_count})."
            )

        results: list[dict[str, Any]] = []
        for p in paths:
            results.append(ctx.journal.record_delete(target=p, reason=(args.get("reason") or "").strip()))
        return {"deleted": len(results), "results": results}


class FsGrepTool(Tool):
    name = "fs.grep"
    description = "Search for a substring in text files under allowed roots"
    args = (
        ToolArgument("query", str, "Substring to find", required=True),
        ToolArgument("path", str, "Base directory", required=True),
        ToolArgument("glob", str, "Optional glob filter, e.g. *.py", required=False, default=""),
        ToolArgument("max_hits", int, "Max hits", required=False, default=200),
    )
    safety_flags = ("filesystem",)

    def run(self, ctx, args: dict[str, Any]) -> dict[str, Any]:
        query = (args.get("query") or "").strip()
        if not query:
            return {"hits": []}
        try:
            base = validate_path(args["path"], cfg=ctx.cfg, for_write=False).path
        except FsPolicyError as e:
            raise ToolExecutionError(str(e))
        if not base.exists() or not base.is_dir():
            raise ToolExecutionError("Directory not found.")

        max_hits = max(1, min(int(args.get("max_hits") or 200), 2000))
        glob_pat = (args.get("glob") or "").strip()
        hits: list[dict[str, Any]] = []

        for p in base.rglob("*"):
            if len(hits) >= max_hits:
                break
            if not p.is_file():
                continue
            if glob_pat and not fnmatch.fnmatch(p.name, glob_pat):
                continue
            # Avoid huge/binary files.
            try:
                if p.stat().st_size > ctx.cfg.fs.max_read_bytes:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            idx = text.find(query)
            if idx == -1:
                continue
            # Best-effort line number.
            line_no = text[:idx].count("\n") + 1
            hits.append({"path": str(p), "line": line_no})

        return {"query": query, "base": str(base), "hits": hits, "truncated": len(hits) >= max_hits}
