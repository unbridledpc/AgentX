from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentx_api.config import config


DEFAULT_TIMEOUT_S = int(os.environ.get("AGENTX_VALIDATION_TIMEOUT_S", "120") or "120")
MAX_OUTPUT_CHARS = int(os.environ.get("AGENTX_VALIDATION_MAX_OUTPUT_CHARS", "12000") or "12000")
ALLOW_CUSTOM_COMMANDS = (os.environ.get("AGENTX_VALIDATION_ALLOW_CUSTOM", "false") or "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_PATCH_CHARS = int(os.environ.get("AGENTX_VALIDATION_MAX_PATCH_CHARS", "200000") or "200000")


@dataclass
class ValidationCommand:
    name: str
    argv: list[str]
    cwd: str = "."
    timeout_s: int = DEFAULT_TIMEOUT_S
    required: bool = True


@dataclass
class ValidationStepResult:
    name: str
    command: str
    cwd: str
    exit_code: int | None
    ok: bool
    duration_ms: float
    stdout: str
    stderr: str
    timeout: bool = False
    skipped: bool = False
    error: str | None = None


@dataclass
class ValidationRunResult:
    ok: bool
    run_id: str
    preset: str
    workspace_path: str
    started_at: float
    duration_ms: float
    results: list[ValidationStepResult]
    summary: dict[str, Any]


@dataclass
class PatchCandidateResult:
    ok: bool
    candidate_id: str
    source_workspace_path: str
    temp_workspace_path: str | None
    preset: str
    started_at: float
    duration_ms: float
    kept: bool
    apply_result: ValidationStepResult
    validation_result: ValidationRunResult | None
    summary: dict[str, Any]
    repair_packet: dict[str, Any] | None = None
    repair_of_candidate_id: str | None = None


class ValidationError(ValueError):
    pass


def _cmd(name: str, argv: list[str], cwd: str = ".", timeout_s: int = DEFAULT_TIMEOUT_S, required: bool = True) -> ValidationCommand:
    return ValidationCommand(name=name, argv=argv, cwd=cwd, timeout_s=timeout_s, required=required)


PRESETS: dict[str, list[ValidationCommand]] = {
    "agentx_api": [
        _cmd("api_compile_config", ["python3", "-m", "py_compile", "agentx_api/config.py"], cwd="apps/api"),
        _cmd("api_compile_app", ["python3", "-m", "py_compile", "agentx_api/app.py"], cwd="apps/api"),
        _cmd("api_compile_runtime_guard", ["python3", "-m", "py_compile", "agentx_api/runtime_guard.py"], cwd="apps/api"),
        _cmd("api_compile_model_ops", ["python3", "-m", "py_compile", "agentx_api/routes/model_ops.py"], cwd="apps/api"),
        _cmd("api_compile_validation", ["python3", "-m", "py_compile", "agentx_api/validation_runner.py", "agentx_api/routes/validation.py"], cwd="apps/api"),
    ],
    "agentx_web": [
        _cmd("web_vite_build", ["node", "./node_modules/vite/bin/vite.js", "build"], cwd="AgentXWeb", timeout_s=180),
    ],
    "agentx_full": [
        _cmd("api_compile_config", ["python3", "-m", "py_compile", "agentx_api/config.py"], cwd="apps/api"),
        _cmd("api_compile_app", ["python3", "-m", "py_compile", "agentx_api/app.py"], cwd="apps/api"),
        _cmd("api_compile_runtime_guard", ["python3", "-m", "py_compile", "agentx_api/runtime_guard.py"], cwd="apps/api"),
        _cmd("api_compile_model_ops", ["python3", "-m", "py_compile", "agentx_api/routes/model_ops.py"], cwd="apps/api"),
        _cmd("api_compile_validation", ["python3", "-m", "py_compile", "agentx_api/validation_runner.py", "agentx_api/routes/validation.py"], cwd="apps/api"),
        _cmd("web_vite_build", ["node", "./node_modules/vite/bin/vite.js", "build"], cwd="AgentXWeb", timeout_s=180),
    ],
    "python_basic": [
        _cmd("python_compileall_api", ["python3", "-m", "compileall", "-q", "apps/api/agentx_api"], cwd="."),
    ],
    "node_basic": [
        _cmd("npm_build", ["npm", "run", "build"], cwd="AgentXWeb", timeout_s=180),
    ],
}


def _looks_like_agentx_root(path: Path) -> bool:
    return (path / "AgentXWeb").is_dir() and (path / "apps" / "api").is_dir()


def _workspace_kind(path: Path) -> str:
    if _looks_like_agentx_root(path):
        return "agentx_root"
    if path.name == "AgentXWeb" and (path / "package.json").exists():
        return "agentx_web"
    if path.name == "api" and path.parent.name == "apps" and (path / "agentx_api").is_dir():
        return "agentx_api"
    if (path / "package.json").exists():
        return "node_project"
    if any(path.glob("*.py")) or (path / "pyproject.toml").exists():
        return "python_project"
    return "directory"


def _candidate_paths() -> list[Path]:
    raw: list[Path] = []
    env_root = os.environ.get("AGENTX_WORKSPACE_ROOT") or os.environ.get("AGENTX_REPO_ROOT")
    if env_root:
        raw.append(Path(env_root).expanduser())
    raw.extend([
        Path.cwd(),
        Path(__file__).resolve().parents[3],
        Path.home() / "projects" / "AgentX",
        Path.home() / "AgentX",
    ])
    for root in _allowed_workspace_roots():
        raw.append(root)
        raw.append(root / "AgentX")
        raw.append(root / "projects" / "AgentX")

    seen: list[Path] = []
    for item in raw:
        try:
            resolved = item.resolve()
        except Exception:
            continue
        if resolved.exists() and resolved.is_dir() and resolved not in seen:
            seen.append(resolved)
    return seen


def discover_workspaces() -> list[dict[str, Any]]:
    """Return likely validation workspace shortcuts for the UI."""
    candidates: dict[str, dict[str, Any]] = {}

    def add(label: str, path: Path, preset: str, kind: str, confidence: int) -> None:
        try:
            resolved = path.resolve()
        except Exception:
            return
        if not resolved.exists() or not resolved.is_dir():
            return
        key = str(resolved)
        current = candidates.get(key)
        if current and int(current.get("confidence", 0)) >= confidence:
            return
        candidates[key] = {
            "label": label,
            "path": key,
            "preset": preset,
            "kind": kind,
            "confidence": confidence,
        }

    for base in _candidate_paths():
        kind = _workspace_kind(base)
        if kind == "agentx_root":
            add("AgentX Root", base, "agentx_full", "agentx_root", 100)
            add("AgentX API", base, "agentx_api", "agentx_root", 95)
            add("AgentX Web", base, "agentx_web", "agentx_root", 95)
            add("AgentX API Folder", base / "apps" / "api", "agentx_api", "agentx_api", 80)
            add("AgentX Web Folder", base / "AgentXWeb", "agentx_web", "agentx_web", 80)
        elif kind == "agentx_web":
            add("AgentX Web Folder", base, "agentx_web", kind, 80)
            parent = base.parent
            if _looks_like_agentx_root(parent):
                add("AgentX Root", parent, "agentx_full", "agentx_root", 100)
        elif kind == "agentx_api":
            add("AgentX API Folder", base, "agentx_api", kind, 80)
            parent = base.parent.parent
            if _looks_like_agentx_root(parent):
                add("AgentX Root", parent, "agentx_full", "agentx_root", 100)
        elif kind in {"node_project", "python_project"}:
            add(base.name or "Workspace", base, "node_basic" if kind == "node_project" else "python_basic", kind, 40)

    out = sorted(candidates.values(), key=lambda item: (-int(item.get("confidence", 0)), str(item.get("label", "")), str(item.get("path", ""))))
    return out[:12]


def preset_summary() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, commands in PRESETS.items():
        out.append(
            {
                "name": name,
                "commands": [
                    {
                        "name": c.name,
                        "command": shlex.join(c.argv),
                        "cwd": c.cwd,
                        "timeout_s": c.timeout_s,
                        "required": c.required,
                    }
                    for c in commands
                ],
            }
        )
    return out


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    keep = max(1000, MAX_OUTPUT_CHARS - 200)
    return text[:keep] + f"\n\n[AgentX truncated output: {len(text) - keep} chars omitted]"


def _allowed_workspace_roots() -> list[Path]:
    roots: list[Path] = []
    for p in getattr(config, "fs_allowed_roots", []) or []:
        roots.append(Path(p).expanduser())
    # Practical local defaults for AgentX installs and the API package itself.
    roots.extend(
        [
            Path.cwd(),
            Path(__file__).resolve().parents[3],
            Path.home(),
        ]
    )
    seen: list[Path] = []
    for root in roots:
        try:
            rp = root.resolve()
        except Exception:
            continue
        if rp not in seen:
            seen.append(rp)
    return seen


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_workspace(path: str) -> Path:
    raw = Path(path).expanduser()
    try:
        workspace = raw.resolve()
    except Exception as exc:
        raise ValidationError(f"Workspace path is not accessible: {exc}") from exc
    if not workspace.exists() or not workspace.is_dir():
        raise ValidationError(f"Workspace path must be an existing directory: {workspace}")

    if getattr(config, "fs_allow_all_paths", False):
        return workspace

    allowed = _allowed_workspace_roots()
    if not any(_is_relative_to(workspace, root) for root in allowed):
        roots = ", ".join(str(r) for r in allowed[:8])
        raise ValidationError(f"Workspace is outside allowed roots. Allowed roots include: {roots}")
    return workspace


def _resolve_cwd(workspace: Path, cwd: str) -> Path:
    rel = Path(cwd or ".")
    if rel.is_absolute():
        raise ValidationError("Validation command cwd must be relative to the workspace.")

    # UX guardrail: presets are written for the AgentX repo root, but users often
    # paste the specific component folder. If the selected workspace already ends
    # with the preset cwd, use it directly instead of double-appending it.
    rel_posix = rel.as_posix().strip("/")
    workspace_posix = workspace.as_posix().rstrip("/")
    if rel_posix in {"", "."}:
        out = workspace.resolve()
    elif workspace.name == rel.name or workspace_posix.endswith("/" + rel_posix):
        out = workspace.resolve()
    else:
        out = (workspace / rel).resolve()

    if not _is_relative_to(out, workspace) and out != workspace:
        raise ValidationError("Validation command cwd escapes the workspace.")
    if not out.exists() or not out.is_dir():
        attempted = workspace / rel
        raise ValidationError(f"Validation command cwd does not exist: {rel} (tried {attempted})")
    return out


def _validate_argv(argv: list[str]) -> None:
    if not argv:
        raise ValidationError("Validation command argv cannot be empty.")
    blocked = {"rm", "rmdir", "mv", "dd", "mkfs", "shutdown", "reboot", "sudo", "su", "chmod", "chown"}
    exe = Path(argv[0]).name.lower()
    if exe in blocked:
        raise ValidationError(f"Blocked validation command: {exe}")
    for arg in argv:
        if "\x00" in arg:
            raise ValidationError("Validation command contains a null byte.")


def _load_commands(preset: str, commands: list[dict[str, Any]] | None = None) -> list[ValidationCommand]:
    if preset == "custom":
        if not ALLOW_CUSTOM_COMMANDS:
            raise ValidationError("Custom validation commands are disabled. Set AGENTX_VALIDATION_ALLOW_CUSTOM=true to enable them.")
        if not commands:
            raise ValidationError("Custom preset requires at least one command.")
        out: list[ValidationCommand] = []
        for idx, item in enumerate(commands[:8]):
            argv = item.get("argv")
            if isinstance(argv, str):
                argv = shlex.split(argv)
            if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
                raise ValidationError(f"Custom command {idx + 1} needs argv as a string array or shell-like string.")
            timeout_s = int(item.get("timeout_s") or DEFAULT_TIMEOUT_S)
            out.append(
                ValidationCommand(
                    name=str(item.get("name") or f"custom_{idx + 1}"),
                    argv=argv,
                    cwd=str(item.get("cwd") or "."),
                    timeout_s=max(1, min(timeout_s, 600)),
                    required=bool(item.get("required", True)),
                )
            )
        return out
    if preset not in PRESETS:
        raise ValidationError(f"Unknown validation preset: {preset}")
    return list(PRESETS[preset])


def _run_one(workspace: Path, command: ValidationCommand) -> ValidationStepResult:
    started = time.perf_counter()
    command_str = shlex.join(command.argv)
    try:
        _validate_argv(command.argv)
        cwd = _resolve_cwd(workspace, command.cwd)
    except Exception as exc:
        return ValidationStepResult(
            name=command.name,
            command=command_str,
            cwd=command.cwd,
            exit_code=None,
            ok=False,
            duration_ms=(time.perf_counter() - started) * 1000,
            stdout="",
            stderr="",
            error=str(exc),
        )

    env = os.environ.copy()
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")
    try:
        proc = subprocess.run(
            command.argv,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=command.timeout_s,
            shell=False,
        )
        duration = (time.perf_counter() - started) * 1000
        ok = proc.returncode == 0 or not command.required
        return ValidationStepResult(
            name=command.name,
            command=command_str,
            cwd=str(cwd.relative_to(workspace)),
            exit_code=proc.returncode,
            ok=ok,
            duration_ms=duration,
            stdout=_truncate(proc.stdout or ""),
            stderr=_truncate(proc.stderr or ""),
        )
    except subprocess.TimeoutExpired as exc:
        duration = (time.perf_counter() - started) * 1000
        return ValidationStepResult(
            name=command.name,
            command=command_str,
            cwd=str(cwd.relative_to(workspace)),
            exit_code=None,
            ok=False,
            duration_ms=duration,
            stdout=_truncate(exc.stdout or ""),
            stderr=_truncate(exc.stderr or ""),
            timeout=True,
            error=f"Timed out after {command.timeout_s}s",
        )
    except FileNotFoundError as exc:
        duration = (time.perf_counter() - started) * 1000
        return ValidationStepResult(
            name=command.name,
            command=command_str,
            cwd=str(cwd.relative_to(workspace)),
            exit_code=None,
            ok=False,
            duration_ms=duration,
            stdout="",
            stderr="",
            error=f"Command not found: {command.argv[0]}",
        )
    except Exception as exc:
        duration = (time.perf_counter() - started) * 1000
        return ValidationStepResult(
            name=command.name,
            command=command_str,
            cwd=str(cwd.relative_to(workspace)),
            exit_code=None,
            ok=False,
            duration_ms=duration,
            stdout="",
            stderr="",
            error=str(exc),
        )


def _history_base() -> Path:
    base = getattr(config, "settings_path", Path("settings.json")).parent
    base.mkdir(parents=True, exist_ok=True)
    return base


def _history_path() -> Path:
    return _history_base() / "validation_runs.jsonl"


def _patch_candidate_history_path() -> Path:
    return _history_base() / "validation_patch_candidates.jsonl"


def _write_history(result: ValidationRunResult) -> None:
    try:
        with _history_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_history(limit: int = 25) -> list[dict[str, Any]]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(limit, 100)) :]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _patch_candidate_record(result: PatchCandidateResult, patch_text: str, repair_of_candidate_id: str | None = None) -> dict[str, Any]:
    validation = result.validation_result
    first_failed_step = None
    if validation:
        first_failed_step = next((step.name for step in validation.results if not step.ok), None)
    apply_error = result.apply_result.error or result.apply_result.stderr or result.apply_result.stdout
    validation_error = None
    if validation:
        failed = next((step for step in validation.results if not step.ok), None)
        if failed:
            validation_error = failed.error or failed.stderr or failed.stdout
    return {
        "candidate_id": result.candidate_id,
        "repair_of_candidate_id": repair_of_candidate_id or result.repair_of_candidate_id,
        "ok": result.ok,
        "preset": result.preset,
        "source_workspace_path": result.source_workspace_path,
        "temp_workspace_path": result.temp_workspace_path,
        "kept": result.kept,
        "started_at": result.started_at,
        "duration_ms": result.duration_ms,
        "phase": result.summary.get("phase"),
        "summary": result.summary,
        "apply_ok": result.apply_result.ok,
        "apply_step": result.apply_result.name,
        "apply_error_excerpt": _compact_output(apply_error, 1200),
        "validation_ok": validation.ok if validation else None,
        "validation_run_id": validation.run_id if validation else None,
        "validation_first_failure": first_failed_step,
        "validation_error_excerpt": _compact_output(validation_error, 1600),
        "repair_packet_title": result.repair_packet.get("title") if result.repair_packet else None,
        "has_repair_packet": bool(result.repair_packet),
        "patch_excerpt": _compact_output(patch_text, 2500),
    }


