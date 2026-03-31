from __future__ import annotations

import json
import tomllib
from pathlib import Path

from sol.cli import main as cli_main
from sol.config import load_config
from sol.install.deps import install_target_for_config, profile_extra_name, required_dependency_packages
from sol.install.local_profile import LocalProfileSelection, resolve_local_profile, save_local_profile
from sol.install.ollama import DEFAULT_OLLAMA_BASE_URL, build_ollama_base_url, detect_wsl_nameserver_ip, wsl_ollama_guidance
from sol.install.lifecycle import ensure_installation_ready, inspect_runtime, run_doctor, show_paths, start_installation, status_installation, stop_installation, uninstall_installation
from sol.install.models import InstallProfile, ServiceMode
from sol.install.store import load_install_config, save_install_config
from sol.runtime.bootstrap import build_runtime_services_from_config
from sol.install.wizard import (
    PromptSpec,
    _normalize_setup_path_input,
    _prompt_ollama_endpoint,
    _run_preflight,
    app_root_sanity_error,
    build_install_config,
    fatal_bundle_validation_errors,
    profile_defaults,
    profile_description,
    prompt_install_config,
    render_profile_summary,
    render_setup_summary,
    validate_install_config,
)


def _stub_managed_runtime(monkeypatch) -> None:
    def _fake_ensure_runtime_python_environment(config, paths):
        paths.runtime_venv_dir.mkdir(parents=True, exist_ok=True)
        paths.runtime_python_path.parent.mkdir(parents=True, exist_ok=True)
        paths.runtime_python_path.write_text("", encoding="utf-8")
        paths.install_log_path.parent.mkdir(parents=True, exist_ok=True)
        paths.install_log_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("sol.install.lifecycle._ensure_runtime_python_environment", _fake_ensure_runtime_python_environment)
    monkeypatch.setattr("sol.install.lifecycle.dependency_report", lambda config, python_executable=None: [])


def test_profile_defaults() -> None:
    assert profile_defaults(InstallProfile.CLI) == (False, False)
    assert profile_defaults(InstallProfile.STANDARD) == (True, True)
    assert profile_defaults(InstallProfile.SERVER) == (True, False)
    assert profile_defaults(InstallProfile.DEVELOPER) == (True, True)
    assert profile_description(InstallProfile.CLI) == "Run NexAI from the terminal only (no web UI)."
    assert profile_description(InstallProfile.STANDARD) == "Recommended: NexAI CLI + API + Web UI."


def test_install_config_round_trip(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="ollama",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
        service_mode=ServiceMode.NONE,
    )
    install_path = tmp_path / "install.json"
    save_install_config(cfg, install_path)
    loaded = load_install_config(install_path)
    assert loaded.profile == InstallProfile.STANDARD
    assert loaded.runtime_root == (tmp_path / "runtime").resolve()
    assert loaded.config_path == (tmp_path / "runtime" / "config" / "sol.toml").resolve()
    assert loaded.ollama_base_url == DEFAULT_OLLAMA_BASE_URL


def test_runtime_layout_and_generated_config(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.DEVELOPER,
        model_provider="openai",
        api_host="0.0.0.0",
        api_port=9000,
        web_host="127.0.0.1",
        web_port=8080,
    )
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    text = paths.config_path.read_text(encoding="utf-8")
    assert 'provider = "openai"' in text
    assert 'working_dir = "' in text
    assert paths.web_config_path.exists()
    assert json.loads(paths.web_config_path.read_text(encoding="utf-8").split("=", 1)[1].rstrip(";\n"))["apiBaseUrl"] == "http://0.0.0.0:9000"
    cfg_loaded = load_config(str(paths.config_path))
    assert cfg_loaded.paths.runtime_root == (tmp_path / "runtime").resolve()
    assert cfg_loaded.paths.web_dist_dir == (app_root / "SolWeb" / "dist").resolve()
    assert cfg_loaded.paths.user_plugins_dir == (tmp_path / "runtime" / "extensions" / "plugins").resolve()
    shown = show_paths(cfg)
    assert shown["runtime_root"] == str((tmp_path / "runtime").resolve())


