from __future__ import annotations

from pathlib import Path

from sol.cli import main as cli_main
from sol.install.lifecycle import apply_safe_doctor_fixes, compute_install_paths
from sol.install.models import InstallProfile, ServiceMode
from sol.install.store import save_install_config
from sol.install.wizard import build_install_config


def _config(tmp_path: Path, *, service_mode: ServiceMode = ServiceMode.NONE, provider: str = "stub") -> object:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    return build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider=provider,
        ollama_base_url="http://127.0.0.1:11434",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
        service_mode=service_mode,
    )


def _doctor_report(paths, *, ok: bool, problems: list[str] | None = None, config_exists: bool | None = None) -> dict:
    return {
        "ok": ok,
        "checks": [],
        "problems": problems or [],
        "paths": {
            "app_root": str(paths.app_root),
            "runtime_root": str(paths.runtime_root),
            "working_dir": str(paths.work_dir),
            "config_path": str((paths.config_path if config_exists is None else paths.config_path)),
            "install_log_path": str(paths.install_log_path),
        },
        "managed_runtime_path": str(paths.runtime_venv_dir),
        "managed_python_path": str(paths.runtime_python_path),
        "environment": {"notes": []},
        "provider": {"provider": "stub"},
        "managed_runtime": {"required": False, "ready": True},
    }


def _ok_health() -> dict:
    return {
        "api": {"healthy": True, "message": "healthy (200 OK)"},
        "web": {"reachable": True, "message": "reachable"},
        "services": {"summary": "running (none)"},
        "model": {"provider": "stub", "connected": True, "message": "stub"},
        "overall": "OK",
    }


