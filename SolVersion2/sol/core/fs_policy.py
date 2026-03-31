from __future__ import annotations

import os
import re
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

from sol.config import SolConfig


class FsPolicyError(PermissionError):
    pass


_CRED_EXTENSIONS = {
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".kdbx",
    ".ovpn",
    ".rdp",
    ".env",
}


def _drive_letter(p: Path) -> str | None:
    drv = (getattr(p, "drive", "") or "").strip()
    if len(drv) == 2 and drv[1] == ":":
        return drv[0].upper()
    return None


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except Exception:
        try:
            resolved = str(path.resolve())
            root_resolved = str(root.resolve())
            return resolved == root_resolved or resolved.startswith(root_resolved + os.sep)
        except Exception:
            return False


@dataclass(frozen=True)
class ValidatedPath:
    path: Path
    drive: str | None


@lru_cache(maxsize=32)
def _compile_denied_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pat in patterns or ():
        if not pat:
            continue
        compiled.append(re.compile(pat))
    return tuple(compiled)


def validate_path(raw: str | Path, *, cfg: SolConfig, for_write: bool) -> ValidatedPath:
    if isinstance(raw, Path):
        p = raw
    else:
        p = Path(str(raw))

    try:
        resolved = p.expanduser().resolve()
    except Exception as e:
        raise FsPolicyError(f"Invalid path: {e}")

    # UNSAFE MODE: when enabled for the current request/thread, bypass all fs policy restrictions.
    try:
        from sol.core.unsafe_mode import current_thread_id, is_unsafe_enabled

        if is_unsafe_enabled(current_thread_id()):
            drv = _drive_letter(resolved)
            return ValidatedPath(path=resolved, drive=drv)
    except Exception:
        # Fail-closed: if unsafe checks are unavailable, keep normal policy.
        pass

    drv = _drive_letter(resolved)
    denied_drives = {d.upper().rstrip(":") for d in (cfg.fs.deny_drive_letters or ())}
    if drv and drv in denied_drives:
        raise FsPolicyError(f"Drive {drv}: is denied.")

    implicit_roots = []
    for candidate in (
        getattr(getattr(cfg, "paths", None), "app_root", None),
        getattr(getattr(cfg, "paths", None), "working_dir", None),
    ):
        if candidate is None:
            continue
        try:
            implicit_roots.append(Path(candidate).resolve())
        except Exception:
            continue

    configured_roots = tuple(cfg.fs.allowed_roots or ())
    effective_roots = tuple(dict.fromkeys(list(configured_roots) + implicit_roots))

    if not effective_roots:
        raise FsPolicyError("No allowed_roots configured.")

    allowed = any(_is_within_root(resolved, root) for root in effective_roots)
    if not allowed:
        raise FsPolicyError("Path is outside allowed_roots.")

    # Hard deny by substring.
    lowered = str(resolved).lower()
    for needle in cfg.fs.denied_substrings or ():
        n = (needle or "").strip().lower()
        if not n:
            continue
        if n in lowered:
            raise FsPolicyError(f"Path blocked by denied_substrings: {needle!r}")

    # Hard deny by regex patterns.
    denied_patterns = _compile_denied_patterns(tuple(cfg.fs.denied_path_patterns or ()))
    for pat in denied_patterns:
        if pat.search(str(resolved)):
            raise FsPolicyError(f"Path blocked by denied_path_patterns: {pat.pattern!r}")

    # Hard deny common credential-like extensions.
    ext = resolved.suffix.lower()
    if ext in _CRED_EXTENSIONS:
        raise FsPolicyError(f"Credential-like file extension is denied: {ext}")

    # Unattended safety: treat writes as privileged operations.
    if cfg.mode == "unattended" and for_write:
        # Writes are allowed, but policy checks are enforced by tools (confirmation + limits).
        pass

    return ValidatedPath(path=resolved, drive=drv)
