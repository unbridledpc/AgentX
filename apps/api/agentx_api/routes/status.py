from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from agentx_api.config import config
from agentx_api.ollama import fetch_ollama_models
from agentx_api.routes.settings import _read_settings, effective_collaborative_ollama_routes, effective_ollama_base_url

router = APIRouter(tags=["status"])

_MODEL_CACHE: Dict[str, List[str]] = {"openai": [], "ollama": [], "ollama_fast": [], "ollama_heavy": []}
_ENDPOINT_STATUS: Dict[str, dict] = {}
_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_LAST_REFRESH: float | None = None
_MODEL_REFRESHING = False
_MODEL_LAST_ERROR: str | None = None


def _fetch_openai_models() -> List[str]:
    if not config.openai_api_key:
        return []
    url = f"{config.openai_base_url.rstrip('/')}/v1/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {config.openai_api_key}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=config.openai_timeout_s) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    ids = [m.get("id", "") for m in data.get("data", [])]
    # Keep chat-capable-ish models; avoid embeddings/audio/etc in the dropdown.
    def keep(model_id: str) -> bool:
        mid = model_id.lower()
        if not mid:
            return False
        if any(x in mid for x in ("embedding", "whisper", "tts", "dall-e", "moderation", "realtime", "audio")):
            return False
        return mid.startswith(("gpt-", "o1", "o3", "o4")) or "gpt" in mid

    filtered = sorted({m for m in ids if keep(m)})
    return filtered


def _refresh_models_worker() -> None:
    global _MODEL_CACHE, _ENDPOINT_STATUS, _MODEL_LAST_REFRESH, _MODEL_REFRESHING, _MODEL_LAST_ERROR
    try:
        openai_models: List[str] = []
        ollama_models: List[str] = []
        errors: List[str] = []
        settings = _read_settings()
        ollama_base_url = effective_ollama_base_url(settings)
        routes = effective_collaborative_ollama_routes(settings)

        try:
            openai_models = _fetch_openai_models()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            errors.append(f"openai HTTP {e.code}: {body}")
        except Exception as e:
            errors.append(f"openai: {e}")

        endpoint_status: Dict[str, dict] = {}
        endpoint_models: Dict[str, List[str]] = {}
        endpoints = {
            "default": ollama_base_url,
            "fast": str(routes.get("fast_base_url") or ollama_base_url),
            "heavy": str(routes.get("heavy_base_url") or ollama_base_url),
        }
        for key, url in endpoints.items():
            result = fetch_ollama_models(base_url=url, timeout_s=config.ollama_timeout_s)
            endpoint_models[key] = result.models
            endpoint_status[key] = {
                "base_url": result.base_url,
                "reachable": result.reachable,
                "error": result.error,
                "error_type": result.error_type,
                "models": result.models,
                "gpu_pin": routes.get("fast_gpu_pin") if key == "fast" else routes.get("heavy_gpu_pin") if key == "heavy" else None,
            }
            if key == "default":
                ollama_models = result.models
            if result.error:
                errors.append(f"ollama {key}: {result.error}")

        merged_ollama = sorted(set(endpoint_models.get("default", []) + endpoint_models.get("fast", []) + endpoint_models.get("heavy", [])))

        with _MODEL_CACHE_LOCK:
            _MODEL_CACHE = {
                "openai": openai_models,
                "ollama": merged_ollama,
                "ollama_fast": endpoint_models.get("fast", []),
                "ollama_heavy": endpoint_models.get("heavy", []),
            }
            _ENDPOINT_STATUS = endpoint_status
            _MODEL_LAST_REFRESH = time.time()
            _MODEL_LAST_ERROR = "; ".join(errors) if errors else None
            _MODEL_REFRESHING = False
    except Exception as e:
        with _MODEL_CACHE_LOCK:
            _MODEL_LAST_REFRESH = time.time()
            _MODEL_LAST_ERROR = f"model refresh failed: {e}"
            _MODEL_REFRESHING = False


