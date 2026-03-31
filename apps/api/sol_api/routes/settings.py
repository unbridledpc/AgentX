from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from sol_api.config import config
from sol_api.ollama import normalize_ollama_base_url

router = APIRouter(tags=["settings"])


class LayoutSettingsModel(BaseModel):
    showSidebar: bool = True
    showInspector: bool = True
    showHeader: bool = True
    showCodeCanvas: bool = True


class SettingsModel(BaseModel):
    showInspector: bool = False
    inspectorWindow: bool = False
    theme: str = "win11-light"
    chatProvider: str = "openai" if config.openai_api_key else "stub"
    chatModel: str = config.openai_model if config.openai_api_key else "stub"
    ollamaBaseUrl: str = config.ollama_base_url
    ollamaRequestTimeoutS: float = 60.0
    assistantDisplayName: str = "Nexus"
    userDisplayName: str = "You"
    appearancePreset: str = "nexus"
    accentIntensity: str = "balanced"
    densityMode: str = "comfortable"
    layout: LayoutSettingsModel = LayoutSettingsModel()


def effective_ollama_base_url(settings: SettingsModel | None = None) -> str:
    chosen = settings or _read_settings()
    return normalize_ollama_base_url(getattr(chosen, "ollamaBaseUrl", "") or config.ollama_base_url)


def effective_ollama_request_timeout_s(settings: SettingsModel | None = None) -> float:
    chosen = settings or _read_settings()
    raw = getattr(chosen, "ollamaRequestTimeoutS", None)
    try:
        timeout_s = float(raw) if raw is not None else float(getattr(config, "ollama_request_timeout_s", 60.0))
    except (TypeError, ValueError):
        timeout_s = float(getattr(config, "ollama_request_timeout_s", 60.0))
    return max(5.0, timeout_s)

_CACHE_LOCK = threading.Lock()
_CACHED_SETTINGS: SettingsModel | None = None


def _read_settings() -> SettingsModel:
    global _CACHED_SETTINGS
    with _CACHE_LOCK:
        if _CACHED_SETTINGS is not None:
            return _CACHED_SETTINGS

    path = config.settings_path
    if not path.exists():
        settings = SettingsModel()
        with _CACHE_LOCK:
            _CACHED_SETTINGS = settings
        return settings
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        settings = SettingsModel(**data)
        with _CACHE_LOCK:
            _CACHED_SETTINGS = settings
        return settings
    except Exception:
        settings = SettingsModel()
        with _CACHE_LOCK:
            _CACHED_SETTINGS = settings
        return settings


def _write_settings(settings: SettingsModel) -> None:
    path = config.settings_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(settings.model_dump(), fh, indent=2)
    tmp.replace(path)


@router.get("/settings", response_model=SettingsModel)
def get_settings() -> SettingsModel:
    return _read_settings()


@router.post("/settings", response_model=SettingsModel)
def save_settings(settings: SettingsModel) -> SettingsModel:
    global _CACHED_SETTINGS
    if not getattr(settings, "ollamaBaseUrl", "").strip():
        settings = settings.model_copy(
            update={
                "ollamaBaseUrl": config.ollama_base_url,
                "ollamaRequestTimeoutS": effective_ollama_request_timeout_s(settings),
            }
        )
    else:
        settings = settings.model_copy(
            update={
                "ollamaBaseUrl": effective_ollama_base_url(settings),
                "ollamaRequestTimeoutS": effective_ollama_request_timeout_s(settings),
            }
        )
    _write_settings(settings)
    with _CACHE_LOCK:
        _CACHED_SETTINGS = settings
    return settings