def test_install_config_round_trip_custom_ollama_url(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="ollama",
        ollama_base_url="http://10.0.0.25:11434/",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    install_path = tmp_path / "install.json"
    save_install_config(cfg, install_path)
    loaded = load_install_config(install_path)
    assert loaded.ollama_base_url == "http://10.0.0.25:11434"
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    text = paths.config_path.read_text(encoding="utf-8")
    assert 'base_url = "http://10.0.0.25:11434"' in text


def test_explicit_local_profile_round_trip(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    save_local_profile(
        runtime_root,
        LocalProfileSelection(mode="explicit", display_name="Jane Local", profile_id="jane-dev"),
    )
    profile = resolve_local_profile(runtime_root)
    assert profile.mode == "explicit"
    assert profile.display_name == "Jane Local"
    assert profile.profile_id == "jane-dev"
    assert profile.memory_namespace == "user.jane-dev"


def test_skipped_profile_uses_os_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SOL_PROFILE_OS_USER", "soltester")
    runtime_root = tmp_path / "runtime"
    save_local_profile(runtime_root, LocalProfileSelection(mode="os-fallback"))
    profile = resolve_local_profile(runtime_root)
    assert profile.mode == "os-fallback"
    assert profile.display_name == "Soltester"
    assert profile.profile_id == "soltester"


def test_os_fallback_resolution_without_profile_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SOL_PROFILE_OS_USER", "fallback-user")
    profile = resolve_local_profile(tmp_path / "runtime")
    assert profile.mode == "os-fallback"
    assert profile.profile_id == "fallback-user"
    assert profile.memory_namespace == "user.fallback-user"


def test_doctor_flags_missing_web_dist(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="ollama",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    ensure_installation_ready(cfg)
    report = run_doctor(cfg)
    assert report["ok"] is False
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["web_dist"]["ok"] is False
    assert report["paths"]["runtime_root"] == str((tmp_path / "runtime").resolve())
    assert "builtin_plugins_dir" in report["extensions"]


def test_validate_install_config_flags_missing_web_dist(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="openai",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    validation = validate_install_config(cfg)
    assert validation.ok is False
    assert any("built frontend assets are missing" in item for item in validation.errors)


def test_prompt_install_config_collects_custom_ollama_endpoint(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    responses = iter(
        [
            "standard",
            str(tmp_path / "runtime"),
            str(tmp_path / "work"),
            "skip",
            "ollama",
            "10.0.0.8",
            "",
            "127.0.0.1",
            "8420",
            "yes",
            "127.0.0.1",
            "5173",
            "none",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    monkeypatch.setattr(
        "sol.install.wizard.probe_ollama_endpoint",
        lambda base_url: type("Probe", (), {"status": "reachable", "message": "Reachable", "base_url": base_url, "models": ("llama3.2",)})(),
    )
    cfg, _, selection = prompt_install_config(app_root=app_root)
    assert selection is not None
    assert cfg.model_provider == "ollama"
    assert cfg.ollama_base_url == "http://10.0.0.8:11434"


def test_build_ollama_base_url_from_host_and_default_port() -> None:
    assert build_ollama_base_url(host_or_url="127.0.0.1", port="11434") == "http://127.0.0.1:11434"
    assert build_ollama_base_url(host_or_url="localhost", port="11434") == "http://localhost:11434"


def test_build_ollama_base_url_from_host_and_custom_port() -> None:
    assert build_ollama_base_url(host_or_url="192.168.68.50", port="12456") == "http://192.168.68.50:12456"


def test_build_ollama_base_url_accepts_full_url() -> None:
    assert build_ollama_base_url(host_or_url="http://192.168.68.50:11434") == "http://192.168.68.50:11434"
    assert build_ollama_base_url(host_or_url="https://example.local:11434") == "https://example.local:11434"


def test_prompt_ollama_endpoint_reprompts_on_invalid_input(monkeypatch, capsys) -> None:
    responses = iter(
        [
            "bad host name",
            "11434",
            "http://10.0.0.8:11434",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    platform_info = type("Platform", (), {"is_wsl": False})()
    base_url = _prompt_ollama_endpoint(platform_info=platform_info)
    captured = capsys.readouterr()
    assert "Invalid Ollama endpoint:" in captured.err
    assert base_url == "http://10.0.0.8:11434"


def test_normalize_setup_path_rejects_backslash_on_linux() -> None:
    platform_info = type("Platform", (), {"is_linux": True, "is_wsl": True})()
    try:
        _normalize_setup_path_input(
            "\\",
            default_value="/home/test/.local/share/sol",
            platform_info=platform_info,
            label="Runtime data directory",
        )
    except ValueError as exc:
        assert "Backslashes are not valid here" in str(exc)
    else:
        raise AssertionError("Expected invalid Linux path to be rejected")


def test_normalize_setup_path_blank_uses_default() -> None:
    platform_info = type("Platform", (), {"is_linux": True, "is_wsl": False})()
    path = _normalize_setup_path_input(
        "",
        default_value="/home/test/.local/share/sol",
        platform_info=platform_info,
        label="Runtime data directory",
    )
    assert path == Path("/home/test/.local/share/sol").resolve(strict=False)


def test_app_root_sanity_rejects_venv_python_location() -> None:
    error = app_root_sanity_error(Path("/home/nexus/.local/share/sol/bootstrap/venv/lib/python3.12"))
    assert error is not None
    assert "Invalid NexAI app bundle root detected" in error


def test_fatal_bundle_validation_errors_include_bundle_breakage() -> None:
    errors = (
        "App root does not look like a NexAI bundle: /bad/path",
        "Web UI is enabled but built frontend assets are missing: /bad/path/SolWeb/dist/index.html",
    )
    fatal = fatal_bundle_validation_errors(errors)
    assert len(fatal) == 2


def test_validate_install_config_warns_for_wsl_mnt_paths(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(
        "sol.install.wizard.detect_platform",
        lambda: type("Platform", (), {"is_wsl": True, "is_linux": True, "systemd_user_available": False})(),
    )
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=Path("/mnt/e/sol-runtime"),
        working_dir=Path("/mnt/e/sol-work"),
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    validation = validate_install_config(cfg)
    assert any("Runtime root is under /mnt/*" in item for item in validation.warnings)
    assert any("Working directory is under /mnt/*" in item for item in validation.warnings)


def test_prompt_install_config_reprompts_on_invalid_runtime_path(tmp_path: Path, monkeypatch, capsys) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    runtime_root = "/home/test/.local/share/sol"
    work_root = "/home/test/sol-work"
    responses = iter(
        [
            "standard",
            "\\",
            runtime_root,
            work_root,
            "skip",
            "stub",
            "127.0.0.1",
            "8420",
            "yes",
            "127.0.0.1",
            "5173",
            "none",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    monkeypatch.setattr(
        "sol.install.wizard.detect_platform",
        lambda: type("Platform", (), {"is_wsl": True, "is_linux": True, "systemd_user_available": False})(),
    )
    cfg, _, _ = prompt_install_config(app_root=app_root)
    captured = capsys.readouterr()
    assert "Invalid path:" in captured.err
    assert cfg.runtime_root == Path(runtime_root).resolve(strict=False)
    assert cfg.working_dir == Path(work_root).resolve(strict=False)


def test_prompt_install_config_blank_runtime_path_uses_default(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    default_runtime_root = "/home/test/.local/share/sol"
    work_root = "/home/test/sol-work"
    responses = iter(
        [
            "standard",
            "",
            work_root,
            "skip",
            "stub",
            "127.0.0.1",
            "8420",
            "yes",
            "127.0.0.1",
            "5173",
            "none",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))
    monkeypatch.setattr(
        "sol.install.wizard.detect_platform",
        lambda: type("Platform", (), {"is_wsl": False, "is_linux": True, "systemd_user_available": False})(),
    )
    monkeypatch.setattr(
        "sol.install.wizard._runtime_prompt",
        lambda: PromptSpec(
            title="Runtime Data Directory",
            prompt="Where should Sol store its runtime data",
            default=default_runtime_root,
            help_text="runtime help",
        ),
    )
    cfg, _, _ = prompt_install_config(app_root=app_root)
    assert cfg.runtime_root == Path(default_runtime_root).resolve(strict=False)


def test_prompt_install_config_aborts_on_invalid_app_root(capsys) -> None:
    try:
        prompt_install_config(app_root=Path("/home/nexus/.local/share/sol/bootstrap/venv/lib/python3.12"))
    except RuntimeError as exc:
        assert "Invalid NexAI bundle root" in str(exc)
    else:
        raise AssertionError("Expected invalid app root to abort setup")
    captured = capsys.readouterr()
    assert "Invalid App Bundle" in captured.out


def test_ask_renders_prompt_once_in_input_line(capsys, monkeypatch) -> None:
    from sol.install.wizard import _ask

    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    spec = PromptSpec(
        title="API Bind Address",
        prompt="Which address should the NexAI API listen on",
        default="127.0.0.1",
        help_text="help",
    )
    value = _ask(spec, index=1, total=10)
    captured = capsys.readouterr()
    assert value == "127.0.0.1"
    assert captured.out.count("Which address should the NexAI API listen on") == 0


def test_wsl_ollama_guidance_includes_nameserver(monkeypatch, tmp_path: Path) -> None:
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 172.28.48.1\n", encoding="utf-8")
    assert detect_wsl_nameserver_ip(resolv) == "172.28.48.1"
    platform_info = type("Platform", (), {"is_wsl": True})()
    monkeypatch.setattr("sol.install.ollama.detect_wsl_nameserver_ip", lambda resolv_conf=Path("/etc/resolv.conf"): "172.28.48.1")
    notes = wsl_ollama_guidance(platform_info=platform_info, base_url="http://127.0.0.1:11434")
    assert any("172.28.48.1:11434" in item for item in notes)


def test_validate_install_config_does_not_require_api_deps_in_bootstrap_python(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )

    validation = validate_install_config(cfg)
    assert validation.ok is True


def test_render_setup_summary_includes_next_steps(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="ollama",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    summary = render_setup_summary(
        cfg,
        setup_complete=True,
        managed_runtime_path=str(tmp_path / "runtime" / "venv"),
        provisioning_ok=True,
        launcher_path="/home/test/.local/bin/nexai",
    )
    assert "NexAI is ready." in summary
    assert "Runtime data:" in summary
    assert "Managed runtime:" in summary
    assert "Provisioning: succeeded" in summary
    assert "Start NexAI:" in summary
    assert "/home/test/.local/bin/nexai" in summary
    assert "Open the web UI: http://127.0.0.1:5173" in summary


def test_render_profile_summary_uses_resolved_identity() -> None:
    summary = render_profile_summary(LocalProfileSelection(mode="explicit", display_name="Local Jane", profile_id="jane-lab"))
    assert "Display name: Local Jane" in summary
    assert "Profile ID: jane-lab" in summary
    assert "Memory namespace: user.jane-lab" in summary


def test_doctor_reports_missing_dependencies(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    ensure_installation_ready(cfg)
    monkeypatch.setattr(
        "sol.install.lifecycle.dependency_report",
        lambda config, python_executable=None: [
            {"module": "uvicorn", "package": "uvicorn[standard]>=0.27", "service": "api", "ok": False, "missing_module": "uvicorn", "error": "No module named 'uvicorn'"}
        ],
    )
    monkeypatch.setattr(
        "sol.install.lifecycle.missing_dependency_messages",
        lambda config, python_executable=None: ["Missing dependency for api: module `uvicorn` is not importable. Install `uvicorn[standard]>=0.27`."],
    )
    report = run_doctor(cfg)
    assert report["ok"] is False
    assert any(item["name"] == "dependency:uvicorn" and item["ok"] is False for item in report["checks"])
    assert any("uvicorn" in item for item in report["problems"])


def test_doctor_reports_local_profile(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    ensure_installation_ready(cfg)
    save_local_profile(cfg.runtime_root, LocalProfileSelection(mode="explicit", display_name="Ops User", profile_id="ops-user"))
    monkeypatch.setattr("sol.install.lifecycle.dependency_report", lambda config, python_executable=None: [])
    monkeypatch.setattr("sol.install.lifecycle.missing_dependency_messages", lambda config, python_executable=None: [])
    report = run_doctor(cfg)
    assert report["local_profile"]["display_name"] == "Ops User"
    assert report["local_profile"]["profile_id"] == "ops-user"
    assert report["paths"]["profile_path"].endswith("profile.json")


def test_runtime_bootstrap_uses_resolved_local_profile(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    save_local_profile(cfg.runtime_root, LocalProfileSelection(mode="explicit", display_name="Ops User", profile_id="ops-user"))
    services = build_runtime_services_from_config(config_path=str(paths.config_path), confirm=lambda prompt: False)
    assert services.ctx.web_session_user == "ops-user"
    assert services.ctx.default_memory_namespace == "user.ops-user"


def test_start_prevents_double_start_and_cleans_stale_pid(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    paths.api_pid_path.write_text("999999", encoding="utf-8")
    paths.web_pid_path.write_text("123456", encoding="utf-8")

    monkeypatch.setattr("sol.install.lifecycle.dependency_report", lambda config, python_executable=None: [])
    monkeypatch.setattr("sol.install.lifecycle._process_running", lambda pid: pid in {4242, 4343})
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: False)
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True)
    next_pid = iter([4242, 4343])

    def _fake_spawn(args, env, pid_path, cwd, log_path, service):
        pid = next(next_pid)
        pid_path.write_text(str(pid), encoding="utf-8")
        return pid

    monkeypatch.setattr("sol.install.lifecycle._spawn_process", _fake_spawn)

    first = start_installation(cfg, install_config_path=tmp_path / "install.json")
    assert first["services"]["api"]["state"] == "started"
    assert first["services"]["web"]["state"] == "started"
    second = start_installation(cfg, install_config_path=tmp_path / "install.json")
    assert second["services"]["api"]["state"] == "already_running"
    assert second["services"]["web"]["state"] == "already_running"
    status = status_installation(cfg)
    assert status["services"]["api"]["state"] == "running"


def test_stop_cleans_stale_pid(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    paths.api_pid_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr("sol.install.lifecycle._process_running", lambda pid: False)
    stopped = stop_installation(cfg)
    assert stopped["api"]["state"] == "stale_pid_removed"
    assert not paths.api_pid_path.exists()


def test_uninstall_removes_runtime_bundle_launchers_and_install_config(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
        service_mode=ServiceMode.NONE,
    )
    _stub_managed_runtime(monkeypatch)
    ensure_installation_ready(cfg)
    install_cfg = tmp_path / "install.json"
    save_install_config(cfg, install_cfg)

    launcher_dir = tmp_path / "bin"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    nexai_launcher = launcher_dir / "nexai"
    sol_launcher = launcher_dir / "sol"
    marker = f'export SOL_BOOTSTRAP_APP_ROOT="{cfg.app_root.resolve(strict=False)}"\n'
    nexai_launcher.write_text(marker, encoding="utf-8")
    sol_launcher.write_text(marker, encoding="utf-8")

    bootstrap_record = tmp_path / "bootstrap" / "app_root.txt"
    bootstrap_record.parent.mkdir(parents=True, exist_ok=True)
    bootstrap_record.write_text(str(cfg.app_root.resolve(strict=False)), encoding="utf-8")

    monkeypatch.setattr("sol.install.lifecycle.canonical_user_launcher_path", lambda: nexai_launcher)
    monkeypatch.setattr("sol.install.lifecycle.compatibility_user_launcher_path", lambda: sol_launcher)
    monkeypatch.setattr("sol.install.lifecycle.bootstrap_app_root_record_path", lambda: bootstrap_record)
    monkeypatch.setattr("sol.install.lifecycle.read_bootstrap_app_root", lambda: cfg.app_root.resolve(strict=False))
    monkeypatch.setattr("sol.install.lifecycle._process_running", lambda pid: False)

    result = uninstall_installation(cfg, install_config_path=install_cfg)

    assert result["runtime_root"]["state"] == "removed"
    assert result["app_root"]["state"] == "removed"
    assert result["install_config"]["state"] == "removed"
    assert result["launchers"]["nexai"]["state"] == "removed"
    assert result["launchers"]["sol"]["state"] == "removed"
    assert result["bootstrap_record"]["state"] == "removed"
    assert not cfg.runtime_root.exists()
    assert not cfg.app_root.exists()
    assert not install_cfg.exists()


def test_uninstall_can_keep_app_root(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
        service_mode=ServiceMode.NONE,
    )
    _stub_managed_runtime(monkeypatch)
    ensure_installation_ready(cfg)
    install_cfg = tmp_path / "install.json"
    save_install_config(cfg, install_cfg)
    monkeypatch.setattr("sol.install.lifecycle.canonical_user_launcher_path", lambda: tmp_path / "bin" / "nexai")
    monkeypatch.setattr("sol.install.lifecycle.compatibility_user_launcher_path", lambda: tmp_path / "bin" / "sol")
    monkeypatch.setattr("sol.install.lifecycle.bootstrap_app_root_record_path", lambda: tmp_path / "bootstrap" / "app_root.txt")
    monkeypatch.setattr("sol.install.lifecycle.read_bootstrap_app_root", lambda: None)
    monkeypatch.setattr("sol.install.lifecycle._process_running", lambda pid: False)

    result = uninstall_installation(cfg, install_config_path=install_cfg, remove_app_root=False)

    assert result["runtime_root"]["state"] == "removed"
    assert result["app_root"]["state"] == "kept"
    assert cfg.app_root.exists()


def test_start_failure_reports_log_path_and_log_tail(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    monkeypatch.setattr("sol.install.lifecycle.dependency_report", lambda config, python_executable=None: [])
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: False)
    state = {"alive": False}
    monkeypatch.setattr("sol.install.lifecycle._process_running", lambda pid: state["alive"])

    def _fake_spawn(args, env, pid_path, cwd, log_path, service):
        log_path.write_text("Traceback\nModuleNotFoundError: No module named 'fastapi'\n", encoding="utf-8")
        pid_path.write_text("4321", encoding="utf-8")
        return 4321

    monkeypatch.setattr("sol.install.lifecycle._spawn_process", _fake_spawn)
    result = start_installation(cfg, install_config_path=tmp_path / "install.json")
    assert result["services"]["api"]["state"] == "failed"
    assert "fastapi" in result["services"]["api"]["error"]
    assert result["services"]["api"]["log_path"] == str(paths.api_log_path)


def test_standard_profile_declares_api_runtime_dependencies() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert "rich>=13.7" in data["project"]["dependencies"]
    standard = data["project"]["optional-dependencies"]["standard"]
    assert "fastapi>=0.110" in standard
    assert "uvicorn[standard]>=0.27" in standard
    assert "pydantic>=2.6" in standard


def test_profile_dependency_targets() -> None:
    cfg_cli = build_install_config(
        app_root=Path("/tmp/app"),
        runtime_root=Path("/tmp/runtime"),
        working_dir=Path("/tmp/work"),
        profile=InstallProfile.CLI,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    cfg_server = build_install_config(
        app_root=Path("/tmp/app"),
        runtime_root=Path("/tmp/runtime"),
        working_dir=Path("/tmp/work"),
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    cfg_standard = build_install_config(
        app_root=Path("/tmp/app"),
        runtime_root=Path("/tmp/runtime"),
        working_dir=Path("/tmp/work"),
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    cfg_dev = build_install_config(
        app_root=Path("/tmp/app"),
        runtime_root=Path("/tmp/runtime"),
        working_dir=Path("/tmp/work"),
        profile=InstallProfile.DEVELOPER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    assert profile_extra_name(cfg_cli) == "cli"
    assert profile_extra_name(cfg_server) == "server"
    assert profile_extra_name(cfg_standard) == "standard"
    assert profile_extra_name(cfg_dev) == "developer"
    assert required_dependency_packages(cfg_cli) == ()
    assert required_dependency_packages(cfg_server) == ("uvicorn[standard]>=0.27", "fastapi>=0.110", "pydantic>=2.6")
    assert "pytest>=8.0" in required_dependency_packages(cfg_dev)
    assert install_target_for_config(cfg_standard).endswith("[standard]")


def test_ensure_installation_ready_provisions_runtime_env(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2").mkdir(parents=True)
    (app_root / "SolVersion2" / "sol").mkdir()
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "plugins").mkdir()
    (app_root / "SolVersion2" / "skills").mkdir()
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    seen: list[list[str]] = []

    class _FakeEnvBuilder:
        def __init__(self, *, with_pip, clear, symlinks):
            self.with_pip = with_pip
            self.clear = clear
            self.symlinks = symlinks

        def create(self, env_dir: str) -> None:
            env_path = Path(env_dir)
            py = env_path / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("", encoding="utf-8")

    monkeypatch.setattr("sol.install.lifecycle.venv.EnvBuilder", _FakeEnvBuilder)
    monkeypatch.setattr("sol.install.lifecycle._run_logged", lambda args, *, cwd, log_path, env=None: seen.append(list(args)))
    monkeypatch.setattr("sol.install.lifecycle._runtime_environment_needs_install", lambda config, paths: True)
    monkeypatch.setattr("sol.install.lifecycle._runtime_package_ready", lambda python_path: True)
    monkeypatch.setattr("sol.install.lifecycle.dependency_report", lambda config, python_executable=None: [])
    paths = ensure_installation_ready(cfg)
    assert paths.runtime_venv_dir.exists()
    assert paths.runtime_python_path.exists()
    assert any("pip" in cmd for cmd in seen)
    assert str(paths.install_log_path).endswith("install.log")


def test_ensure_installation_ready_fails_when_managed_runtime_missing(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "plugins").mkdir()
    (app_root / "SolVersion2" / "skills").mkdir()
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    class _NoopEnvBuilder:
        def __init__(self, *, with_pip, clear, symlinks):
            pass

        def create(self, env_dir: str) -> None:
            return None

    monkeypatch.setattr("sol.install.lifecycle.venv.EnvBuilder", _NoopEnvBuilder)
    monkeypatch.setattr("sol.install.lifecycle._run_logged", lambda *args, **kwargs: None)
    monkeypatch.setattr("sol.install.lifecycle._runtime_environment_needs_install", lambda config, paths: True)
    monkeypatch.setattr("sol.install.lifecycle.dependency_report", lambda config, python_executable=None: [])
    try:
        ensure_installation_ready(cfg)
    except RuntimeError as exc:
        assert "Managed runtime was not created" in str(exc)
        assert "install.log" in str(exc)
        assert (tmp_path / "runtime" / "logs" / "install.log").exists()
    else:
        raise AssertionError("Expected managed runtime verification failure")


def test_doctor_reports_missing_managed_runtime(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    report = run_doctor(cfg)
    assert report["ok"] is False
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["runtime_venv"]["ok"] is False
    assert by_name["runtime_python"]["ok"] is False
    assert report["managed_runtime"]["required"] is True
    assert Path(report["paths"]["managed_runtime_path"]).name == "venv"
    assert report["managed_runtime_exists"] is False
    assert report["managed_python_exists"] is False
    assert report["launcher_path"].endswith("nexai") or report["launcher_path"].endswith("nexai.cmd")
    assert report["runtime_launcher_path"].endswith("sol") or report["runtime_launcher_path"].endswith("sol.cmd")
    assert report["imports"]["uvicorn"]["ok"] is False
    assert any("Managed runtime virtual environment is missing" in item for item in report["problems"])


def test_doctor_flags_windows_drive_paths_in_runtime_config_on_wsl(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    _stub_managed_runtime(monkeypatch)
    paths = ensure_installation_ready(cfg)
    paths.config_path.write_text(
        paths.config_path.read_text(encoding="utf-8") + '\n[broken]\nsource_path = "C:\\\\example\\\\sol"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sol.install.lifecycle.detect_platform",
        lambda: type(
            "Platform",
            (),
            {
                "system": "linux",
                "is_linux": True,
                "is_wsl": True,
                "wsl_version": "2",
                "systemd_user_available": False,
                "notes": [],
            },
        )(),
    )
    report = run_doctor(cfg)
    assert report["ok"] is False
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["runtime_config_portable_paths"]["ok"] is False
    assert report["runtime_config_portability"]["linux_wsl_check_applied"] is True
    assert report["runtime_config_portability"]["windows_drive_path_findings"]
    assert any("Windows drive path" in item["message"] for item in report["runtime_config_portability"]["windows_drive_path_findings"])
    assert any("Runtime config embeds a Windows drive path" in item for item in report["problems"])


def test_runtime_inspect_reports_missing_managed_runtime(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    report = inspect_runtime(cfg)
    assert report["ready"] is False
    assert report["managed_runtime_exists"] is False
    assert report["managed_python_exists"] is False
    assert report["imports"]["fastapi"]["ok"] is False
    assert report["python_executable"]
    assert report["sol_module_path"].endswith("sol\\__init__.py") or report["sol_module_path"].endswith("sol/__init__.py")
    assert report["sol_cli_path"].endswith("sol\\cli\\__init__.py") or report["sol_cli_path"].endswith("sol/cli/__init__.py")
    assert report["launcher_path"].endswith("nexai") or report["launcher_path"].endswith("nexai.cmd")
    assert report["runtime_launcher_path"].endswith("sol") or report["runtime_launcher_path"].endswith("sol.cmd")


def test_load_config_infers_app_root_from_explicit_app_paths(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    config_dir = runtime_root / "config"
    config_dir.mkdir(parents=True)
    app_root = tmp_path / "installed-sol"
    cfg_path = config_dir / "sol.toml"
    cfg_path.write_text(
        f"""
[paths]
plugins_dir = "{(app_root / 'SolVersion2' / 'plugins').as_posix()}"
skills_dir = "{(app_root / 'SolVersion2' / 'skills').as_posix()}"
features_dir = "{(app_root / 'SolVersion2' / 'Server' / 'data' / 'features').as_posix()}"
api_dir = "{(app_root / 'apps' / 'api').as_posix()}"
web_dir = "{(app_root / 'SolWeb').as_posix()}"
web_dist_dir = "{(app_root / 'SolWeb' / 'dist').as_posix()}"
working_dir = "{(runtime_root / 'work').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.paths.app_root == app_root.resolve()
    assert cfg.root_dir == app_root.resolve()
    assert cfg.paths.runtime_root == runtime_root.resolve()


def test_runtime_inspect_cli_returns_nonzero_for_missing_runtime(tmp_path: Path, capsys) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    install_cfg = tmp_path / "install.json"
    runtime_root = tmp_path / "runtime"
    work_root = tmp_path / "work"
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=runtime_root,
        working_dir=work_root,
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    save_install_config(cfg, install_cfg)
    code = cli_main(["--install-config", str(install_cfg), "runtime", "inspect"])
    captured = capsys.readouterr()
    assert code == 2
    assert '"managed_runtime_exists": false' in captured.out


def test_preflight_warns_when_launcher_dir_not_on_path(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    install_cfg = tmp_path / "install.json"
    monkeypatch.setenv("PATH", "/usr/bin")
    checks, failures = _run_preflight(app_root=app_root, install_cfg_path=install_cfg)
    assert failures == []
    assert any(item.title == "PATH" and item.status == "warn" for item in checks)


def test_doctor_cli_renders_human_friendly_report(tmp_path: Path, capsys, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    install_cfg = tmp_path / "install.json"
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    save_install_config(cfg, install_cfg)
    code = cli_main(["--install-config", str(install_cfg), "doctor"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Doctor" in captured.out
    assert "Managed runtime" in captured.out
    assert "nexai" in captured.out.lower() or "nexai" in captured.err.lower()


def test_start_cli_renders_failure_guidance_for_missing_runtime(tmp_path: Path, capsys) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    install_cfg = tmp_path / "install.json"
    runtime_root = tmp_path / "runtime"
    (runtime_root / "config").mkdir(parents=True, exist_ok=True)
    (runtime_root / "config" / "sol.toml").write_text("", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=runtime_root,
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    save_install_config(cfg, install_cfg)
    code = cli_main(["--install-config", str(install_cfg), "start"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Startup Failed" in captured.out
    assert "Managed runtime is missing or incomplete" in captured.out
    assert "nexai doctor" in captured.out.lower()


def test_start_aborts_when_managed_runtime_missing(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2").mkdir(parents=True)
    (app_root / "SolVersion2" / "pyproject.toml").write_text("[project]\nname='solversion2'\nversion='0.0.0'\n", encoding="utf-8")
    (app_root / "SolVersion2" / "plugins").mkdir()
    (app_root / "SolVersion2" / "skills").mkdir()
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    paths = tmp_path / "runtime" / "config"
    paths.mkdir(parents=True, exist_ok=True)
    (paths / "sol.toml").write_text("", encoding="utf-8")
    result = start_installation(cfg, install_config_path=tmp_path / "install.json")
    assert result["services"]["api"]["state"] == "missing_runtime"
    assert "Managed runtime is missing or incomplete" in result["services"]["api"]["error"]
    assert result["services"]["api"]["log_path"].endswith("install.log")
    assert result["services"]["api"]["service_log_path"].endswith("api.log")
    assert (tmp_path / "runtime" / "logs" / "api.log").exists()


def test_internal_serve_api_failure_is_logged(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "sol").mkdir(parents=True)
    install_cfg = tmp_path / "install.json"
    cfg = build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.SERVER,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
    )
    save_install_config(cfg, install_cfg)
    monkeypatch.setattr("sol.cli.serve_api_forever", lambda config: (_ for _ in ()).throw(RuntimeError("boom")))
    code = cli_main(["--install-config", str(install_cfg), "internal", "serve-api"])
    api_log = tmp_path / "runtime" / "logs" / "api.log"
    assert code == 2
    assert api_log.exists()
    assert "RuntimeError: boom" in api_log.read_text(encoding="utf-8")

def test_setup_cli_fails_when_provisioning_does_not_create_runtime(tmp_path: Path, monkeypatch, capsys) -> None:
    app_root = tmp_path / "app"
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
    class _NoopEnvBuilder:
        def __init__(self, *, with_pip, clear, symlinks):
            pass

        def create(self, env_dir: str) -> None:
            return None

    monkeypatch.setattr("sol.install.lifecycle.venv.EnvBuilder", _NoopEnvBuilder)
    code = cli_main(
        [
            "--install-config",
            str(install_cfg),
            "setup",
            "--non-interactive",
            "--app-root",
            str(app_root),
            "--runtime-root",
            str(runtime_root),
            "--working-dir",
            str(work_root),
            "--profile",
            "standard",
            "--model-provider",
            "stub",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Managed runtime was not created" in captured.out
    assert "Log file:" in captured.out
    assert "NexAI is ready." not in captured.out
    assert (runtime_root / "logs" / "install.log").exists()
    assert not install_cfg.exists()