def test_doctor_without_fix_remains_read_only(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    monkeypatch.setattr("sol.cli._print_doctor_report", lambda result: None)
    monkeypatch.setattr(
        "sol.cli.run_doctor",
        lambda install: {
            "ok": True,
            "paths": {
                "app_root": str(config.app_root),
                "runtime_root": str(config.runtime_root),
                "working_dir": str(config.working_dir),
                "config_path": str(config.config_path),
                "install_log_path": str(config.runtime_root / "logs" / "install.log"),
            },
            "managed_runtime_path": str(config.runtime_root / "venv"),
            "managed_python_path": str(config.runtime_root / "venv" / "bin" / "python"),
            "checks": [],
            "environment": {"notes": []},
            "provider": {"provider": "stub"},
            "problems": [],
        },
    )
    monkeypatch.setattr(
        "sol.cli.apply_safe_doctor_fixes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("doctor --fix helper should not run")),
    )
    assert cli_main(["--install-config", str(install_cfg), "doctor"]) == 0


def test_doctor_fix_recreates_missing_runtime_directories(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    paths = compute_install_paths(config)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text("mode='supervised'\n", encoding="utf-8")
    paths.web_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.web_config_path.write_text("window.SOL_CONFIG = {};\n", encoding="utf-8")
    launcher_path = tmp_path / "bin" / "nexai"
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text("", encoding="utf-8")
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())
    monkeypatch.setattr(
        "sol.install.lifecycle._managed_runtime_report",
        lambda cfg, p: {"required": False, "venv_exists": True, "python_exists": True, "dependencies": []},
    )
    monkeypatch.setattr("sol.install.lifecycle.canonical_user_launcher_path", lambda: launcher_path)
    result = apply_safe_doctor_fixes(config)
    assert paths.runtime_root.exists()
    assert paths.logs_dir.exists()
    assert "Created missing runtime directories." in result["fixes_applied"]
    assert result["final_status"] == "OK"


def test_doctor_fix_regenerates_missing_runtime_and_web_config(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    paths = compute_install_paths(config)
    paths.runtime_root.mkdir(parents=True, exist_ok=True)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    called = {"ensure": 0}
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())
    monkeypatch.setattr(
        "sol.install.lifecycle._managed_runtime_report",
        lambda cfg, p: {"required": False, "venv_exists": True, "python_exists": True, "dependencies": []},
    )

    def _fake_ensure(cfg):
        called["ensure"] += 1
        paths.config_path.write_text("mode='supervised'\n", encoding="utf-8")
        paths.web_config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.web_config_path.write_text("window.SOL_CONFIG = {};\n", encoding="utf-8")
        return paths

    monkeypatch.setattr("sol.install.lifecycle.ensure_installation_ready", _fake_ensure)
    result = apply_safe_doctor_fixes(config)
    assert called["ensure"] == 1
    assert "Regenerated runtime config." in result["fixes_applied"]
    assert "Regenerated web config." in result["fixes_applied"]


def test_doctor_fix_reprovisions_missing_managed_runtime(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    paths = compute_install_paths(config)
    state = {"ready": False, "ensure": 0}
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())

    def _runtime_report(cfg, p):
        if state["ready"]:
            return {"required": True, "venv_exists": True, "python_exists": True, "dependencies": []}
        return {"required": True, "venv_exists": False, "python_exists": False, "dependencies": []}

    def _fake_ensure(cfg):
        state["ready"] = True
        state["ensure"] += 1
        return paths

    monkeypatch.setattr("sol.install.lifecycle._managed_runtime_report", _runtime_report)
    monkeypatch.setattr("sol.install.lifecycle.ensure_installation_ready", _fake_ensure)
    result = apply_safe_doctor_fixes(config)
    assert state["ensure"] == 1
    assert "Recreated managed runtime virtual environment." in result["fixes_applied"]
    assert "Repaired managed runtime interpreter." in result["fixes_applied"]


def test_doctor_fix_reinstalls_missing_dependencies(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    paths = compute_install_paths(config)
    state = {"ready": False, "ensure": 0}
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())

    def _runtime_report(cfg, p):
        if state["ready"]:
            return {"required": True, "venv_exists": True, "python_exists": True, "dependencies": []}
        return {
            "required": True,
            "venv_exists": True,
            "python_exists": True,
            "dependencies": [{"ok": False, "module": "uvicorn", "package": "uvicorn", "service": "api"}],
        }

    monkeypatch.setattr("sol.install.lifecycle._managed_runtime_report", _runtime_report)
    monkeypatch.setattr("sol.install.lifecycle.ensure_installation_ready", lambda cfg: state.update(ready=True, ensure=1) or paths)
    result = apply_safe_doctor_fixes(config)
    assert state["ensure"] == 1
    assert "Reinstalled missing managed runtime dependencies." in result["fixes_applied"]


def test_doctor_fix_reinstalls_systemd_units_and_reloads(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, service_mode=ServiceMode.SYSTEMD_USER)
    paths = compute_install_paths(config)
    service_dir = tmp_path / "units"
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())
    monkeypatch.setattr(
        "sol.install.lifecycle._managed_runtime_report",
        lambda cfg, p: {"required": False, "venv_exists": True, "python_exists": True, "dependencies": []},
    )
    monkeypatch.setattr("sol.install.lifecycle.detect_platform", lambda: type("Platform", (), {"systemd_user_available": True})())
    monkeypatch.setattr("sol.install.lifecycle._service_dir", lambda: service_dir)
    monkeypatch.setattr("sol.install.lifecycle._systemctl_user_query", lambda *args, **kwargs: type("Proc", (), {"stdout": "enabled\n", "returncode": 0})())
    called = {"install": 0}

    def _fake_install(cfg, p):
        called["install"] += 1
        service_dir.mkdir(parents=True, exist_ok=True)
        for name in ("sol-api.service", "sol-web.service"):
            (service_dir / name).write_text("", encoding="utf-8")
        return [service_dir / "sol-api.service", service_dir / "sol-web.service"]

    monkeypatch.setattr("sol.install.lifecycle.install_systemd_units", _fake_install)
    result = apply_safe_doctor_fixes(config)
    assert called["install"] == 1
    assert "Reinstalled systemd user units." in result["fixes_applied"]
    assert "Reloaded systemd user daemon." in result["fixes_applied"]


def test_doctor_fix_enables_disabled_systemd_units(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, service_mode=ServiceMode.SYSTEMD_USER)
    paths = compute_install_paths(config)
    service_dir = tmp_path / "units"
    service_dir.mkdir(parents=True, exist_ok=True)
    for name in ("sol-api.service", "sol-web.service"):
        (service_dir / name).write_text("", encoding="utf-8")
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())
    monkeypatch.setattr(
        "sol.install.lifecycle._managed_runtime_report",
        lambda cfg, p: {"required": False, "venv_exists": True, "python_exists": True, "dependencies": []},
    )
    monkeypatch.setattr("sol.install.lifecycle.detect_platform", lambda: type("Platform", (), {"systemd_user_available": True})())
    monkeypatch.setattr("sol.install.lifecycle._service_dir", lambda: service_dir)
    monkeypatch.setattr("sol.install.lifecycle._systemctl_user_query", lambda *args, **kwargs: type("Proc", (), {"stdout": "disabled\n", "returncode": 1})())
    called = {"enable": 0}
    monkeypatch.setattr("sol.install.lifecycle.install_systemd_units", lambda cfg, p: [])
    monkeypatch.setattr("sol.install.lifecycle.enable_systemd_units", lambda cfg: called.update(enable=1) or {"sol-api.service": "enabled", "sol-web.service": "enabled"})
    result = apply_safe_doctor_fixes(config)
    assert called["enable"] == 1
    assert "Enabled systemd user units." in result["fixes_applied"]


