from __future__ import annotations

import os
import shutil
from pathlib import Path
from shlex import join as shell_join


def _normalize_path_no_symlink(path: Path) -> Path:
    expanded = path.expanduser()
    return Path(os.path.abspath(os.fspath(expanded)))


def detect_bootstrap_platform(*, proc_version: str | None = None) -> str:
    if os.name != "posix" and proc_version is None:
        return "unsupported"
    version_text = proc_version
    if version_text is None:
        try:
            version_text = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        except Exception:
            version_text = ""
    lower = version_text.lower()
    if "microsoft" in lower or "wsl" in lower:
        return "wsl"
    return "linux"


def default_bootstrap_root(*, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env_map = env or os.environ
    home_dir = (home or Path.home()).expanduser()
    xdg_data = (env_map.get("XDG_DATA_HOME") or "").strip()
    base = Path(xdg_data).expanduser() if xdg_data else (home_dir / ".local" / "share")
    return (base / "sol" / "bootstrap").resolve(strict=False)


def default_user_bin_dir(*, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env_map = env or os.environ
    home_dir = (home or Path.home()).expanduser()
    xdg_bin = (env_map.get("XDG_BIN_HOME") or "").strip()
    base = Path(xdg_bin).expanduser() if xdg_bin else (home_dir / ".local" / "bin")
    return base.resolve(strict=False)


def default_user_launcher_path(*, env: dict[str, str] | None = None, home: Path | None = None, command_name: str = "nexai") -> Path:
    return default_user_bin_dir(env=env, home=home) / command_name


def bootstrap_venv_dir(*, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    return default_bootstrap_root(env=env, home=home) / "venv"


def bootstrap_python_path(*, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    return bootstrap_venv_dir(env=env, home=home) / "bin" / "python"


def ensure_bootstrap_python(
    *,
    bootstrap_python: Path | None,
    bootstrap_root: Path | None = None,
    require_exists: bool = True,
) -> Path:
    if bootstrap_python is None:
        raise RuntimeError("Bootstrap interpreter path is required. Re-run install-sol.sh.")
    python_path = _normalize_path_no_symlink(bootstrap_python)
    if python_path.name != "python" or python_path.parent.name != "bin" or python_path.parent.parent.name != "venv":
        raise RuntimeError(
            "Invalid bootstrap interpreter: "
            f"{python_path}\nExpected bootstrap interpreter under:\n  <bootstrap_root>/venv/bin/python\nRe-run install-sol.sh"
        )
    if bootstrap_root is not None:
        expected_python = _normalize_path_no_symlink(bootstrap_root) / "venv" / "bin" / "python"
        if python_path != expected_python:
            raise RuntimeError(
                "Invalid bootstrap interpreter: "
                f"{python_path}\nExpected bootstrap interpreter under:\n  {expected_python}\nRe-run install-sol.sh"
            )
    if require_exists:
        if not python_path.exists():
            raise RuntimeError(
                "Bootstrap interpreter is missing: "
                f"{python_path}\nRe-run install-sol.sh"
            )
        if not os.access(python_path, os.X_OK):
            raise RuntimeError(
                "Bootstrap interpreter is not executable: "
                f"{python_path}\nRe-run install-sol.sh"
            )
    return python_path


def bootstrap_app_root_record_path(*, env: dict[str, str] | None = None, home: Path | None = None, bootstrap_python: Path | None = None) -> Path:
    if bootstrap_python is not None:
        python_path = ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=False)
        root = python_path.parent.parent.parent
        path = root / "app_root.txt"
    else:
        path = default_bootstrap_root(env=env, home=home) / "app_root.txt"
    if path.parent == Path(path.anchor) or str(path.parent) in {"/", "\\"}:
        raise RuntimeError(f"Invalid bootstrap metadata path computed: {path}")
    return path


def default_runtime_root(*, env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    env_map = env or os.environ
    home_dir = (home or Path.home()).expanduser()
    xdg_data = (env_map.get("XDG_DATA_HOME") or "").strip()
    base = Path(xdg_data).expanduser() if xdg_data else (home_dir / ".local" / "share")
    return (base / "sol").resolve(strict=False)


def validate_app_bundle(app_root: Path) -> list[str]:
    required = {
        "SolVersion2/pyproject.toml": app_root / "SolVersion2" / "pyproject.toml",
        "apps/api": app_root / "apps" / "api",
        "SolWeb": app_root / "SolWeb",
    }
    missing: list[str] = []
    for label, path in required.items():
        if not path.exists():
            missing.append(label)
    return missing


def bootstrap_launcher_content(*, bootstrap_python: Path, app_root: Path) -> str:
    python_path = ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=False)
    bundle_root = app_root.resolve(strict=False)
    return (
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "# Generated by install-sol.sh. Uses the bootstrap Sol CLI environment.\n"
        f'BOOTSTRAP_PY="{python_path}"\n'
        'if [ ! -x "$BOOTSTRAP_PY" ]; then\n'
        '  echo "NexAI bootstrap interpreter missing: $BOOTSTRAP_PY" >&2\n'
        '  echo "Re-run install-sol.sh" >&2\n'
        "  exit 1\n"
        "fi\n"
        f'export SOL_BOOTSTRAP_APP_ROOT="{bundle_root}"\n'
        'exec "$BOOTSTRAP_PY" -m sol "$@"\n'
    )


def launcher_validation_error(*, launcher_text: str, bootstrap_python: Path, app_root: Path) -> str | None:
    expected_python = str(ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=False))
    expected_app_root = str(app_root.resolve(strict=False))
    lines = [line.strip() for line in launcher_text.splitlines() if line.strip()]
    bootstrap_line = next((line for line in lines if line.startswith('BOOTSTRAP_PY=')), "")
    if not bootstrap_line:
        return "Launcher is missing the BOOTSTRAP_PY assignment."
    expected_bootstrap_line = f'BOOTSTRAP_PY="{expected_python}"'
    if bootstrap_line != expected_bootstrap_line:
        detected = bootstrap_line.partition("=")[2].strip().strip('"')
        return f"Launcher BOOTSTRAP_PY is incorrect. Detected: {detected}. Expected: {expected_python}."
    export_line = next((line for line in lines if line.startswith('export SOL_BOOTSTRAP_APP_ROOT=')), "")
    if export_line != f'export SOL_BOOTSTRAP_APP_ROOT="{expected_app_root}"':
        return f"Launcher is missing the persisted app bundle root: {expected_app_root}"
    exec_line = next((line for line in lines if line.startswith("exec ")), "")
    if exec_line != 'exec "$BOOTSTRAP_PY" -m sol "$@"':
        return "Launcher does not exec the bootstrap interpreter correctly."
    forbidden_bootstrap_values = {"/usr/bin/python3", "/usr/bin/python3.12", "python3"}
    detected_python = bootstrap_line.partition("=")[2].strip().strip('"')
    if detected_python in forbidden_bootstrap_values:
        return f"Launcher contains forbidden Python invocation: {detected_python}"
    forbidden_exec_patterns = {
        'exec /usr/bin/python3 -m sol "$@"',
        'exec /usr/bin/python3.12 -m sol "$@"',
        'exec python3 -m sol "$@"',
        'exec /usr/bin/env python3 -m sol "$@"',
    }
    if exec_line in forbidden_exec_patterns:
        return f"Launcher contains forbidden Python invocation: {exec_line}"
    for line in lines:
        if line.startswith("#!"):
            continue
        if "/usr/bin/env python3" in line:
            return "Launcher contains forbidden Python invocation: /usr/bin/env python3"
    return None


def write_bootstrap_app_root_record(*, record_path: Path, app_root: Path, bootstrap_python: Path) -> Path:
    verified_python = ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=True)
    expected_record_path = bootstrap_app_root_record_path(bootstrap_python=verified_python)
    if record_path.expanduser().resolve(strict=False) != expected_record_path:
        raise RuntimeError(
            "Bootstrap app-root record path is incorrect: "
            f"{record_path}\nExpected:\n  {expected_record_path}\nRe-run install-sol.sh"
        )
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(str(app_root.resolve(strict=False)) + "\n", encoding="utf-8")
    return record_path


def read_bootstrap_app_root(*, env: dict[str, str] | None = None, home: Path | None = None, bootstrap_python: Path | None = None) -> Path | None:
    raw = ((env or os.environ).get("SOL_BOOTSTRAP_APP_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    try:
        record_path = bootstrap_app_root_record_path(env=env, home=home, bootstrap_python=bootstrap_python)
    except RuntimeError:
        return None
    if not record_path.exists():
        return None
    text = record_path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    return Path(text).expanduser().resolve(strict=False)


def bootstrap_setup_command(*, bootstrap_python: Path, setup_args: list[str] | tuple[str, ...] = ()) -> list[str]:
    python_path = ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=False)
    return [str(python_path), "-m", "sol", "setup", *[str(arg) for arg in setup_args]]


def describe_command(args: list[str] | tuple[str, ...]) -> str:
    return shell_join([str(arg) for arg in args])


def launcher_targets_bootstrap_python(*, launcher_text: str, bootstrap_python: Path) -> bool:
    expected = str(ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=False))
    return f'BOOTSTRAP_PY="{expected}"' in launcher_text and 'exec "$BOOTSTRAP_PY" -m sol "$@"' in launcher_text


def write_bootstrap_launcher(*, launcher_path: Path, bootstrap_python: Path, app_root: Path) -> Path:
    ensure_bootstrap_python(bootstrap_python=bootstrap_python, require_exists=True)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    text = bootstrap_launcher_content(bootstrap_python=bootstrap_python, app_root=app_root)
    error = launcher_validation_error(launcher_text=text, bootstrap_python=bootstrap_python, app_root=app_root)
    if error:
        raise RuntimeError(error)
    launcher_path.write_text(text, encoding="utf-8")
    launcher_path.chmod(0o755)
    return launcher_path


def shadowed_sol_warning(*, launcher_path: Path, which_sol: str | None = None) -> str | None:
    current = which_sol or shutil.which("sol")
    if not current:
        return None
    resolved = Path(current).expanduser().resolve(strict=False)
    expected = launcher_path.expanduser().resolve(strict=False)
    if resolved == expected:
        return None
    return f"`sol` currently resolves to {resolved}. The intended bootstrap launcher is {expected}."
