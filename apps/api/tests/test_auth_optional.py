from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentx_api.app import create_app
from agentx_api.auth import session_store
from agentx_api.config import config
from agentx_api.rag.session import session_tracker
import agentx_api.routes.settings as settings_route


def test_local_mode_allows_protected_routes_without_login(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    threads_dir = tmp_path / "threads"
    projects_dir = tmp_path / "projects"
    scripts_dir = tmp_path / "scripts"
    threads_dir.mkdir(parents=True, exist_ok=True)
    projects_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "settings_path", settings_path)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "projects_dir", projects_dir)
    monkeypatch.setattr(config, "scripts_dir", scripts_dir)
    monkeypatch.setattr(config, "auth_enabled", False)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    client = TestClient(create_app())

    status = client.get("/v1/status")
    assert status.status_code == 200, status.text
    assert status.json()["auth_enabled"] is False

    settings = client.get("/v1/settings")
    assert settings.status_code == 200, settings.text

    created = client.post("/v1/threads", json={"title": "Local thread"})
    assert created.status_code == 200, created.text
    thread_id = created.json()["id"]

    threads = client.get("/v1/threads")
    assert threads.status_code == 200, threads.text
    assert [item["id"] for item in threads.json()] == [thread_id]
    session_tracker.reset_for_tests()


def test_login_route_reports_when_auth_is_disabled(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    threads_dir = tmp_path / "threads"
    projects_dir = tmp_path / "projects"
    scripts_dir = tmp_path / "scripts"
    threads_dir.mkdir(parents=True, exist_ok=True)
    projects_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "settings_path", settings_path)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "projects_dir", projects_dir)
    monkeypatch.setattr(config, "scripts_dir", scripts_dir)
    monkeypatch.setattr(config, "auth_enabled", False)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()

    client = TestClient(create_app())
    response = client.post("/v1/auth/login", json={"username": "agentx", "password": "ignored"})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Authentication is disabled for this install."


def test_cors_allows_runtime_web_origin_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENTX_CORS_ALLOW_ORIGINS", "http://172.17.24.34:5173")
    client = TestClient(create_app())

    response = client.get("/v1/status", headers={"Origin": "http://172.17.24.34:5173"})

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://172.17.24.34:5173"


def test_cors_allows_runtime_web_origin_alias_from_env(monkeypatch) -> None:
    monkeypatch.delenv("AGENTX_CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.setenv("AGENTX_WEB_ORIGIN", "http://172.17.24.34:5173")
    client = TestClient(create_app())

    response = client.get("/v1/status", headers={"Origin": "http://172.17.24.34:5173"})

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://172.17.24.34:5173"


def _prepare_local_thread_test(monkeypatch, tmp_path: Path) -> TestClient:
    settings_path = tmp_path / "settings.json"
    threads_dir = tmp_path / "threads"
    projects_dir = tmp_path / "projects"
    scripts_dir = tmp_path / "scripts"
    threads_dir.mkdir(parents=True, exist_ok=True)
    projects_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "settings_path", settings_path)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "projects_dir", projects_dir)
    monkeypatch.setattr(config, "scripts_dir", scripts_dir)
    monkeypatch.setattr(config, "auth_enabled", False)
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    session_tracker.reset_for_tests()
    return TestClient(create_app())


def test_thread_model_selection_is_stored_and_listed(monkeypatch, tmp_path: Path) -> None:
    client = _prepare_local_thread_test(monkeypatch, tmp_path)

    created = client.post(
        "/v1/threads",
        json={"title": "Coder thread", "chat_provider": "ollama", "chat_model": "qwen2.5-coder:7b"},
    )

    assert created.status_code == 200, created.text
    thread = created.json()
    assert thread["chat_provider"] == "ollama"
    assert thread["chat_model"] == "qwen2.5-coder:7b"

    listed = client.get("/v1/threads")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["chat_provider"] == "ollama"
    assert listed.json()[0]["chat_model"] == "qwen2.5-coder:7b"


def test_thread_model_selection_can_be_updated(monkeypatch, tmp_path: Path) -> None:
    client = _prepare_local_thread_test(monkeypatch, tmp_path)
    thread = client.post(
        "/v1/threads",
        json={"title": "Switch model", "chat_provider": "ollama", "chat_model": "qwen2.5-coder:7b"},
    ).json()

    updated = client.post(
        f"/v1/threads/{thread['id']}/model",
        json={"chat_provider": "ollama", "chat_model": "qwen3.5:9b"},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["chat_provider"] == "ollama"
    assert updated.json()["chat_model"] == "qwen3.5:9b"

    reloaded = client.get(f"/v1/threads/{thread['id']}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["chat_model"] == "qwen3.5:9b"


def test_chat_uses_thread_model_instead_of_global_settings(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace

    import agentx_api.routes.chat as chat_route
    from agentx_api.routes.settings import SettingsModel

    client = _prepare_local_thread_test(monkeypatch, tmp_path)
    thread = client.post(
        "/v1/threads",
        json={"title": "Per-chat model", "chat_provider": "ollama", "chat_model": "qwen2.5-coder:7b"},
    ).json()

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    captured: dict[str, object] = {}

    class _FakeAgent:
        def chat(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="ok", retrieved=tuple(), sources=tuple(), verification_level=None, verification=None, tool_results=tuple())

    monkeypatch.setattr(chat_route, "_read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="global-model"))
    monkeypatch.setattr(chat_route, "_get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), _FakeAgent()))

    response = client.post("/v1/chat", json={"message": "hello", "thread_id": thread["id"]})

    assert response.status_code == 200, response.text
    assert captured["provider"] == "ollama"
    assert captured["model"] == "qwen2.5-coder:7b"


def test_projects_can_group_threads(monkeypatch, tmp_path: Path) -> None:
    client = _prepare_local_thread_test(monkeypatch, tmp_path)

    project_response = client.post("/v1/projects", json={"name": "AgentX UI"})
    assert project_response.status_code == 200, project_response.text
    project = project_response.json()

    thread_response = client.post("/v1/threads", json={"title": "Project chat", "project_id": project["id"]})
    assert thread_response.status_code == 200, thread_response.text
    assert thread_response.json()["project_id"] == project["id"]

    listed = client.get("/v1/threads")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["project_id"] == project["id"]

    moved = client.post(f"/v1/threads/{thread_response.json()['id']}/project", json={"project_id": None})
    assert moved.status_code == 200, moved.text
    assert moved.json()["project_id"] is None


def test_scripts_can_be_saved_updated_and_listed(monkeypatch, tmp_path: Path) -> None:
    client = _prepare_local_thread_test(monkeypatch, tmp_path)

    created = client.post(
        "/v1/scripts",
        json={
            "title": "Hello script",
            "language": "python",
            "content": "print('hello')",
            "model_provider": "ollama",
            "model_name": "qwen2.5-coder:7b",
            "source_thread_id": "thread-1",
            "source_message_id": "message-1",
        },
    )
    assert created.status_code == 200, created.text
    script = created.json()
    assert script["language"] == "python"
    assert script["model_name"] == "qwen2.5-coder:7b"

    listed = client.get("/v1/scripts?query=hello")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == script["id"]

    updated = client.patch(f"/v1/scripts/{script['id']}", json={"title": "Updated", "content": "print('updated')"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Updated"
    assert updated.json()["content"] == "print('updated')"
