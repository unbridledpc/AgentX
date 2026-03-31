from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sol_api.app import create_app
from sol_api.auth import session_store
from sol_api.config import config
import sol_api.routes.settings as settings_route
from sol_api.routes.settings import SettingsModel


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post("/v1/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_chat_prefers_solv2_runtime_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "auth_enabled", True)
    monkeypatch.setattr(config, "auth_users", {"alice": hashlib.sha256(b"alice-pass").hexdigest()})
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()

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

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="llama3.2"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), _FakeAgent()))

    client = TestClient(create_app())
    headers = _auth_headers(client)
    response = client.post("/v1/chat", json={"message": "hello", "thread_id": None}, headers=headers)
    assert response.status_code == 200, response.text
    assert captured["user_message"] == "hello"
    assert captured["provider"] == "ollama"
    assert captured["model"] == "llama3.2"


def test_runtime_state_exposes_working_memory_snapshot(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "settings_path", tmp_path / "settings.json")
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "auth_enabled", True)
    monkeypatch.setattr(config, "auth_users", {"alice": hashlib.sha256(b"alice-pass").hexdigest()})
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()

    class _FakeHandle:
        pass

    class _FakeAgent:
        def runtime_state_snapshot(self):
            return {
                "mode": "supervised",
                "thread_id": "thread-1",
                "user_id": "alice",
                "working_memory": {
                    "goal": "Inspect repo",
                    "current_subgoal": "Execute fs.list",
                    "recent_tool_outputs": [{"tool": "fs.list", "ok": True}],
                    "decisions": [{"action": "run_plan", "reason": "tool-addressable"}],
                },
            }

    monkeypatch.setattr("sol_api.routes.solv2.get_agent_for_thread", lambda thread_id, user=None: (_FakeHandle(), _FakeAgent()))

    client = TestClient(create_app())
    headers = _auth_headers(client)
    response = client.get("/v1/runtime/state", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()["state"]
    assert payload["working_memory"]["goal"] == "Inspect repo"
    assert payload["working_memory"]["decisions"][0]["action"] == "run_plan"
