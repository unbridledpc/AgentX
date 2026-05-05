from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agentx_api.config import config
from agentx_api.ollama import normalize_ollama_base_url
from agentx_api.routes.settings import _read_settings, effective_collaborative_ollama_routes, effective_ollama_base_url

router = APIRouter(tags=["model-ops"])

_BENCH_HISTORY_PATH = config.settings_path.parent / "model_ops_benchmarks.jsonl"
_BENCH_HISTORY_MAX_ROWS = 500


def _endpoint_url(endpoint: str | None) -> str:
    settings = _read_settings()
    key = (endpoint or "default").strip().lower()
    routes = effective_collaborative_ollama_routes(settings)
    if key == "fast":
        return normalize_ollama_base_url(str(routes.get("fast_base_url") or effective_ollama_base_url(settings)))
    if key == "heavy":
        return normalize_ollama_base_url(str(routes.get("heavy_base_url") or effective_ollama_base_url(settings)))
    return effective_ollama_base_url(settings)


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _get_json(url: str, *, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _ollama_http_error(exc: Exception, base_url: str) -> HTTPException:
    if isinstance(exc, urllib.error.HTTPError):
        body = exc.read().decode("utf-8", errors="replace") if getattr(exc, "fp", None) else ""
        return HTTPException(status_code=502, detail=f"Ollama HTTP {exc.code} from {base_url}: {body[:500]}")
    if isinstance(exc, urllib.error.URLError):
        return HTTPException(status_code=502, detail=f"Ollama endpoint unreachable at {base_url}: {exc.reason}")
    return HTTPException(status_code=502, detail=f"Ollama request failed at {base_url}: {exc}")


class OllamaPsRequest(BaseModel):
    endpoint: str = "default"


class OllamaBenchRequest(BaseModel):
    endpoint: str = "default"
    model: str = Field(..., min_length=1)
    prompt: str = "Say READY in one short sentence."
    num_predict: int = Field(64, ge=1, le=2048)
    num_ctx: int | None = Field(None, ge=512, le=262144)
    temperature: float = Field(0.1, ge=0.0, le=2.0)


class OllamaCompareRequest(BaseModel):
    model: str = Field(..., min_length=1)
    endpoints: list[str] = Field(default_factory=lambda: ["fast", "heavy"])
    prompt: str = "Say READY and one short sentence about your role in AgentX."
    num_predict: int = Field(64, ge=1, le=2048)
    num_ctx: int | None = Field(None, ge=512, le=262144)
    temperature: float = Field(0.1, ge=0.0, le=2.0)


class ContextBudgetRequest(BaseModel):
    model: str | None = None
    message: str = ""
    attachment_chars: int = 0
    tool_context_chars: int = 4800
    system_context_chars: int = 5200
    target_context_tokens: int | None = Field(None, ge=512, le=262144)


def _token_estimate(chars: int) -> int:
    # Conservative English/code estimate. Good enough for warning users before send.
    return max(0, int((max(0, chars) + 3) / 4))


def _guess_context_tokens(model: str | None, requested: int | None) -> int:
    if requested:
        return int(requested)
    name = (model or "").lower()
    if any(x in name for x in ("128k", "131k", "120k")):
        return 128000
    if any(x in name for x in ("64k", "65536")):
        return 64000
    if any(x in name for x in ("32k", "32768")):
        return 32000
    if any(x in name for x in ("16k", "16384")):
        return 16000
    if any(x in name for x in ("8k", "8192")):
        return 8000
    return 4096


def _model_role_hint(model: str | None) -> str:
    name = (model or "").lower()
    if any(x in name for x in ("coder", "code", "devstral", "deepseek-coder", "dolphin")):
        return "coding"
    if any(x in name for x in ("vision", "llava", "moondream")):
        return "vision"
    if any(x in name for x in ("glm", "kimi", "qwen", "mistral", "mixtral", "deepseek")):
        return "reasoning"
    return "chat"


def _context_profile(model: str | None, requested: int | None = None) -> dict[str, Any]:
    target = _guess_context_tokens(model, requested)
    role = _model_role_hint(model)
    if target >= 64000:
        tier = "long"
        advice = "Good for large codebase analysis, logs, and multi-file repair. Still prefer focused attachments."
    elif target >= 16000:
        tier = "medium"
        advice = "Good for normal coding tasks and several attached files. Summarize huge logs before sending."
    elif target >= 8000:
        tier = "short-medium"
        advice = "Usable for focused chat and small patches. Avoid dumping large files."
    else:
        tier = "short"
        advice = "Keep prompts tight. For coding harness work, route to a larger-context model when possible."
    return {
        "model": model,
        "target_context_tokens": target,
        "context_tier": tier,
        "role_hint": role,
        "advice": advice,
    }


def _run_ollama_bench(body: OllamaBenchRequest) -> dict[str, Any]:
    base_url = _endpoint_url(body.endpoint)
    payload: dict[str, Any] = {
        "model": body.model,
        "prompt": body.prompt,
        "stream": False,
        "options": {
            "num_predict": body.num_predict,
            "temperature": body.temperature,
        },
    }
    if body.num_ctx:
        payload["options"]["num_ctx"] = body.num_ctx

    started = time.perf_counter()
    data = _post_json(f"{base_url.rstrip('/')}/api/generate", payload, timeout_s=max(config.ollama_request_timeout_s, 30.0))
    total_ms = (time.perf_counter() - started) * 1000

    eval_count = int(data.get("eval_count") or 0)
    prompt_eval_count = int(data.get("prompt_eval_count") or 0)
    eval_duration_ns = int(data.get("eval_duration") or 0)
    prompt_eval_duration_ns = int(data.get("prompt_eval_duration") or 0)
    load_duration_ns = int(data.get("load_duration") or 0)
    tps = (eval_count / (eval_duration_ns / 1_000_000_000)) if eval_count and eval_duration_ns else None
    prompt_tps = (prompt_eval_count / (prompt_eval_duration_ns / 1_000_000_000)) if prompt_eval_count and prompt_eval_duration_ns else None

    return {
        "ok": True,
        "ts": time.time(),
        "endpoint": body.endpoint,
        "base_url": base_url,
        "model": body.model,
        "total_ms": round(total_ms, 2),
        "load_ms": round(load_duration_ns / 1_000_000, 2) if load_duration_ns else None,
        "prompt_eval_ms": round(prompt_eval_duration_ns / 1_000_000, 2) if prompt_eval_duration_ns else None,
        "eval_ms": round(eval_duration_ns / 1_000_000, 2) if eval_duration_ns else None,
        "prompt_tokens": prompt_eval_count or None,
        "output_tokens": eval_count or None,
        "tokens_per_second": round(tps, 2) if tps else None,
        "prompt_tokens_per_second": round(prompt_tps, 2) if prompt_tps else None,
        "response_preview": str(data.get("response") or "")[:500],
        "raw_done_reason": data.get("done_reason"),
        "num_predict": body.num_predict,
        "num_ctx": body.num_ctx,
    }


def _read_bench_history(limit: int = 50) -> list[dict[str, Any]]:
    if not _BENCH_HISTORY_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with _BENCH_HISTORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except Exception:
        return []
    rows = rows[-max(1, min(limit, _BENCH_HISTORY_MAX_ROWS)) :]
    rows.reverse()
    return rows


def _append_bench_history(row: dict[str, Any]) -> None:
    try:
        _BENCH_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_bench_history(_BENCH_HISTORY_MAX_ROWS)
        existing.reverse()
        existing.append(row)
        existing = existing[-_BENCH_HISTORY_MAX_ROWS:]
        tmp = _BENCH_HISTORY_PATH.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for item in existing:
                f.write(json.dumps(item, sort_keys=True) + "\n")
        tmp.replace(_BENCH_HISTORY_PATH)
    except Exception:
        # Benchmarks should never fail the main request because history failed to write.
        return


@router.post("/model-ops/ollama/ps")
def ollama_ps(body: OllamaPsRequest) -> dict[str, Any]:
    base_url = _endpoint_url(body.endpoint)
    started = time.perf_counter()
    try:
        data = _get_json(f"{base_url.rstrip('/')}/api/ps", timeout_s=config.ollama_timeout_s)
    except Exception as exc:
        raise _ollama_http_error(exc, base_url)
    return {
        "ok": True,
        "endpoint": body.endpoint,
        "base_url": base_url,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "models": data.get("models", []),
        "raw": data,
    }


@router.post("/model-ops/ollama/bench")
def ollama_bench(body: OllamaBenchRequest) -> dict[str, Any]:
    base_url = _endpoint_url(body.endpoint)
    try:
        result = _run_ollama_bench(body)
    except Exception as exc:
        raise _ollama_http_error(exc, base_url)
    _append_bench_history(result)
    return result


@router.post("/model-ops/ollama/compare")
def ollama_compare(body: OllamaCompareRequest) -> dict[str, Any]:
    endpoints = []
    seen: set[str] = set()
    for endpoint in body.endpoints:
        key = (endpoint or "default").strip().lower()
        if key and key not in seen:
            seen.add(key)
            endpoints.append(key)
    if not endpoints:
        endpoints = ["fast", "heavy"]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for endpoint in endpoints:
        bench_body = OllamaBenchRequest(
            endpoint=endpoint,
            model=body.model,
            prompt=body.prompt,
            num_predict=body.num_predict,
            num_ctx=body.num_ctx,
            temperature=body.temperature,
        )
        base_url = _endpoint_url(endpoint)
        try:
            result = _run_ollama_bench(bench_body)
            result["compare_run"] = True
            _append_bench_history(result)
            results.append(result)
        except Exception as exc:
            err = _ollama_http_error(exc, base_url)
            errors.append({"endpoint": endpoint, "base_url": base_url, "error": str(err.detail)})

    best = None
    usable = [r for r in results if isinstance(r.get("tokens_per_second"), (int, float))]
    if usable:
        best = max(usable, key=lambda r: float(r.get("tokens_per_second") or 0))

    return {
        "ok": len(results) > 0,
        "model": body.model,
        "results": results,
        "errors": errors,
        "best_endpoint": best.get("endpoint") if best else None,
        "best_tokens_per_second": best.get("tokens_per_second") if best else None,
    }


@router.get("/model-ops/bench/history")
def bench_history(limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
    rows = _read_bench_history(limit)
    return {"ok": True, "path": str(_BENCH_HISTORY_PATH), "history": rows}


@router.post("/model-ops/context-budget")
def context_budget(body: ContextBudgetRequest) -> dict[str, Any]:
    message_chars = len(body.message or "")
    attachment_chars = max(0, int(body.attachment_chars or 0))
    tool_chars = max(0, int(body.tool_context_chars or 0))
    system_chars = max(0, int(body.system_context_chars or 0))
    total_chars = message_chars + attachment_chars + tool_chars + system_chars
    profile = _context_profile(body.model, body.target_context_tokens)
    target = int(profile["target_context_tokens"])
    used = _token_estimate(total_chars)
    remaining = max(0, target - used)
    pct = round((used / target) * 100, 1) if target else 0.0
    if pct >= 95:
        risk = "critical"
    elif pct >= 80:
        risk = "high"
    elif pct >= 60:
        risk = "medium"
    else:
        risk = "low"
    return {
        "ok": True,
        "model": body.model,
        "target_context_tokens": target,
        "estimated_used_tokens": used,
        "estimated_remaining_tokens": remaining,
        "estimated_used_pct": pct,
        "risk": risk,
        "breakdown": {
            "system_tokens": _token_estimate(system_chars),
            "tool_tokens": _token_estimate(tool_chars),
            "message_tokens": _token_estimate(message_chars),
            "attachment_tokens": _token_estimate(attachment_chars),
        },
        "profile": profile,
        "note": "Estimates use chars/4. Confirm loaded context with Ollama ps when a model is running.",
    }
