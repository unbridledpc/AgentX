from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .errors import FsAccessDenied, FsAccessError
from .errors import FsNotFound, FsTooLarge
from .policy import FsPolicy, validate_path


def _safe_read_bytes(path: Path, *, max_bytes: int) -> bytes:
    size = path.stat().st_size
    if size > max_bytes:
        raise FsTooLarge(f"File too large ({size} bytes), max is {max_bytes}.")
    return path.read_bytes()


def read_text(path_str: str, *, policy: FsPolicy) -> dict:
    path = validate_path(Path(path_str), policy=policy, for_write=False)
    if not path.exists() or not path.is_file():
        raise FsNotFound("File not found.")
    raw = _safe_read_bytes(path, max_bytes=policy.max_read_bytes)
    text = raw.decode("utf-8", errors="replace")
    return {"path": str(path), "content": text, "bytes": len(raw)}


def write_text(path_str: str, content: str, *, policy: FsPolicy, create: bool = True, backup: bool = True) -> dict:
    path = validate_path(Path(path_str), policy=policy, for_write=True)
    if path.exists() and not path.is_file():
        raise FsNotFound("Path exists but is not a file.")
    if not path.exists() and not create:
        raise FsNotFound("File does not exist (create=false).")

    data = (content or "").encode("utf-8")
    if len(data) > policy.max_write_bytes:
        raise FsTooLarge(f"Write too large ({len(data)} bytes), max is {policy.max_write_bytes}.")

    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            backup_path.write_bytes(path.read_bytes())
        except Exception:
            backup_path = None

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)

    return {"path": str(path), "bytes_written": len(data), "backup_path": str(backup_path) if backup_path else None}


def list_dir(path_str: str, *, policy: FsPolicy, recursive: bool = False, max_entries: int = 500) -> dict:
    base = validate_path(Path(path_str), policy=policy, for_write=False)
    if not base.exists() or not base.is_dir():
        raise FsNotFound("Directory not found.")

    entries: list[dict] = []
    count = 0

    iterator = base.rglob("*") if recursive else base.iterdir()
    for p in iterator:
        if count >= max_entries:
            break
        try:
            is_dir = p.is_dir()
            size = None if is_dir else p.stat().st_size
            entries.append(
                {
                    "path": str(p),
                    "name": p.name,
                    "is_dir": bool(is_dir),
                    "size": size,
                }
            )
            count += 1
        except Exception:
            continue

    return {"path": str(base), "recursive": recursive, "entries": entries, "truncated": count >= max_entries}


def mkdir(path_str: str, *, policy: FsPolicy, parents: bool = True, exist_ok: bool = True) -> dict:
    path = validate_path(Path(path_str), policy=policy, for_write=True)
    try:
        path.mkdir(parents=bool(parents), exist_ok=bool(exist_ok))
    except Exception as e:
        raise FsAccessError(f"mkdir failed: {e}")
    return {"path": str(path), "created": True}


def delete_path(path_str: str, *, policy: FsPolicy, recursive: bool = False) -> dict:
    if not policy.allow_delete:
        raise FsAccessDenied("Delete is disabled (SOL_FS_DELETE_ENABLED=false).")
    path = validate_path(Path(path_str), policy=policy, for_write=True)
    if not path.exists():
        raise FsNotFound("Path not found.")
    try:
        if path.is_dir():
            if not recursive:
                raise FsAccessError("Refusing to delete directory without recursive=true.")
            shutil.rmtree(path)
        else:
            path.unlink()
    except FsAccessError:
        raise
    except Exception as e:
        raise FsAccessError(f"delete failed: {e}")
    return {"path": str(path), "deleted": True}