def _write_patch_candidate_history(result: PatchCandidateResult, patch_text: str, repair_of_candidate_id: str | None = None) -> None:
    try:
        record = _patch_candidate_record(result, patch_text, repair_of_candidate_id)
        with _patch_candidate_history_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_patch_candidate_history(limit: int = 25) -> list[dict[str, Any]]:
    path = _patch_candidate_history_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(limit, 100)) :]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _finalize_patch_candidate(result: PatchCandidateResult, patch_text: str, repair_of_candidate_id: str | None = None) -> PatchCandidateResult:
    result.repair_of_candidate_id = repair_of_candidate_id
    _write_patch_candidate_history(result, patch_text, repair_of_candidate_id)
    return result


def _run_validation_workspace(workspace: Path, preset: str, commands: list[dict[str, Any]] | None = None, *, run_id_prefix: str = "val") -> ValidationRunResult:
    started_at = time.time()
    perf_start = time.perf_counter()
    run_id = f"{run_id_prefix}_{uuid.uuid4().hex[:12]}"
    workspace = workspace.resolve()
    plan = _load_commands(preset, commands)

    results: list[ValidationStepResult] = []
    for command in plan:
        result = _run_one(workspace, command)
        results.append(result)
        if not result.ok and command.required:
            # v1 stops after first required failure. That keeps feedback tight and avoids noisy cascades.
            break

    required_results = [r for r in results if not r.skipped]
    ok = all(r.ok for r in required_results)
    duration_ms = (time.perf_counter() - perf_start) * 1000
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "timeouts": sum(1 for r in results if r.timeout),
        "first_failure": next((r.name for r in results if not r.ok), None),
    }
    out = ValidationRunResult(
        ok=ok,
        run_id=run_id,
        preset=preset,
        workspace_path=str(workspace),
        started_at=started_at,
        duration_ms=duration_ms,
        results=results,
        summary=summary,
    )
    _write_history(out)
    return out



