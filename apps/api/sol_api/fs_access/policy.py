from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import FsAccessDenied


@dataclass(frozen=True)
class FsPolicy:
    enabled: bool
    allow_all_paths: bool
    allowed_roots: tuple[Path, ...]
    allow_write: bool
    allow_delete: bool
    deny_write_drives: tuple[str, ...]
    max_read_bytes: int
    max_write_bytes: int


def is_within_root(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except Exception:
        try:
            resolved = str(path.resolve())
            root_resolved = str(root.resolve())
            return resolved == root_resolved or resolved.startswith(root_resolved + os.sep)
        except Exception:
            return False


def _drive_letter(path: Path) -> str | None:
    # Windows: Path("C:\\x").drive == "C:"
    drv = (getattr(path, "drive", "") or "").strip()
    if len(drv) == 2 and drv[1] == ":":
        return drv[0].upper()
    return None


def validate_path(path: Path, *, policy: FsPolicy, for_write: bool) -> Path:
    if not policy.enabled:
        raise FsAccessDenied("File system access is disabled.")
    if for_write and not policy.allow_write:
        raise FsAccessDenied("Write access is disabled.")

    try:
        resolved = path.expanduser().resolve()
    except Exception:
        raise FsAccessDenied("Invalid path.")

    if for_write:
        drv = _drive_letter(resolved)
        denied = {d.upper().rstrip(":") for d in policy.deny_write_drives}
        if drv and drv in denied:
            raise FsAccessDenied(f"Write access is denied on drive {drv}:")

    if policy.allow_all_paths:
        return resolved

    for root in policy.allowed_roots:
        if is_within_root(resolved, root):
            return resolved

    raise FsAccessDenied("Path is outside allowed roots.")
