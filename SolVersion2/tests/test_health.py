from __future__ import annotations

from pathlib import Path

from sol.cli import main as cli_main
from sol.install.lifecycle import collect_health_report
from sol.install.models import InstallProfile, ServiceMode
from sol.install.store import save_install_config
from sol.install.wizard import build_install_config


def _config(tmp_path: Path, *, provider: str = "ollama") -> object:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
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
        service_mode=ServiceMode.SYSTEMD_USER,
    )


def test_health_api_running_reports_healthy(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: url.endswith("/v1/status"))
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": model, "model_available": True, "category": "connected", "detail": None})(),
    )
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True)
    result = collect_health_report(config)
    assert result["api"]["healthy"] is True
    assert result["api"]["message"] == "healthy (200 OK)"
    assert result["overall"] == "OK"


def test_health_api_down_reports_unhealthy(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "inactive"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: False if url.endswith("/v1/status") else True)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": model, "model_available": True, "category": "connected", "detail": None})(),
    )
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True)
    result = collect_health_report(config)
    assert result["api"]["message"] == "unhealthy"
    assert result["overall"] == "FAIL"


def test_health_web_reachable_reports_reachable(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True if url.endswith("/v1/status") else False)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": model, "model_available": True, "category": "connected", "detail": None})(),
    )
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True if port == 5173 else False)
    result = collect_health_report(config)
    assert result["web"]["message"] == "reachable"


def test_health_web_down_reports_unreachable(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "inactive"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True if url.endswith("/v1/status") else False)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": model, "model_available": True, "category": "connected", "detail": None})(),
    )
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: False)
    result = collect_health_report(config)
    assert result["web"]["message"] == "unreachable"
    assert result["services"]["summary"] == "partially running (systemd-user)"
    assert result["overall"] == "DEGRADED"


def test_health_ollama_reachable_reports_connected(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="ollama")
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True if url.endswith("/v1/status") else False)
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": model, "model_available": True, "category": "connected", "detail": None})(),
    )
    result = collect_health_report(config)
    assert result["model"]["message"] == "ollama (connected)"


def test_health_ollama_down_reports_disconnected(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="ollama")
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True if url.endswith("/v1/status") else False)
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "unreachable", "base_url": base_url, "model": model, "model_available": None, "category": "provider_unreachable", "detail": "connection refused"})(),
    )
    result = collect_health_report(config)
    assert result["model"]["message"] == "ollama (disconnected)"
    assert result["overall"] == "DEGRADED"


def test_health_ollama_model_missing_reports_model_missing(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="ollama")
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True if url.endswith("/v1/status") else False)
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": "qwen3.5:9b", "model_available": False, "category": "model_unavailable", "detail": None})(),
    )
    result = collect_health_report(config)
    assert result["model"]["message"] == "ollama (model missing: qwen3.5:9b)"
    assert result["overall"] == "DEGRADED"


def test_health_fully_running_service_summary(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="ollama")
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "active"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: True if url.endswith("/v1/status") else False)
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: True)
    monkeypatch.setattr(
        "sol.install.lifecycle.probe_ollama_provider",
        lambda base_url, model=None, timeout_s=2.0: type("Probe", (), {"status": "reachable", "base_url": base_url, "model": model, "model_available": True, "category": "connected", "detail": None})(),
    )
    result = collect_health_report(config)
    assert result["services"]["summary"] == "running (systemd-user)"
    assert result["overall"] == "OK"


def test_health_stopped_service_summary(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="stub")
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "inactive"}, "web": {"state": "inactive"}}},
    )
    monkeypatch.setattr("sol.install.lifecycle._http_health", lambda url, timeout_s=1.0: False)
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: False)
    result = collect_health_report(config)
    assert result["services"]["summary"] == "stopped (systemd-user)"
    assert result["overall"] == "FAIL"


def test_health_partial_runtime_with_healthy_api_is_degraded(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, provider="stub")
    monkeypatch.setattr(
        "sol.install.lifecycle.status_installation",
        lambda cfg: {"service_mode": "systemd-user", "services": {"api": {"state": "active"}, "web": {"state": "inactive"}}},
    )

    def fake_http_health(url: str, timeout_s: float = 1.0) -> bool:
        if url.endswith("/v1/status"):
            return True
        return False

    monkeypatch.setattr("sol.install.lifecycle._http_health", fake_http_health)
    monkeypatch.setattr("sol.install.lifecycle._port_open", lambda host, port, timeout_s=0.2: False)
    result = collect_health_report(config)
    assert result["services"]["summary"] == "partially running (systemd-user)"
    assert result["overall"] == "DEGRADED"


def test_health_cli_renders_human_readable_output(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    monkeypatch.setattr(
        "sol.cli.collect_health_report",
        lambda install: {
            "api": {"message": "healthy (200 OK)"},
            "web": {"message": "reachable"},
            "services": {"summary": "running (systemd-user)"},
            "model": {"message": "ollama (connected)"},
            "overall": "OK",
        },
    )
    code = cli_main(["--install-config", str(install_cfg), "health"])
    captured = capsys.readouterr()
    assert code == 0
    assert "NexAI Health Check" in captured.out
    assert "healthy (200 OK)" in captured.out
    assert "reachable" in captured.out
    assert "running (systemd-user)" in captured.out
    assert "ollama (connected)" in captured.out
    assert "Overall" in captured.out
