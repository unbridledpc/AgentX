from __future__ import annotations

import io
import json
import socket
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from sol_api.ollama import fetch_ollama_models, normalize_ollama_base_url
from sol_api.routes.chat import ChatRequest, _ollama_generate, chat
from sol_api.routes.settings import SettingsModel, effective_ollama_base_url, effective_ollama_request_timeout_s, save_settings
from sol_api.routes.status import status


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_effective_ollama_base_url_uses_settings_override() -> None:
    settings = SettingsModel(ollamaBaseUrl="10.0.0.44:11434")
    assert effective_ollama_base_url(settings) == "http://10.0.0.44:11434"
    assert normalize_ollama_base_url("http://10.0.0.44:11434/") == "http://10.0.0.44:11434"


def test_fetch_ollama_models_reports_unreachable(monkeypatch) -> None:
    def _boom(req, timeout=0):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    result = fetch_ollama_models(base_url="http://10.0.0.44:11434", timeout_s=0.1)
    assert result.models == []
    assert result.error is not None
    assert result.error_type == "provider_unreachable"
    assert "Configured Ollama endpoint could not be reached" in result.error


def test_ollama_generate_uses_configured_settings_url(monkeypatch) -> None:
    captured = {}

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps({"response": "ok"}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr(
        "sol_api.routes.chat._read_settings",
        lambda: SettingsModel(
            chatProvider="ollama",
            chatModel="llama3.2",
            ollamaBaseUrl="http://10.0.0.44:11434",
            ollamaRequestTimeoutS=90,
        ),
    )
    output = _ollama_generate("hi", "llama3.2")
    assert output == "ok"
    assert captured["url"] == "http://10.0.0.44:11434/api/generate"
    assert captured["timeout"] == 90


def test_ollama_generate_returns_structured_provider_http_error(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url,
            404,
            "not found",
            hdrs=None,
            fp=io.BytesIO(b"missing route"),
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="llama3.2", ollamaBaseUrl="http://10.0.0.44:11434"))
    with pytest.raises(Exception) as excinfo:
        _ollama_generate("hi", "llama3.2")
    payload = excinfo.value.detail
    assert payload["type"] == "provider_http_error"
    assert payload["provider"] == "ollama"
    assert payload["base_url"] == "http://10.0.0.44:11434"


def test_ollama_generate_returns_structured_timeout(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="qwen3.5:9b", ollamaBaseUrl="http://10.0.0.44:11434"))
    with pytest.raises(Exception) as excinfo:
        _ollama_generate("hi", "qwen3.5:9b")
    payload = excinfo.value.detail
    assert payload["type"] == "provider_timeout"
    assert "timed out" in payload["message"].lower()
    assert payload["timeout_s"] == 60


def test_ollama_generate_returns_structured_model_missing(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url,
            404,
            "not found",
            hdrs=None,
            fp=io.BytesIO(b'model "qwen3.5:9b" not found'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="qwen3.5:9b", ollamaBaseUrl="http://10.0.0.44:11434"))
    with pytest.raises(Exception) as excinfo:
        _ollama_generate("hi", "qwen3.5:9b")
    payload = excinfo.value.detail
    assert payload["type"] == "model_unavailable"
    assert payload["model"] == "qwen3.5:9b"


