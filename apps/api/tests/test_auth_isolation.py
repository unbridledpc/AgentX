from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sol_api.app import create_app
from sol_api.auth import session_store
from sol_api.config import config
import sol_api.routes.settings as settings_route
from sol_api.routes.settings import SettingsModel


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "settings_path", settings_path)
    monkeypatch.setattr(config, "threads_dir", threads_dir)
    monkeypatch.setattr(config, "auth_enabled", True)
    monkeypatch.setattr(config, "auth_session_ttl_s", 3600)
    monkeypatch.setattr(
        config,
        "auth_users",
        {
            "alice": _sha256("alice-pass"),
            "bob": _sha256("bob-pass"),
        },
    )
    with settings_route._CACHE_LOCK:
        settings_route._CACHED_SETTINGS = None
    session_store.reset_for_tests()
    app = create_app()
    try:
        yield TestClient(app)
    finally:
        session_store.reset_for_tests()
        with settings_route._CACHE_LOCK:
            settings_route._CACHED_SETTINGS = None


def _auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    res = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_protected_routes_require_authentication(client: TestClient) -> None:
    for method, path in (
        ("get", "/v1/settings"),
        ("get", "/v1/threads"),
        ("get", "/v1/agent/unsafe/thread-1"),
        ("post", "/v1/chat"),
    ):
        if method == "get":
            res = client.get(path, headers={"X-Sol-User": "alice"})
        else:
            res = client.post(path, json={"message": "hi"}, headers={"X-Sol-User": "alice"})
        assert res.status_code == 401


def test_spoofed_identity_header_does_not_override_authenticated_user(client: TestClient) -> None:
    alice_headers = _auth_headers(client, "alice", "alice-pass")
    bob_headers = _auth_headers(client, "bob", "bob-pass")

    res = client.post("/v1/threads", json={"title": "Alice thread"}, headers={**alice_headers, "X-Sol-User": "bob"})
    assert res.status_code == 200, res.text
    thread_id = res.json()["id"]

    alice_threads = client.get("/v1/threads", headers=alice_headers)
    bob_threads = client.get("/v1/threads", headers=bob_headers)
    assert alice_threads.status_code == 200
    assert bob_threads.status_code == 200
    assert [item["id"] for item in alice_threads.json()] == [thread_id]
    assert bob_threads.json() == []


def test_threads_are_isolated_per_authenticated_user(client: TestClient) -> None:
    alice_headers = _auth_headers(client, "alice", "alice-pass")
    bob_headers = _auth_headers(client, "bob", "bob-pass")

    created = client.post("/v1/threads", json={"title": "Secret"}, headers=alice_headers)
    assert created.status_code == 200, created.text
    thread_id = created.json()["id"]

    assert client.get(f"/v1/threads/{thread_id}", headers=bob_headers).status_code == 404
    assert client.post(f"/v1/threads/{thread_id}/title", json={"title": "Hijacked"}, headers=bob_headers).status_code == 404
    assert client.delete(f"/v1/threads/{thread_id}", headers=bob_headers).status_code == 404
    assert client.get(f"/v1/threads/{thread_id}", headers=alice_headers).status_code == 200


def test_active_thread_tracking_isolated_per_authenticated_user(client: TestClient, monkeypatch) -> None:
    alice_headers = _auth_headers(client, "alice", "alice-pass")
    bob_headers = _auth_headers(client, "bob", "bob-pass")

    created = client.post("/v1/threads", json={"title": "Alice session"}, headers=alice_headers)
    thread_id = created.json()["id"]
    appended = client.post(
        f"/v1/threads/{thread_id}/messages",
        json={"role": "user", "content": "remember this"},
        headers=alice_headers,
    )
    assert appended.status_code == 200, appended.text

    captured: list[str | None] = []

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    class _FakeAgent:
        def chat(self, *, user_message: str, provider: str, model: str, thread_id: str | None = None, response_mode: str = "chat"):
            captured.append(thread_id)
            return SimpleNamespace(
                text="ok",
                retrieved=tuple(),
                sources=tuple(),
                verification_level=None,
                verification=None,
                tool_results=tuple(),
            )

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="llama3.2"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), _FakeAgent()))

    bob_chat = client.post("/v1/chat", json={"message": "hi"}, headers=bob_headers)
    alice_chat = client.post("/v1/chat", json={"message": "hi"}, headers=alice_headers)

    assert bob_chat.status_code == 200, bob_chat.text
    assert alice_chat.status_code == 200, alice_chat.text
    assert captured == [None, thread_id]


def test_unsafe_mode_uses_authenticated_user_not_spoofed_header(client: TestClient, monkeypatch) -> None:
    import sol.core.unsafe_mode as unsafe_mode

    alice_headers = _auth_headers(client, "alice", "alice-pass")
    created = client.post("/v1/threads", json={"title": "Unsafe thread"}, headers=alice_headers)
    thread_id = created.json()["id"]

    captured: dict[str, str | None] = {}

    def _fake_enable(thread_id: str, *, reason: str, user: str | None = None, cfg=None):
        captured["user"] = user
        return SimpleNamespace(thread_id=thread_id, unsafe_enabled=True, enabled_at="now", enabled_by=user, reason=reason)

    monkeypatch.setattr("sol_api.routes.unsafe.get_handle", lambda: SimpleNamespace(cfg=object()))
    monkeypatch.setattr(unsafe_mode, "enable", _fake_enable)

    response = client.post(
        f"/v1/agent/unsafe/{thread_id}/enable",
        json={"reason": "needed"},
        headers={**alice_headers, "X-Sol-User": "bob"},
    )

    assert response.status_code == 200, response.text
    assert captured["user"] == "alice"
