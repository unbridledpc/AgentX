from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentx_api.app import create_app
from agentx_api.config import config


def _prepare(monkeypatch, tmp_path: Path) -> None:
    threads_dir = tmp_path / "threads"
    projects_dir = tmp_path / "projects"
    scripts_dir = tmp_path / "scripts"
    for path in (threads_dir, projects_dir, scripts_dir):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "projects_dir", projects_dir)
    monkeypatch.setattr(config, "scripts_dir", scripts_dir)
    monkeypatch.setattr(config, "rag_db_path", tmp_path / "rag.sqlite3")
    monkeypatch.setattr(config, "auth_enabled", False)
    monkeypatch.setattr(config, "rate_limit_enabled", False)


def test_runtime_diagnostics_reports_safe_local_warnings(monkeypatch, tmp_path: Path) -> None:
    _prepare(monkeypatch, tmp_path)
    client = TestClient(create_app())

    response = client.get("/v1/runtime/diagnostics")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["config"]["auth_enabled"] is False
    assert any("Authentication is disabled" in item for item in payload["warnings"])
    assert response.headers.get("x-request-id")


def test_request_id_header_is_preserved(monkeypatch, tmp_path: Path) -> None:
    _prepare(monkeypatch, tmp_path)
    client = TestClient(create_app())

    response = client.get("/v1/status", headers={"X-Request-ID": "agentx-test-request"})

    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"] == "agentx-test-request"


def test_rate_limiter_can_block_when_enabled(monkeypatch, tmp_path: Path) -> None:
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "rate_limit_enabled", True)
    monkeypatch.setattr(config, "rate_limit_requests", 1)
    monkeypatch.setattr(config, "rate_limit_window_s", 60)
    client = TestClient(create_app())

    first = client.get("/v1/runtime/diagnostics")
    second = client.get("/v1/runtime/diagnostics")

    assert first.status_code == 200, first.text
    assert second.status_code == 429, second.text
    assert second.json()["detail"] == "Rate limit exceeded."