def test_status_reports_configured_ollama_endpoint_error(monkeypatch) -> None:
    monkeypatch.setattr("sol_api.routes.status._ensure_model_cache", lambda force=False: None)
    monkeypatch.setattr("sol_api.routes.status._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="", ollamaBaseUrl="http://10.0.0.44:11434"))
    monkeypatch.setattr("sol_api.routes.status._MODEL_CACHE", {"openai": [], "ollama": []})
    monkeypatch.setattr("sol_api.routes.status._MODEL_LAST_REFRESH", 1.0)
    monkeypatch.setattr("sol_api.routes.status._MODEL_REFRESHING", False)
    monkeypatch.setattr(
        "sol_api.routes.status._MODEL_LAST_ERROR",
        "Configured Ollama endpoint could not be reached: http://10.0.0.44:11434 (connection refused)",
    )
    res = status(refresh=False)
    assert res.ollama_base_url == "http://10.0.0.44:11434"
    assert res.chat_ready is False
    assert res.chat_error is not None
    assert res.provider_endpoint_status == "unreachable"
    assert res.provider_error_type == "provider_unreachable"
    assert "Configured Ollama endpoint could not be reached" in res.chat_error


def test_status_reports_model_missing(monkeypatch) -> None:
    monkeypatch.setattr("sol_api.routes.status._ensure_model_cache", lambda force=False: None)
    monkeypatch.setattr("sol_api.routes.status._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="qwen3.5:9b", ollamaBaseUrl="http://10.0.0.44:11434"))
    monkeypatch.setattr("sol_api.routes.status._MODEL_CACHE", {"openai": [], "ollama": ["llama3.2"]})
    monkeypatch.setattr("sol_api.routes.status._MODEL_LAST_REFRESH", 1.0)
    monkeypatch.setattr("sol_api.routes.status._MODEL_REFRESHING", False)
    monkeypatch.setattr("sol_api.routes.status._MODEL_LAST_ERROR", None)
    res = status(refresh=False)
    assert res.chat_ready is False
    assert res.provider_endpoint_status == "reachable"
    assert res.provider_model_status == "missing"
    assert res.provider_error_type == "model_unavailable"


def test_chat_spoken_mode_sanitizes_agent_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeAudit:
        def tail(self, limit: int = 50):
            return []

    class _FakeHandle:
        class ctx:
            audit = _FakeAudit()

    class _FakeAgent:
        def chat(self, *, user_message: str, provider: str, model: str, thread_id: str | None = None, response_mode: str = "chat"):
            captured["response_mode"] = response_mode
            return SimpleNamespace(
                text="<think>I need to make sure this is right.</think>\nThe user said hello.\nHello there.",
                retrieved=tuple(),
                sources=tuple(),
                verification_level=None,
                verification=None,
                tool_results=tuple(),
            )

    monkeypatch.setattr("sol_api.routes.chat._read_settings", lambda: SettingsModel(chatProvider="ollama", chatModel="llama3.2", ollamaBaseUrl="http://127.0.0.1:11434"))
    monkeypatch.setattr("sol_api.routes.chat._get_agent_pair", lambda thread_id, user="unknown": (_FakeHandle(), _FakeAgent()))
    response = chat(ChatRequest(message="hi", thread_id="thread-1", response_mode="spoken"), SimpleNamespace(headers={}, client=None))
    assert captured["response_mode"] == "spoken"
    assert response.content == "Hello there."


def test_save_settings_normalizes_ollama_url(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr("sol_api.routes.settings.config.settings_path", settings_path)
    saved = save_settings(SettingsModel(chatProvider="ollama", chatModel="llama3.2", ollamaBaseUrl="10.0.0.44:11434/"))
    assert saved.ollamaBaseUrl == "http://10.0.0.44:11434"
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert raw["ollamaBaseUrl"] == "http://10.0.0.44:11434"


def test_effective_ollama_request_timeout_uses_settings_override() -> None:
    settings = SettingsModel(ollamaRequestTimeoutS=120)
    assert effective_ollama_request_timeout_s(settings) == 120
    assert effective_ollama_request_timeout_s(SettingsModel(ollamaRequestTimeoutS=1)) == 5


def test_save_settings_persists_customization_fields(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr("sol_api.routes.settings.config.settings_path", settings_path)
    saved = save_settings(
        SettingsModel(
            assistantDisplayName="Orion",
            userDisplayName="Alex",
            ollamaRequestTimeoutS=75,
            appearancePreset="midnight",
            accentIntensity="vivid",
            densityMode="compact",
            layout={
                "showSidebar": False,
                "showInspector": True,
                "showHeader": True,
                "showCodeCanvas": False,
            },
        )
    )
    assert saved.assistantDisplayName == "Orion"
    assert saved.userDisplayName == "Alex"
    assert saved.ollamaRequestTimeoutS == 75
    assert saved.appearancePreset == "midnight"
    assert saved.accentIntensity == "vivid"
    assert saved.densityMode == "compact"
    assert saved.layout.showSidebar is False
    assert saved.layout.showInspector is True
    assert saved.layout.showHeader is True
    assert saved.layout.showCodeCanvas is False
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert raw["assistantDisplayName"] == "Orion"
    assert raw["userDisplayName"] == "Alex"
    assert raw["ollamaRequestTimeoutS"] == 75
    assert raw["appearancePreset"] == "midnight"
    assert raw["accentIntensity"] == "vivid"
    assert raw["densityMode"] == "compact"
    assert raw["layout"]["showSidebar"] is False
    assert raw["layout"]["showInspector"] is True
    assert raw["layout"]["showHeader"] is True
    assert raw["layout"]["showCodeCanvas"] is False
