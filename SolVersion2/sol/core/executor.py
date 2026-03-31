from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from sol.config import SolConfig
from sol.core.fs_policy import FsPolicyError, validate_path


class ExecPolicyError(PermissionError):
    pass


@dataclass(frozen=True)
class ExecResult:
    cmd: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float


def _normalize_cmd(cmd: str | list[str]) -> list[str]:
    if isinstance(cmd, list):
        return [str(x) for x in cmd if str(x)]
    s = (cmd or "").strip()
    if not s:
        return []
    # Windows-friendly split; still best-effort.
    return shlex.split(s, posix=False)


def _base_exe(token0: str) -> str:
    t = token0.strip().strip('"')
    return Path(t).name.lower()


def _is_bare_command(token0: str) -> bool:
    s = (token0 or "").strip().strip('"')
    if not s:
        return False
    # Reject anything that looks like a path.
    if any(x in s for x in ("\\", "/", ":")):
        return False
    return True


def _resolve_windows_npm(argv0: str, *, env: dict[str, str]) -> tuple[str, str] | None:
    """Resolve npm/npx to npm.cmd/npx.cmd on Windows, without enabling arbitrary .cmd execution."""
    if os.name != "nt":
        return None
    base = _base_exe(argv0)
    if base not in ("npm", "npx", "npm.cmd", "npx.cmd"):
        return None
    if not _is_bare_command(argv0):
        raise ExecPolicyError("Refusing to execute a .cmd path; use bare `npm`/`npx` only.")

    canonical = "npm" if base.startswith("npm") else "npx"
    resolved = shutil.which(canonical + ".cmd", path=env.get("PATH")) or shutil.which(canonical + ".exe", path=env.get("PATH"))
    if not resolved:
        return None
    return resolved, canonical


def _has_denied_extension(argv: list[str], denied_exts: tuple[str, ...]) -> str | None:
    exts = {e.lower() for e in denied_exts if e}
    for a in argv:
        s = a.strip().strip('"')
        ext = Path(s).suffix.lower()
        if ext and ext in exts:
            return ext
    return None


def run_command(
    *,
    cmd: str | list[str],
    cfg: SolConfig,
    cwd: str | Path | None = None,
) -> ExecResult:
    if not cfg.exec.enabled:
        raise ExecPolicyError("Command execution disabled by config.")

    argv = _normalize_cmd(cmd)
    if not argv:
        raise ExecPolicyError("Empty command.")

    env = os.environ.copy()
    exe = _base_exe(argv[0])
    # Windows: allow npm/npx to resolve to their .cmd shims (narrow exception).
    resolved = _resolve_windows_npm(argv[0], env=env)
    if resolved:
        resolved_path, canonical = resolved
        argv = list(argv)
        argv[0] = resolved_path
        exe = canonical
    allowed = set(cfg.exec.allowed_commands or ())
    if allowed and exe not in allowed:
        raise ExecPolicyError(f"Executable not in allowlist: {exe}")

    # Block arbitrary .cmd/.bat execution even in supervised mode; allow npm/npx only via resolver.
    resolved_ext = Path(str(argv[0]).strip().strip('"')).suffix.lower()
    if resolved_ext in (".cmd", ".bat") and exe not in ("npm", "npx"):
        raise ExecPolicyError(f"Refusing to execute {resolved_ext} scripts (only npm/npx are allowed).")

    if not cfg.exec.allow_shell:
        shell = False
    else:
        # Intentionally not supported in this runner.
        raise ExecPolicyError("Shell execution is not allowed.")

    if cfg.mode == "unattended":
        denied_ext = _has_denied_extension(argv, cfg.exec.deny_extensions)
        if denied_ext:
            raise ExecPolicyError(f"Unattended mode blocks executing {denied_ext} files.")

    cwd_path: Path | None = None
    if cwd:
        try:
            v = validate_path(cwd, cfg=cfg, for_write=False)
            if not v.path.exists() or not v.path.is_dir():
                raise ExecPolicyError("cwd is not a directory.")
            cwd_path = v.path
        except FsPolicyError as e:
            raise ExecPolicyError(str(e))

    started = time.perf_counter()
    try:
        p = subprocess.run(
            argv,
            cwd=str(cwd_path) if cwd_path else None,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(cfg.exec.timeout_s)),
            env=env,
        )
    except FileNotFoundError as e:
        raise ExecPolicyError(f"Executable not found: {argv[0]}") from e
    ended = time.perf_counter()
    return ExecResult(
        cmd=argv,
        cwd=str(cwd_path) if cwd_path else "",
        returncode=int(p.returncode),
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        duration_ms=(ended - started) * 1000.0,
    )
