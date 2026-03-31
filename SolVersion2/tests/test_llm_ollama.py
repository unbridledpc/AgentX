from __future__ import annotations

import io
import socket
import urllib.error

import pytest

from sol.core.llm import OllamaConfig, ProviderError, load_ollama_cfg, ollama_generate


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_load_ollama_cfg_normalizes_custom_base_url() -> None:
    cfg = load_ollama_cfg({"ollama": {"base_url": "10.0.0.44:11434/"}})
    assert cfg.base_url == "http://10.0.0.44:11434"


def test_ollama_generate_uses_normalized_base_url(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        return _FakeResponse(b'{"response":"ok"}')

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    result = ollama_generate(cfg=OllamaConfig(base_url="10.0.0.44:11434/", model="llama3.2", timeout_s=1.0, max_tool_iters=4), prompt="hello")
    assert result == "ok"
    assert captured["url"] == "http://10.0.0.44:11434/api/generate"


def test_ollama_generate_reports_http_error_with_category(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url,
            404,
            "not found",
            hdrs=None,
            fp=io.BytesIO(b"missing route"),
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(ProviderError) as excinfo:
        ollama_generate(cfg=OllamaConfig(base_url="10.0.0.44:11434", model="llama3.2", timeout_s=1.0, max_tool_iters=4), prompt="hello")
    assert excinfo.value.category == "provider_http_error"
    assert excinfo.value.base_url == "http://10.0.0.44:11434"


def test_ollama_generate_reports_timeout(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(ProviderError) as excinfo:
        ollama_generate(cfg=OllamaConfig(base_url="10.0.0.44:11434", model="qwen3.5:9b", timeout_s=30.0, max_tool_iters=4), prompt="hello")
    assert excinfo.value.category == "provider_timeout"
    assert "timed out" in excinfo.value.message.lower()


def test_ollama_generate_reports_model_unavailable(monkeypatch) -> None:
    def _fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url,
            404,
            "not found",
            hdrs=None,
            fp=io.BytesIO(b'model "qwen3.5:9b" not found, try pulling it first'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    with pytest.raises(ProviderError) as excinfo:
        ollama_generate(cfg=OllamaConfig(base_url="10.0.0.44:11434", model="qwen3.5:9b", timeout_s=30.0, max_tool_iters=4), prompt="hello")
    assert excinfo.value.category == "model_unavailable"
    assert excinfo.value.model == "qwen3.5:9b"