def move_path(src_str: str, dst_str: str, *, policy: FsPolicy, overwrite: bool = False, backup: bool = True) -> dict:
    src = validate_path(Path(src_str), policy=policy, for_write=True)
    dst = validate_path(Path(dst_str), policy=policy, for_write=True)
    if not src.exists():
        raise FsNotFound("Source not found.")
    if dst.exists() and not overwrite:
        raise FsAccessError("Destination exists (overwrite=false).")

    dst.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and dst.exists() and dst.is_file():
        backup_path = dst.with_suffix(dst.suffix + ".bak")
        try:
            backup_path.write_bytes(dst.read_bytes())
        except Exception:
            backup_path = None

    try:
        src.replace(dst)
    except Exception as e:
        raise FsAccessError(f"move failed: {e}")

    return {"src": str(src), "dst": str(dst), "backup_path": str(backup_path) if backup_path else None}


@dataclass(frozen=True)
class PatchFile:
    path: str
    hunks: list[tuple[int, int, list[str]]]  # (start_line, remove_count, new_lines)


_RE_DIFF_HEADER = re.compile(r"^\+\+\+\s+(?P<path>.+)$")
_RE_HUNK = re.compile(r"^@@\s+-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@")


def _parse_unified_diff(patch_text: str) -> list[PatchFile]:
    lines = (patch_text or "").splitlines()
    i = 0
    files: list[PatchFile] = []
    current_path: str | None = None
    hunks: list[tuple[int, int, list[str]]] = []

    while i < len(lines):
        line = lines[i]
        if line.startswith("+++ "):
            # finalize previous file
            if current_path is not None:
                files.append(PatchFile(path=current_path, hunks=hunks))
                hunks = []
            m = _RE_DIFF_HEADER.match(line)
            if not m:
                raise ValueError("Malformed diff header.")
            raw_path = m.group("path").strip()
            # normalize "b/..."
            if raw_path.startswith("b/") or raw_path.startswith("a/"):
                raw_path = raw_path[2:]
            current_path = raw_path
            i += 1
            continue

        if line.startswith("@@ "):
            m = _RE_HUNK.match(line)
            if not m:
                raise ValueError("Malformed hunk header.")
            old_start = int(m.group(1))
            old_count = int(m.group(2) or "1")
            i += 1
            new_lines: list[str] = []
            consumed_old = 0
            while i < len(lines):
                l = lines[i]
                if l.startswith("@@ ") or l.startswith("+++ "):
                    break
                if l.startswith("-"):
                    consumed_old += 1
                elif l.startswith("+"):
                    new_lines.append(l[1:])
                elif l.startswith(" "):
                    consumed_old += 1
                    new_lines.append(l[1:])
                elif l.startswith("\\"):
                    # "\ No newline at end of file" ignore
                    pass
                else:
                    raise ValueError("Malformed diff line.")
                i += 1
            # represent as: replace old_count lines starting at old_start with new_lines (best-effort)
            hunks.append((old_start, old_count, new_lines))
            continue

        i += 1

    if current_path is not None:
        files.append(PatchFile(path=current_path, hunks=hunks))
    if not files:
        raise ValueError("No files found in patch.")
    return files


def apply_unified_diff(patch_text: str, *, policy: FsPolicy, backup: bool = True) -> dict:
    files = _parse_unified_diff(patch_text)
    results: list[dict] = []

    for f in files:
        # Only allow patching absolute paths if allow_all_paths is enabled; otherwise treat as relative to an allowed root.
        p = Path(f.path)
        if not p.is_absolute() and policy.allowed_roots:
            # Use the first root as base for relative patches.
            p = policy.allowed_roots[0] / p
        path = validate_path(p, policy=policy, for_write=True)

        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            original_lines = text.splitlines()
        else:
            original_lines = []

        new_lines = original_lines[:]
        # Apply hunks in reverse order so line offsets don't shift earlier hunks.
        for (start_line, remove_count, insert_lines) in reversed(f.hunks):
            idx = max(0, start_line - 1)
            new_lines[idx : idx + remove_count] = insert_lines

        new_text = "\n".join(new_lines) + ("\n" if new_lines else "")
        write_result = write_text(str(path), new_text, policy=policy, create=True, backup=backup)
        results.append(
            {
                "file": str(path),
                "backup_path": write_result.get("backup_path"),
                "bytes_written": write_result.get("bytes_written"),
            }
        )

    return {"applied": True, "files": results}
