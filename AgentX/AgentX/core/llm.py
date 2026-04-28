from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


def _env(name: str) -> str | None:
    value = os.getenv(name)
    if value is not None:
        return value
    if name.startswith("AGENTX_"):
        suffix = name.removeprefix("AGENTX_")
        for legacy_name in (f"SOL_{suffix}", f"NEXAI_{suffix}"):
            legacy_value = os.getenv(legacy_name)
            if legacy_value is not None:
                return legacy_value
    return None


class LlmError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderError(LlmError):
    category: str
    provider: str
    message: str
    model: str | None = None
    base_url: str | None = None
    detail: str | None = None
    status_code: int | None = None
    timeout_s: float | None = None

    def __str__(self) -> str:
        return self.message


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class OpenAiConfig:
    api_key: str | None
    base_url: str
    model: str
    timeout_s: float
    max_tool_iters: int


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout_s: float
    max_tool_iters: int


def provider_error_detail(exc: BaseException) -> dict[str, Any] | None:
    if not isinstance(exc, ProviderError):
        return None
    detail: dict[str, Any] = {
        "type": exc.category,
        "provider": exc.provider,
        "message": exc.message,
    }
    if exc.model:
        detail["model"] = exc.model
    if exc.base_url:
        detail["base_url"] = exc.base_url
    if exc.status_code is not None:
        detail["status_code"] = exc.status_code
    if exc.timeout_s is not None:
        detail["timeout_s"] = exc.timeout_s
    if exc.detail:
        detail["detail"] = exc.detail
    return detail


def _decode_http_error_body(exc: urllib.error.HTTPError) -> str:
    if not getattr(exc, "fp", None):
        return ""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _looks_like_missing_model(body: str, *, model: str) -> bool:
    text = (body or "").lower()
    model_text = (model or "").strip().lower()
    if not text:
        return False
    if "model" in text and any(token in text for token in ("not found", "no such", "missing", "unavailable", "pull")):
        return True
    if model_text and model_text in text and any(token in text for token in ("not found", "missing", "unavailable")):
        return True
    return False


def _raise_provider_error(
    *,
    category: str,
    provider: str,
    message: str,
    model: str | None = None,
    base_url: str | None = None,
    detail: str | None = None,
    status_code: int | None = None,
    timeout_s: float | None = None,
) -> None:
    raise ProviderError(
        category=category,
        provider=provider,
        message=message,
        model=model,
        base_url=base_url,
        detail=detail,
        status_code=status_code,
        timeout_s=timeout_s,
    )


def normalize_ollama_base_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_OLLAMA_BASE_URL
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urllib.parse.urlparse(raw)
    scheme = parsed.scheme or "http"
    host = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    normalized = urllib.parse.urlunparse((scheme, host, path.rstrip("/"), "", "", ""))
    return normalized.rstrip("/") or DEFAULT_OLLAMA_BASE_URL


def load_openai_cfg(llm_cfg: dict[str, Any]) -> OpenAiConfig:
    d = llm_cfg.get("openai") if isinstance(llm_cfg.get("openai"), dict) else {}
    api_key_env = str(d.get("api_key_env") or "AGENTX_OPENAI_API_KEY")
    api_key = _env(api_key_env) or None
    return OpenAiConfig(
        api_key=api_key,
        base_url=str(d.get("base_url") or "https://api.openai.com"),
        model=str(d.get("model") or "gpt-4o-mini"),
        timeout_s=float(d.get("timeout_s") or 20),
        max_tool_iters=int(d.get("max_tool_iters") or 4),
    )


def load_ollama_cfg(llm_cfg: dict[str, Any]) -> OllamaConfig:
    d = llm_cfg.get("ollama") if isinstance(llm_cfg.get("ollama"), dict) else {}
    return OllamaConfig(
        base_url=normalize_ollama_base_url(str(d.get("base_url") or DEFAULT_OLLAMA_BASE_URL)),
        model=str(d.get("model") or "llama3.2"),
        timeout_s=float(d.get("timeout_s") or 30),
        max_tool_iters=int(d.get("max_tool_iters") or 4),
    )