def _ensure_model_cache(force: bool = False) -> None:
    global _MODEL_REFRESHING
    now = time.time()
    with _MODEL_CACHE_LOCK:
        last = _MODEL_LAST_REFRESH
        refreshing = _MODEL_REFRESHING
    if refreshing:
        return
    if not force and last is not None and (now - last) < config.model_list_ttl_s:
        return
    with _MODEL_CACHE_LOCK:
        if _MODEL_REFRESHING:
            return
        _MODEL_REFRESHING = True
    threading.Thread(target=_refresh_models_worker, daemon=True).start()


class StatusResponse(BaseModel):
    ok: bool = True
    name: str = "AgentX API"
    ts: float
    auth_enabled: bool
    chat_provider: str
    chat_model: str
    chat_ready: bool
    chat_error: str | None = None
    available_chat_models: Dict[str, List[str]]
    ollama_base_url: str
    ollama_endpoints: Dict[str, dict] = {}
    models_last_refresh: float | None = None
    models_refreshing: bool
    models_error: str | None = None
    provider_endpoint_status: str | None = None
    provider_model_status: str | None = None
    provider_error_type: str | None = None
    provider_error_message: str | None = None


@router.get("/status", response_model=StatusResponse)
def status(refresh: bool = Query(False)) -> StatusResponse:
    _ensure_model_cache(force=refresh)

    settings = _read_settings()
    ollama_base_url = effective_ollama_base_url(settings)
    provider = (getattr(settings, "chatProvider", None) or ("openai" if config.openai_api_key else "stub")).strip().lower()
    model = (getattr(settings, "chatModel", None) or (config.openai_model if config.openai_api_key else "stub")).strip()

    with _MODEL_CACHE_LOCK:
        models = dict(_MODEL_CACHE)
        last_refresh = _MODEL_LAST_REFRESH
        refreshing = _MODEL_REFRESHING
        last_error = _MODEL_LAST_ERROR
        endpoint_status = dict(_ENDPOINT_STATUS)

    chat_ready = True
    chat_error: str | None = None
    provider_endpoint_status: str | None = None
    provider_model_status: str | None = None
    provider_error_type: str | None = None
    provider_error_message: str | None = None
    if provider == "openai" and not config.openai_api_key:
        chat_ready = False
        chat_error = "OpenAI selected but AGENTX_OPENAI_API_KEY is not set."
    if provider == "ollama" and (not model or model == "stub"):
        chat_ready = False
        chat_error = "Ollama selected but no model is configured."
    if provider == "ollama":
        ollama_models = list(models.get("ollama") or [])
        if last_error and "Configured Ollama endpoint" in last_error:
            chat_ready = False
            chat_error = last_error
            provider_endpoint_status = "unreachable"
            provider_model_status = "unknown"
            provider_error_message = last_error
            provider_error_type = "provider_unreachable" if "could not be reached" in last_error else "provider_http_error"
        else:
            provider_endpoint_status = "reachable"
            if not model or model == "stub":
                provider_model_status = "unconfigured"
                provider_error_type = "provider_misconfigured"
                provider_error_message = chat_error
            elif model in ollama_models:
                provider_model_status = "available"
            else:
                provider_model_status = "missing"
                provider_error_type = "model_unavailable"
                provider_error_message = f"Model `{model}` is not available on the configured Ollama server."
                chat_ready = False
                chat_error = provider_error_message

    if chat_error is None and last_error:
        # Non-fatal: discovery can fail while chat still works (e.g. OpenAI list blocked).
        chat_error = None

    return StatusResponse(
        ts=time.time(),
        auth_enabled=bool(config.auth_enabled),
        chat_provider=provider,
        chat_model=model,
        chat_ready=chat_ready,
        chat_error=chat_error,
        available_chat_models=models,
        ollama_base_url=ollama_base_url,
        ollama_endpoints=endpoint_status,
        models_last_refresh=last_refresh,
        models_refreshing=refreshing,
        models_error=last_error,
        provider_endpoint_status=provider_endpoint_status,
        provider_model_status=provider_model_status,
        provider_error_type=provider_error_type,
        provider_error_message=provider_error_message,
    )
