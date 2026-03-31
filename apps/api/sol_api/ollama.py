from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class OllamaDiscoveryResult:
    base_url: str
    models: list[str]
    error: str | None = None
    reachable: bool = False
    error_type: str | None = None


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


def fetch_ollama_models(*, base_url: str, timeout_s: float) -> OllamaDiscoveryResult:
    normalized = normalize_ollama_base_url(base_url)
    url = f"{normalized.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        models = sorted({str(m.get("name") or "").strip() for m in data.get("models", []) if str(m.get("name") or "").strip()})
        if models:
            return OllamaDiscoveryResult(base_url=normalized, models=models, error=None, reachable=True, error_type=None)
        return OllamaDiscoveryResult(
            base_url=normalized,
            models=[],
            error=f"Configured Ollama endpoint is reachable but returned no models: {normalized}",
            reachable=True,
            error_type="provider_misconfigured",
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if getattr(exc, "fp", None) else ""
        return OllamaDiscoveryResult(
            base_url=normalized,
            models=[],
            error=f"Configured Ollama endpoint could not be reached cleanly: HTTP {exc.code} from {normalized}. {body[:240]}".strip(),
            reachable=False,
            error_type="provider_http_error",
        )
    except Exception as exc:
        return OllamaDiscoveryResult(
            base_url=normalized,
            models=[],
            error=f"Configured Ollama endpoint could not be reached: {normalized} ({exc})",
            reachable=False,
            error_type="provider_unreachable",
        )