def openai_chat_completions(
    *,
    cfg: OpenAiConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not cfg.api_key:
        _raise_provider_error(
            category="provider_misconfigured",
            provider="openai",
            message="OpenAI is selected but no API key is configured.",
            model=cfg.model,
            base_url=cfg.base_url,
        )

    url = f"{cfg.base_url.rstrip('/')}/v1/chat/completions"
    payload: dict[str, Any] = {"model": cfg.model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = _decode_http_error_body(e)
        _raise_provider_error(
            category="provider_http_error",
            provider="openai",
            message=f"OpenAI returned HTTP {e.code}.",
            model=cfg.model,
            base_url=cfg.base_url,
            detail=body[:4000] or str(e),
            status_code=e.code,
        )
    except TimeoutError as e:
        _raise_provider_error(
            category="provider_timeout",
            provider="openai",
            message=f"OpenAI request timed out after {int(cfg.timeout_s)}s.",
            model=cfg.model,
            base_url=cfg.base_url,
            detail=str(e),
            timeout_s=cfg.timeout_s,
        )
    except urllib.error.URLError as e:
        _raise_provider_error(
            category="provider_unreachable",
            provider="openai",
            message=f"OpenAI is unreachable at {cfg.base_url}.",
            model=cfg.model,
            base_url=cfg.base_url,
            detail=str(getattr(e, 'reason', e)),
        )
    except Exception as e:
        _raise_provider_error(
            category="unknown_provider_error",
            provider="openai",
            message="OpenAI request failed.",
            model=cfg.model,
            base_url=cfg.base_url,
            detail=str(e),
        )


def ollama_generate(*, cfg: OllamaConfig, prompt: str) -> str:
    base_url = normalize_ollama_base_url(cfg.base_url)
    model = (cfg.model or "").strip()
    if not model or model == "stub":
        _raise_provider_error(
            category="provider_misconfigured",
            provider="ollama",
            message="Ollama is selected but no model is configured.",
            model=model or None,
            base_url=base_url,
        )
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            _raise_provider_error(
                category="unknown_provider_error",
                provider="ollama",
                message="Ollama returned a malformed response.",
                model=model,
                base_url=base_url,
                detail=f"Expected JSON object, received {type(data).__name__}.",
            )
        if data.get("error"):
            error_text = str(data.get("error") or "").strip()
            if _looks_like_missing_model(error_text, model=model):
                _raise_provider_error(
                    category="model_unavailable",
                    provider="ollama",
                    message=f"Model `{model}` is not available on the configured Ollama instance.",
                    model=model,
                    base_url=base_url,
                    detail=error_text,
                )
            _raise_provider_error(
                category="provider_http_error",
                provider="ollama",
                message=f"Ollama returned an error for model `{model}`.",
                model=model,
                base_url=base_url,
                detail=error_text,
            )
        return str(data.get("response") or "")
    except urllib.error.HTTPError as e:
        body = _decode_http_error_body(e)
        if _looks_like_missing_model(body, model=model):
            _raise_provider_error(
                category="model_unavailable",
                provider="ollama",
                message=f"Model `{model}` is not available on the configured Ollama instance.",
                model=model,
                base_url=base_url,
                detail=body[:4000] or str(e),
                status_code=e.code,
            )
        _raise_provider_error(
            category="provider_http_error",
            provider="ollama",
            message=f"Ollama returned HTTP {e.code} from {base_url}.",
            model=model,
            base_url=base_url,
            detail=body[:4000] or str(e),
            status_code=e.code,
        )
    except (TimeoutError, socket.timeout) as e:
        _raise_provider_error(
                category="provider_timeout",
                provider="ollama",
                message=f"Ollama request timed out after {int(cfg.timeout_s)}s.",
                model=model,
                base_url=base_url,
                detail=str(e),
                timeout_s=cfg.timeout_s,
            )
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            _raise_provider_error(
                category="provider_timeout",
                provider="ollama",
                message=f"Ollama request timed out after {int(cfg.timeout_s)}s.",
                model=model,
                base_url=base_url,
                detail=str(reason),
                timeout_s=cfg.timeout_s,
            )
        _raise_provider_error(
            category="provider_unreachable",
            provider="ollama",
            message=f"Ollama is unreachable at {base_url}.",
            model=model,
            base_url=base_url,
            detail=str(reason),
        )
    except json.JSONDecodeError as e:
        _raise_provider_error(
            category="unknown_provider_error",
            provider="ollama",
            message="Ollama returned a malformed response.",
            model=model,
            base_url=base_url,
            detail=str(e),
        )
    except Exception as e:
        _raise_provider_error(
            category="unknown_provider_error",
            provider="ollama",
            message=f"Ollama request failed for model `{model}`.",
            model=model,
            base_url=base_url,
            detail=str(e),
        )


def ollama_generate_stream(*, cfg: OllamaConfig, prompt: str) -> Iterator[str]:
    """Yield text chunks from Ollama's streaming /api/generate endpoint."""
    base_url = normalize_ollama_base_url(cfg.base_url)
    model = (cfg.model or "").strip()
    if not model or model == "stub":
        _raise_provider_error(
            category="provider_misconfigured",
            provider="ollama",
            message="Ollama is selected but no model is configured.",
            model=model or None,
            base_url=base_url,
        )
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": True}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            for raw_line in resp:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("error"):
                    error_text = str(data.get("error") or "").strip()
                    if _looks_like_missing_model(error_text, model=model):
                        _raise_provider_error(
                            category="model_unavailable",
                            provider="ollama",
                            message=f"Model `{model}` is not available on the configured Ollama instance.",
                            model=model,
                            base_url=base_url,
                            detail=error_text,
                        )
                    _raise_provider_error(
                        category="provider_http_error",
                        provider="ollama",
                        message=f"Ollama returned an error for model `{model}`.",
                        model=model,
                        base_url=base_url,
                        detail=error_text,
                    )
                chunk = data.get("response")
                if isinstance(chunk, str) and chunk:
                    yield chunk
                if data.get("done"):
                    break
    except urllib.error.HTTPError as e:
        body = _decode_http_error_body(e)
        if _looks_like_missing_model(body, model=model):
            _raise_provider_error(
                category="model_unavailable",
                provider="ollama",
                message=f"Model `{model}` is not available on the configured Ollama instance.",
                model=model,
                base_url=base_url,
                detail=body[:4000] or str(e),
                status_code=e.code,
            )
        _raise_provider_error(
            category="provider_http_error",
            provider="ollama",
            message=f"Ollama returned HTTP {e.code} from {base_url}.",
            model=model,
            base_url=base_url,
            detail=body[:4000] or str(e),
            status_code=e.code,
        )
    except (TimeoutError, socket.timeout) as e:
        _raise_provider_error(
            category="provider_timeout",
            provider="ollama",
            message=f"Ollama request timed out after {int(cfg.timeout_s)}s.",
            model=model,
            base_url=base_url,
            detail=str(e),
            timeout_s=cfg.timeout_s,
        )
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            _raise_provider_error(
                category="provider_timeout",
                provider="ollama",
                message=f"Ollama request timed out after {int(cfg.timeout_s)}s.",
                model=model,
                base_url=base_url,
                detail=str(reason),
                timeout_s=cfg.timeout_s,
            )
        _raise_provider_error(
            category="provider_unreachable",
            provider="ollama",
            message=f"Ollama is unreachable at {base_url}.",
            model=model,
            base_url=base_url,
            detail=str(reason),
        )
    except ProviderError:
        raise
    except Exception as e:
        _raise_provider_error(
            category="unknown_provider_error",
            provider="ollama",
            message=f"Ollama request failed for model `{model}`.",
            model=model,
            base_url=base_url,
            detail=str(e),
        )
