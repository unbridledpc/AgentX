from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from sol.install.platform import PlatformInfo


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class OllamaProbeResult:
    status: str
    message: str
    base_url: str
    models: tuple[str, ...] = ()
    model: str | None = None
    model_available: bool | None = None
    category: str | None = None
    detail: str | None = None


def is_full_ollama_url(value: str) -> bool:
    return "://" in (value or "").strip()


def build_ollama_base_url(*, host_or_url: str, port: str | int | None = None) -> str:
    raw = (host_or_url or "").strip()
    if not raw:
        raise ValueError("Ollama host or URL is required.")
    if is_full_ollama_url(raw):
        return normalize_ollama_base_url(raw)
    host = raw.strip().strip("/")
    if not host or any(ch.isspace() for ch in host) or host in {"http:", "https:"}:
        raise ValueError("Enter a valid Ollama host or IP, such as 127.0.0.1 or 192.168.68.50.")
    port_text = str(port or "11434").strip()
    if not port_text.isdigit():
        raise ValueError("Ollama port must be a number such as 11434.")
    port_num = int(port_text)
    if port_num <= 0 or port_num > 65535:
        raise ValueError("Ollama port must be between 1 and 65535.")
    return normalize_ollama_base_url(f"http://{host}:{port_num}")


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


def detect_wsl_nameserver_ip(resolv_conf: Path = Path("/etc/resolv.conf")) -> str | None:
    if not resolv_conf.exists():
        return None
    try:
        for line in resolv_conf.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text.startswith("nameserver "):
                continue
            _, _, value = text.partition(" ")
            candidate = value.strip()
            if candidate:
                return candidate
    except Exception:
        return None
    return None


def wsl_ollama_guidance(*, platform_info: PlatformInfo, base_url: str) -> tuple[str, ...]:
    if not platform_info.is_wsl:
        return ()
    lines = [
        "WSL detected. Ollama running on Windows may not be reachable from WSL via 127.0.0.1.",
        "If Ollama is running on Windows, try the Windows host IP or another reachable endpoint instead of WSL localhost.",
    ]
    nameserver_ip = detect_wsl_nameserver_ip()
    if nameserver_ip:
        parsed = urllib.parse.urlparse(base_url)
        host_port = parsed.netloc or parsed.path
        _, _, port = host_port.partition(":")
        lines.append(f"Try this likely Windows host endpoint from WSL: http://{nameserver_ip}:{port or '11434'}")
    return tuple(lines)


def probe_ollama_endpoint(base_url: str, *, timeout_s: float = 2.0) -> OllamaProbeResult:
    return probe_ollama_provider(base_url, timeout_s=timeout_s)


def probe_ollama_provider(base_url: str, *, model: str | None = None, timeout_s: float = 2.0) -> OllamaProbeResult:
    normalized = normalize_ollama_base_url(base_url)
    url = f"{normalized.rstrip('/')}/api/tags"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        models = tuple(sorted({str(m.get('name') or '').strip() for m in data.get("models", []) if str(m.get("name") or "").strip()}))
        requested_model = (model or "").strip() or None
        model_available = None if not requested_model else requested_model in models
        if models:
            if requested_model and not model_available:
                return OllamaProbeResult(
                    status="reachable",
                    message=f"Reachable, but model missing: {requested_model}.",
                    base_url=normalized,
                    models=models,
                    model=requested_model,
                    model_available=False,
                    category="model_unavailable",
                )
            return OllamaProbeResult(
                status="reachable",
                message=f"Reachable: {normalized} returned {len(models)} model(s).",
                base_url=normalized,
                models=models,
                model=requested_model,
                model_available=model_available,
                category="connected",
            )
        return OllamaProbeResult(
            status="reachable_no_models",
            message=f"Reachable, but {normalized} returned no models.",
            base_url=normalized,
            models=(),
            model=requested_model,
            model_available=False if requested_model else None,
            category="provider_misconfigured",
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if getattr(exc, "fp", None) else ""
        return OllamaProbeResult(
            status="unreachable",
            message=f"Configured Ollama endpoint could not be reached cleanly: HTTP {exc.code} from {normalized}. {body[:240]}".strip(),
            base_url=normalized,
            model=(model or "").strip() or None,
            model_available=None,
            category="provider_http_error",
            detail=body[:4000] or str(exc),
        )
    except Exception as exc:
        return OllamaProbeResult(
            status="unreachable",
            message=f"Configured Ollama endpoint could not be reached: {normalized} ({exc})",
            base_url=normalized,
            model=(model or "").strip() or None,
            model_available=None,
            category="provider_unreachable",
            detail=str(exc),
        )