def _compact_output(value: str | None, limit: int = 4000) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    head = max(1000, limit // 2)
    tail = max(1000, limit - head - 120)
    return text[:head] + f"\n\n[AgentX repair packet truncated {len(text) - head - tail} chars]\n\n" + text[-tail:]


def _step_failure_summary(step: ValidationStepResult) -> dict[str, Any]:
    return {
        "name": step.name,
        "command": step.command,
        "cwd": step.cwd,
        "exit_code": step.exit_code,
        "timeout": step.timeout,
        "error": step.error,
        "stderr": _compact_output(step.stderr, 3000),
        "stdout": _compact_output(step.stdout, 1500),
    }


def build_repair_packet(
    *,
    candidate_id: str,
    source_workspace: Path,
    preset: str,
    patch_text: str,
    apply_result: ValidationStepResult,
    validation_result: ValidationRunResult | None,
    phase: str,
) -> dict[str, Any]:
    """Create a copy/paste repair packet for a model or human reviewer.

    v7 intentionally stops short of auto-correction. This packet is the safe bridge:
    the failed candidate is summarized with exact logs and a strict prompt that asks for
    a replacement unified diff only.
    """
    failed_steps: list[dict[str, Any]] = []
    if not apply_result.ok:
        failed_steps.append(_step_failure_summary(apply_result))
    if validation_result:
        failed_steps.extend(_step_failure_summary(step) for step in validation_result.results if not step.ok)

    first = failed_steps[0] if failed_steps else {}
    first_name = str(first.get("name") or phase)
    title = f"Repair patch candidate {candidate_id}: {first_name} failed"
    summary_lines = [
        f"Patch candidate {candidate_id} failed during {phase}.",
        f"Workspace: {source_workspace}",
        f"Preset: {preset}",
    ]
    if first.get("error"):
        summary_lines.append(f"First error: {first.get('error')}")
    if first.get("stderr"):
        stderr_one = str(first.get("stderr") or "").strip().splitlines()[:3]
        if stderr_one:
            summary_lines.append("First stderr: " + " | ".join(stderr_one))

    patch_excerpt = _compact_output(patch_text, 9000)
    log_lines: list[str] = []
    log_lines.append(f"## Patch apply: {apply_result.name} - {'PASS' if apply_result.ok else 'FAIL'}")
    log_lines.append(f"cwd: {apply_result.cwd}")
    log_lines.append(f"command: {apply_result.command}")
    log_lines.append(f"exit: {apply_result.exit_code}")
    if apply_result.error:
        log_lines.append(f"error: {apply_result.error}")
    if apply_result.stderr:
        log_lines.append("stderr:\n" + _compact_output(apply_result.stderr, 4000))
    if apply_result.stdout:
        log_lines.append("stdout:\n" + _compact_output(apply_result.stdout, 2500))
    if validation_result:
        log_lines.append(f"\n## Validation: {validation_result.run_id} - {'PASS' if validation_result.ok else 'FAIL'}")
        for step in validation_result.results:
            if step.ok:
                continue
            log_lines.append(f"\n### {step.name} - FAIL")
            log_lines.append(f"cwd: {step.cwd}")
            log_lines.append(f"command: {step.command}")
            log_lines.append(f"exit: {step.exit_code}")
            if step.error:
                log_lines.append(f"error: {step.error}")
            if step.stderr:
                log_lines.append("stderr:\n" + _compact_output(step.stderr, 4000))
            if step.stdout:
                log_lines.append("stdout:\n" + _compact_output(step.stdout, 2500))
    logs_excerpt = _compact_output("\n".join(log_lines), 12000)

    prompt = f"""You are repairing an AgentX patch candidate.

Goal: produce a corrected unified diff that preserves the original intent and fixes the failure below.

Hard rules:
- Output only a unified diff / git patch.
- Do not include prose outside the patch.
- Keep the patch minimal and scoped to the original change.
- Do not delete unrelated files.
- Do not introduce network calls, secrets, sudo, chmod/chown, destructive shell commands, or broad rewrites.
- Preserve AgentX's existing repo structure and validation preset expectations.

Candidate: {candidate_id}
Workspace: {source_workspace}
Validation preset: {preset}
Failed phase: {phase}

Failure summary:
{chr(10).join(summary_lines)}

Validation/apply logs:
{logs_excerpt}

Original patch candidate:
{patch_excerpt}
"""

    return {
        "created_at": time.time(),
        "candidate_id": candidate_id,
        "phase": phase,
        "title": title,
        "summary": "\n".join(summary_lines),
        "failed_steps": failed_steps,
        "recommended_next_steps": [
            "Copy the repair prompt into AgentX chat with a capable code model.",
            "Ask for a corrected unified diff only.",
            "Paste the repaired diff back into Patch Candidate Validation.",
            "Only apply to the live repo after candidate validation passes.",
        ],
        "prompt": prompt,
        "original_patch_excerpt": patch_excerpt,
        "logs_excerpt": logs_excerpt,
    }

_PATCH_COPY_IGNORE = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".agentx",
    "__pycache__",
    "dist",
    "build",
    "logs",
    "runtime",
    "cache",
    "tmp",
    "work",
}
_PATCH_SYMLINK_DIRS = {
    "node_modules",
    ".venv",
    "venv",
}


