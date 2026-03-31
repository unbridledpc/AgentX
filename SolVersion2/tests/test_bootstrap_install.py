from __future__ import annotations

from pathlib import Path

from sol.cli import main as cli_main
from sol.install.bootstrap import (
    bootstrap_app_root_record_path,
    bootstrap_setup_command,
    bootstrap_launcher_content,
    default_user_launcher_path,
    describe_command,
    default_bootstrap_root,
    default_runtime_root,
    default_user_bin_dir,
    detect_bootstrap_platform,
    ensure_bootstrap_python,
    launcher_validation_error,
    launcher_targets_bootstrap_python,
    read_bootstrap_app_root,
    shadowed_sol_warning,
    validate_app_bundle,
    write_bootstrap_app_root_record,
    write_bootstrap_launcher,
)
from sol.install.models import InstallProfile, ServiceMode


def _make_bootstrap_python(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_default_bootstrap_paths_follow_xdg(tmp_path: Path) -> None:
    env = {"XDG_DATA_HOME": str(tmp_path / "xdg-data"), "XDG_BIN_HOME": str(tmp_path / "xdg-bin")}
    assert default_bootstrap_root(env=env, home=tmp_path) == (tmp_path / "xdg-data" / "sol" / "bootstrap").resolve()
    assert default_runtime_root(env=env, home=tmp_path) == (tmp_path / "xdg-data" / "sol").resolve()
    assert default_user_bin_dir(env=env, home=tmp_path) == (tmp_path / "xdg-bin").resolve()
    assert default_user_launcher_path(env=env, home=tmp_path) == (tmp_path / "xdg-bin" / "nexai").resolve()


def test_detect_bootstrap_platform_distinguishes_linux_and_wsl() -> None:
    assert detect_bootstrap_platform(proc_version="Linux version 6.6.0") == "linux"
    assert detect_bootstrap_platform(proc_version="Linux version 6.6.0-microsoft-standard-WSL2") == "wsl"


def test_validate_app_bundle_reports_missing_components(tmp_path: Path) -> None:
    app_root = tmp_path / "bundle"
    (app_root / "SolVersion2").mkdir(parents=True)
    (app_root / "SolVersion2" / "sol").mkdir()
    missing = validate_app_bundle(app_root)
    assert "SolVersion2/pyproject.toml" in missing
    assert "apps/api" in missing
    assert "SolWeb" in missing


def test_bootstrap_launcher_content_exports_bundle_root(tmp_path: Path) -> None:
    launcher = bootstrap_launcher_content(
        bootstrap_python=tmp_path / "bootstrap" / "venv" / "bin" / "python",
        app_root=tmp_path / "bundle",
    )
    assert launcher.startswith("#!/usr/bin/env sh\nset -eu\n")
    assert 'BOOTSTRAP_PY="' in launcher
    assert 'if [ ! -x "$BOOTSTRAP_PY" ]; then' in launcher
    assert 'Re-run install-sol.sh' in launcher
    assert 'SOL_BOOTSTRAP_APP_ROOT="' in launcher
    assert 'exec "$BOOTSTRAP_PY" -m sol "$@"' in launcher
    assert "/usr/bin/python" not in launcher


def test_bootstrap_app_root_record_round_trip(tmp_path: Path) -> None:
    bootstrap_python = _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    record_path = bootstrap_app_root_record_path(bootstrap_python=bootstrap_python)
    written = write_bootstrap_app_root_record(record_path=record_path, app_root=tmp_path / "bundle", bootstrap_python=bootstrap_python)
    assert written == record_path
    assert read_bootstrap_app_root(bootstrap_python=bootstrap_python) == (tmp_path / "bundle").resolve(strict=False)
    assert record_path == (tmp_path / "bootstrap" / "app_root.txt").resolve(strict=False)


def test_bootstrap_app_root_record_path_rejects_filesystem_root() -> None:
    try:
        bootstrap_app_root_record_path(bootstrap_python=Path("/python"))
    except RuntimeError as exc:
        assert "Invalid bootstrap interpreter" in str(exc)
    else:
        raise AssertionError("Expected invalid root-level metadata path to be rejected")


def test_launcher_targets_bootstrap_python_and_handles_spaces(tmp_path: Path) -> None:
    bootstrap_python = _make_bootstrap_python(tmp_path / "bootstrap space" / "venv" / "bin" / "python")
    app_root = tmp_path / "bundle space"
    launcher_text = bootstrap_launcher_content(
        bootstrap_python=bootstrap_python,
        app_root=app_root,
    )
    assert launcher_targets_bootstrap_python(launcher_text=launcher_text, bootstrap_python=bootstrap_python) is True
    assert f'export SOL_BOOTSTRAP_APP_ROOT="{app_root.resolve(strict=False)}"' in launcher_text
    assert f'BOOTSTRAP_PY="{bootstrap_python.resolve(strict=False)}"' in launcher_text
    assert 'exec "$BOOTSTRAP_PY" -m sol "$@"' in launcher_text


def test_write_bootstrap_launcher_writes_bootstrap_python_not_system_python(tmp_path: Path) -> None:
    launcher_path = tmp_path / ".local" / "bin" / "sol"
    bootstrap_python = _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    written = write_bootstrap_launcher(
        launcher_path=launcher_path,
        bootstrap_python=bootstrap_python,
        app_root=tmp_path / "bundle",
    )
    text = written.read_text(encoding="utf-8")
    assert written == launcher_path
    assert launcher_targets_bootstrap_python(launcher_text=text, bootstrap_python=bootstrap_python) is True
    assert "/usr/bin/python3" not in text
    assert 'exec "$BOOTSTRAP_PY" -m sol "$@"' in text


def test_write_bootstrap_launcher_supports_nexai_and_sol_aliases(tmp_path: Path) -> None:
    bootstrap_python = _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    app_root = tmp_path / "bundle"
    nexai = write_bootstrap_launcher(
        launcher_path=tmp_path / ".local" / "bin" / "nexai",
        bootstrap_python=bootstrap_python,
        app_root=app_root,
    )
    sol = write_bootstrap_launcher(
        launcher_path=tmp_path / ".local" / "bin" / "sol",
        bootstrap_python=bootstrap_python,
        app_root=app_root,
    )
    assert nexai.name == "nexai"
    assert sol.name == "sol"
    assert launcher_targets_bootstrap_python(launcher_text=nexai.read_text(encoding="utf-8"), bootstrap_python=bootstrap_python)
    assert launcher_targets_bootstrap_python(launcher_text=sol.read_text(encoding="utf-8"), bootstrap_python=bootstrap_python)


def test_launcher_validation_rejects_system_python_launcher(tmp_path: Path) -> None:
    launcher_text = (
        '#!/usr/bin/env sh\n'
        'set -eu\n'
        'BOOTSTRAP_PY="/usr/bin/python3.12"\n'
        'export SOL_BOOTSTRAP_APP_ROOT="/bundle"\n'
        'exec "$BOOTSTRAP_PY" -m sol "$@"\n'
    )
    error = launcher_validation_error(
        launcher_text=launcher_text,
        bootstrap_python=tmp_path / "bootstrap" / "venv" / "bin" / "python",
        app_root=Path("/bundle"),
    )
    assert error is not None
    assert "BOOTSTRAP_PY is incorrect" in error or "forbidden Python invocation" in error


def test_launcher_validation_accepts_valid_shell_shebang(tmp_path: Path) -> None:
    bootstrap_python = _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    app_root = tmp_path / "bundle"
    launcher_text = bootstrap_launcher_content(bootstrap_python=bootstrap_python, app_root=app_root)
    error = launcher_validation_error(
        launcher_text=launcher_text,
        bootstrap_python=bootstrap_python,
        app_root=app_root,
    )
    assert error is None


def test_launcher_validation_rejects_exec_python3_pattern(tmp_path: Path) -> None:
    bootstrap_python = _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    app_root = tmp_path / "bundle"
    launcher_text = (
        '#!/usr/bin/env sh\n'
        'set -eu\n'
        f'BOOTSTRAP_PY="{bootstrap_python.resolve(strict=False)}"\n'
        f'export SOL_BOOTSTRAP_APP_ROOT="{app_root.resolve(strict=False)}"\n'
        'exec python3 -m sol "$@"\n'
    )
    error = launcher_validation_error(
        launcher_text=launcher_text,
        bootstrap_python=bootstrap_python,
        app_root=app_root,
    )
    assert error is not None
    assert "forbidden Python invocation" in error or "does not exec the bootstrap interpreter correctly" in error


def test_shadowed_sol_warning_reports_mismatch(tmp_path: Path) -> None:
    warning = shadowed_sol_warning(
        launcher_path=tmp_path / ".local" / "bin" / "sol",
        which_sol=str(tmp_path / "other" / "sol"),
    )
    assert warning is not None
    assert "intended bootstrap launcher" in warning


def test_bootstrap_setup_command_uses_bootstrap_python_not_path_sol(tmp_path: Path) -> None:
    _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    cmd = bootstrap_setup_command(
        bootstrap_python=tmp_path / "bootstrap" / "venv" / "bin" / "python",
        setup_args=["--profile", "standard"],
    )
    assert cmd[:4] == [str((tmp_path / "bootstrap" / "venv" / "bin" / "python").resolve()), "-m", "sol", "setup"]
    assert "--profile" in cmd
    assert "standard" in cmd


def test_describe_command_renders_exact_setup_invocation(tmp_path: Path) -> None:
    _make_bootstrap_python(tmp_path / "bootstrap" / "venv" / "bin" / "python")
    cmd = bootstrap_setup_command(
        bootstrap_python=tmp_path / "bootstrap" / "venv" / "bin" / "python",
        setup_args=["--profile", "server"],
    )
    rendered = describe_command(cmd)
    assert "-m sol setup" in rendered
    assert str((tmp_path / "bootstrap" / "venv" / "bin" / "python").resolve()) in rendered
    assert "server" in rendered


def test_ensure_bootstrap_python_rejects_system_python_input() -> None:
    try:
        ensure_bootstrap_python(bootstrap_python=Path("/usr/bin/python3.12"), require_exists=False)
    except RuntimeError as exc:
        assert "Invalid bootstrap interpreter" in str(exc)
    else:
        raise AssertionError("Expected system python to be rejected")


def test_write_bootstrap_launcher_rejects_system_python_input(tmp_path: Path) -> None:
    try:
        write_bootstrap_launcher(
            launcher_path=tmp_path / ".local" / "bin" / "nexai",
            bootstrap_python=Path("/usr/bin/python3.12"),
            app_root=tmp_path / "bundle",
        )
    except RuntimeError as exc:
        assert "Invalid bootstrap interpreter" in str(exc)
    else:
        raise AssertionError("Expected system python launcher generation to fail")


def test_write_bootstrap_app_root_record_rejects_system_python_input(tmp_path: Path) -> None:
    record_path = tmp_path / "bootstrap" / "app_root.txt"
    try:
        write_bootstrap_app_root_record(
            record_path=record_path,
            app_root=tmp_path / "bundle",
            bootstrap_python=Path("/usr/bin/python3.12"),
        )
    except RuntimeError as exc:
        assert "Invalid bootstrap interpreter" in str(exc)
    else:
        raise AssertionError("Expected system python metadata write to fail")


def test_install_script_uses_bootstrap_python_for_post_install_helpers() -> None:
    script = Path(r"F:\Sol Folder\install-sol.sh").read_text(encoding="utf-8")
    assert '"$BOOTSTRAP_PYTHON" - <<PY' in script
    assert '"$BOOTSTRAP_PYTHON" -m pip install --upgrade pip setuptools wheel' in script
    assert '"$BOOTSTRAP_PYTHON" -m pip install --upgrade "${APP_ROOT}/SolVersion2[cli]"' in script
    assert "python3 -m sol" not in script


def test_install_script_has_no_bare_python_calls_after_bootstrap_python_is_defined() -> None:
    script = Path(r"F:\Sol Folder\install-sol.sh").read_text(encoding="utf-8")
    _, _, post_bootstrap = script.partition('BOOTSTRAP_PYTHON="${BOOTSTRAP_VENV}/bin/python"')
    assert post_bootstrap
    assert 'python - <<' not in post_bootstrap
    assert 'python3 - <<' not in post_bootstrap
    assert 'python -m ' not in post_bootstrap
    bare_python3_m_lines = [line.strip() for line in post_bootstrap.splitlines() if 'python3 -m ' in line]
    assert bare_python3_m_lines == ['python3 -m venv "$BOOTSTRAP_VENV" >>"$INSTALL_LOG" 2>&1 || {']


def test_setup_uses_bootstrap_app_root_env(tmp_path: Path, monkeypatch, capsys) -> None:
    app_root = tmp_path / "bundle"
    (app_root / "SolVersion2").mkdir(parents=True)
    (app_root / "SolVersion2" / "sol").mkdir()
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "plugins").mkdir()
    (app_root / "SolVersion2" / "skills").mkdir()
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")

    install_cfg = tmp_path / "install.json"
    runtime_root = tmp_path / "runtime"
    work_root = tmp_path / "work"
    monkeypatch.setenv("SOL_BOOTSTRAP_APP_ROOT", str(app_root))

    class _Paths:
        runtime_venv_dir = runtime_root / "venv"
        config_path = runtime_root / "config" / "sol.toml"

    captured = {}
    ui_calls = {"summary": None, "next_steps": None}

    def _fake_ensure(config):
        captured["app_root"] = config.app_root
        _Paths.runtime_venv_dir.mkdir(parents=True, exist_ok=True)
        _Paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        _Paths.config_path.write_text("", encoding="utf-8")
        return _Paths

    monkeypatch.setattr("sol.cli.ensure_installation_ready", _fake_ensure)
    monkeypatch.setattr(
        "sol.cli.inspect_runtime",
        lambda config: {"ready": True, "install_log_path": str(runtime_root / "logs" / "install.log")},
    )
    monkeypatch.setattr("sol.cli.write_installation", lambda config, path: path)
    monkeypatch.setattr("sol.cli.write_cli_launcher", lambda config, paths, install_cfg_path: runtime_root / "bin" / "sol")
    monkeypatch.setattr("sol.cli.save_local_profile", lambda runtime_root_arg, local_profile: runtime_root_arg / "config" / "profile.json")
    expected_launcher = Path("/home/test/.local/bin/nexai")
    expected_compat = Path("/home/test/.local/bin/sol")
    monkeypatch.setattr("sol.cli.canonical_user_launcher_path", lambda: expected_launcher)
    monkeypatch.setattr("sol.cli.compatibility_user_launcher_path", lambda: expected_compat)
    monkeypatch.setattr("sol.cli.canonical_bootstrap_fallback", lambda: "/home/test/.local/share/sol/bootstrap/venv/bin/python -m sol")
    monkeypatch.setattr("sol.cli.summary_panel", lambda title, items, style="#5B8CFF": ui_calls.__setitem__("summary", (title, list(items), style)))
    monkeypatch.setattr("sol.cli.next_steps_panel", lambda title, steps, notes=None: ui_calls.__setitem__("next_steps", (title, list(steps), list(notes or []))))

    code = cli_main(
        [
            "--install-config",
            str(install_cfg),
            "setup",
            "--non-interactive",
            "--runtime-root",
            str(runtime_root),
            "--working-dir",
            str(work_root),
            "--profile",
            InstallProfile.CLI.value,
            "--model-provider",
            "stub",
            "--service-mode",
            ServiceMode.NONE.value,
        ]
    )
    capsys.readouterr()
    assert code == 0
    assert captured["app_root"] == app_root.resolve()
    assert ui_calls["summary"] is not None
    assert ui_calls["next_steps"] is not None
    assert any(str(expected_launcher) in line for line in ui_calls["next_steps"][2])
    assert any(str(expected_compat) in line for line in ui_calls["next_steps"][2])
    assert all(str(runtime_root / "bin" / "sol") not in line for line in ui_calls["next_steps"][2])