def test_doctor_fix_rewrites_missing_launcher(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    paths = compute_install_paths(config)
    launcher_path = tmp_path / "bin" / "nexai"
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: _ok_health())
    monkeypatch.setattr(
        "sol.install.lifecycle._managed_runtime_report",
        lambda cfg, p: {"required": False, "venv_exists": True, "python_exists": True, "dependencies": []},
    )
    monkeypatch.setattr("sol.install.lifecycle.canonical_user_launcher_path", lambda: launcher_path)
    monkeypatch.setattr(
        "sol.install.lifecycle.write_bootstrap_launcher",
        lambda launcher_path, bootstrap_python, app_root: launcher_path.parent.mkdir(parents=True, exist_ok=True) or launcher_path.write_text("#!/usr/bin/env sh\n", encoding="utf-8") or launcher_path,
    )
    result = apply_safe_doctor_fixes(config)
    assert launcher_path.exists()
    assert "Rewrote NexAI launcher." in result["fixes_applied"]


def test_doctor_fix_reports_remaining_ollama_problem_honestly(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="ollama")
    paths = compute_install_paths(config)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_path.write_text("mode='supervised'\n", encoding="utf-8")
    paths.web_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.web_config_path.write_text("window.SOL_CONFIG = {};\n", encoding="utf-8")
    launcher_path = tmp_path / "bin" / "nexai"
    reports = iter([_doctor_report(paths, ok=False), _doctor_report(paths, ok=True)])
    health_reports = iter(
        [
            {
                "api": {"healthy": True, "message": "healthy (200 OK)"},
                "web": {"reachable": True, "message": "reachable"},
                "services": {"summary": "running (none)"},
                "model": {"provider": "ollama", "connected": False, "message": "ollama (disconnected)"},
                "overall": "DEGRADED",
            },
            {
                "api": {"healthy": True, "message": "healthy (200 OK)"},
                "web": {"reachable": True, "message": "reachable"},
                "services": {"summary": "running (none)"},
                "model": {"provider": "ollama", "connected": False, "message": "ollama (disconnected)"},
                "overall": "DEGRADED",
            },
        ]
    )
    monkeypatch.setattr("sol.install.lifecycle.run_doctor", lambda cfg: next(reports))
    monkeypatch.setattr("sol.install.lifecycle.collect_health_report", lambda cfg: next(health_reports))
    monkeypatch.setattr(
        "sol.install.lifecycle._managed_runtime_report",
        lambda cfg, p: {"required": False, "venv_exists": True, "python_exists": True, "dependencies": []},
    )
    monkeypatch.setattr("sol.install.lifecycle.canonical_user_launcher_path", lambda: launcher_path)
    monkeypatch.setattr(
        "sol.install.lifecycle.write_bootstrap_launcher",
        lambda launcher_path, bootstrap_python, app_root: launcher_path.parent.mkdir(parents=True, exist_ok=True) or launcher_path.write_text("", encoding="utf-8") or launcher_path,
    )
    result = apply_safe_doctor_fixes(config)
    assert result["final_status"] == "DEGRADED"
    assert "Ollama endpoint is unreachable." in result["remaining_problems"]


def test_doctor_fix_cli_renders_sections_and_return_code(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    monkeypatch.setattr(
        "sol.cli.apply_safe_doctor_fixes",
        lambda install, install_config_path=None: {
            "findings": ["Managed runtime virtual environment is missing"],
            "fixes_applied": ["Recreated managed runtime virtual environment."],
            "fix_failures": [],
            "remaining_problems": ["Ollama endpoint is unreachable."],
            "final_status": "DEGRADED",
        },
    )
    code = cli_main(["--install-config", str(install_cfg), "doctor", "--fix"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Doctor Findings" in captured.out
    assert "Applied Fixes" in captured.out
    assert "Remaining Problems" in captured.out
    assert "Final Status" in captured.out