def _ignore_patch_copy(src: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in _PATCH_COPY_IGNORE or name in _PATCH_SYMLINK_DIRS:
            ignored.add(name)
    return ignored


def _symlink_dependency_dirs(source: Path, temp_root: Path) -> None:
    """Keep patch-candidate copies small while still allowing local builds to run."""
    candidates = [
        (source / "node_modules", temp_root / "node_modules"),
        (source / ".venv", temp_root / ".venv"),
        (source / "venv", temp_root / "venv"),
        (source / "AgentXWeb" / "node_modules", temp_root / "AgentXWeb" / "node_modules"),
        (source / "apps" / "desktop" / "node_modules", temp_root / "apps" / "desktop" / "node_modules"),
    ]
    for src, dst in candidates:
        try:
            if src.exists() and not dst.exists() and dst.parent.exists():
                dst.symlink_to(src, target_is_directory=True)
        except Exception:
            # Symlinks are an optimization. Validation can still report the missing dependency clearly.
            continue


def _patch_candidate_parent() -> Path:
    parent = Path(tempfile.gettempdir()) / "agentx_patch_candidates"
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def _copy_workspace_for_patch_candidate(source: Path, candidate_id: str) -> Path:
    dest = _patch_candidate_parent() / candidate_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(source, dest, ignore=_ignore_patch_copy, symlinks=True)
    _symlink_dependency_dirs(source, dest)
    return dest.resolve()


def validate_patch_candidate(workspace_path: str, preset: str, patch_text: str, keep_worktree: bool = False, repair_of_candidate_id: str | None = None) -> PatchCandidateResult:
    """Apply a unified diff to a temporary copy, then run validation there.

    This is intentionally conservative: the source workspace is never edited and validation runs
    against a disposable working tree. The caller can opt into keeping the temp tree for inspection.
    """
    started_at = time.time()
    perf_start = time.perf_counter()
    candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
    source = resolve_workspace(workspace_path)
    patch_text = patch_text or ""
    if not patch_text.strip():
        raise ValidationError("Patch text is required.")
    if len(patch_text) > MAX_PATCH_CHARS:
        raise ValidationError(f"Patch is too large for candidate validation ({len(patch_text)} chars > {MAX_PATCH_CHARS}).")
    if "\x00" in patch_text:
        raise ValidationError("Patch contains a null byte.")

    temp_workspace: Path | None = None
    apply_result: ValidationStepResult | None = None
    validation_result: ValidationRunResult | None = None
    keep = bool(keep_worktree)
    try:
        temp_workspace = _copy_workspace_for_patch_candidate(source, candidate_id)
        patch_file = temp_workspace / ".agentx_candidate.patch"
        patch_file.write_text(patch_text, encoding="utf-8")

        check_cmd = ValidationCommand(
            name="patch_apply_check",
            argv=["git", "apply", "--check", "--whitespace=nowarn", ".agentx_candidate.patch"],
            cwd=".",
            timeout_s=60,
            required=True,
        )
        check_result = _run_one(temp_workspace, check_cmd)
        if not check_result.ok:
            apply_result = check_result
            keep = keep or bool(os.environ.get("AGENTX_VALIDATION_KEEP_FAILED_PATCH_CANDIDATES"))
            duration_ms = (time.perf_counter() - perf_start) * 1000
            return _finalize_patch_candidate(PatchCandidateResult(
                ok=False,
                candidate_id=candidate_id,
                source_workspace_path=str(source),
                temp_workspace_path=str(temp_workspace) if keep else None,
                preset=preset,
                started_at=started_at,
                duration_ms=duration_ms,
                kept=keep,
                apply_result=apply_result,
                validation_result=None,
                summary={"phase": "apply_check", "passed": 0, "failed": 1},
                repair_packet=build_repair_packet(
                    candidate_id=candidate_id,
                    source_workspace=source,
                    preset=preset,
                    patch_text=patch_text,
                    apply_result=apply_result,
                    validation_result=None,
                    phase="apply_check",
                ),
            ), patch_text, repair_of_candidate_id)

        apply_cmd = ValidationCommand(
            name="patch_apply",
            argv=["git", "apply", "--whitespace=nowarn", ".agentx_candidate.patch"],
            cwd=".",
            timeout_s=60,
            required=True,
        )
        apply_result = _run_one(temp_workspace, apply_cmd)
        if not apply_result.ok:
            keep = keep or bool(os.environ.get("AGENTX_VALIDATION_KEEP_FAILED_PATCH_CANDIDATES"))
            duration_ms = (time.perf_counter() - perf_start) * 1000
            return _finalize_patch_candidate(PatchCandidateResult(
                ok=False,
                candidate_id=candidate_id,
                source_workspace_path=str(source),
                temp_workspace_path=str(temp_workspace) if keep else None,
                preset=preset,
                started_at=started_at,
                duration_ms=duration_ms,
                kept=keep,
                apply_result=apply_result,
                validation_result=None,
                summary={"phase": "apply", "passed": 0, "failed": 1},
                repair_packet=build_repair_packet(
                    candidate_id=candidate_id,
                    source_workspace=source,
                    preset=preset,
                    patch_text=patch_text,
                    apply_result=apply_result,
                    validation_result=None,
                    phase="apply",
                ),
            ), patch_text, repair_of_candidate_id)

        try:
            patch_file.unlink(missing_ok=True)
        except Exception:
            pass
        validation_result = _run_validation_workspace(temp_workspace, preset, None, run_id_prefix="candval")
        ok = bool(validation_result.ok)
        if not ok:
            keep = keep or bool(os.environ.get("AGENTX_VALIDATION_KEEP_FAILED_PATCH_CANDIDATES"))
        duration_ms = (time.perf_counter() - perf_start) * 1000
        return _finalize_patch_candidate(PatchCandidateResult(
            ok=ok,
            candidate_id=candidate_id,
            source_workspace_path=str(source),
            temp_workspace_path=str(temp_workspace) if keep else None,
            preset=preset,
            started_at=started_at,
            duration_ms=duration_ms,
            kept=keep,
            apply_result=apply_result,
            validation_result=validation_result,
            summary={
                "phase": "validation" if ok else "validation_failed",
                "validation_ok": ok,
                "validation_run_id": validation_result.run_id,
                "passed": validation_result.summary.get("passed", 0),
                "failed": validation_result.summary.get("failed", 0),
            },
            repair_packet=None if ok else build_repair_packet(
                candidate_id=candidate_id,
                source_workspace=source,
                preset=preset,
                patch_text=patch_text,
                apply_result=apply_result,
                validation_result=validation_result,
                phase="validation_failed",
            ),
        ), patch_text, repair_of_candidate_id)
    finally:
        if temp_workspace is not None and not keep:
            shutil.rmtree(temp_workspace, ignore_errors=True)


def run_validation(workspace_path: str, preset: str, commands: list[dict[str, Any]] | None = None) -> ValidationRunResult:
    workspace = resolve_workspace(workspace_path)
    return _run_validation_workspace(workspace, preset, commands)
