from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sol.core.agent import Agent, AgentPolicyError


@dataclass(frozen=True)
class CliRunResult:
    ok: bool
    text: str
    exit_code: int


def interactive_run(agent: Agent) -> int:
    print(f"SolVersion2 ready (mode={agent.ctx.cfg.agent.mode}).")
    print("Type /quit to exit.")
    print("Explicit tool call format: /tool <name> <json-with-reason>")
    while True:
        try:
            text = input("You> ").rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.strip().lower() in ("/q", "/quit", "/exit"):
            return 0
        if not text.strip():
            continue

        try:
            res = agent.run(text)
        except AgentPolicyError as e:
            print(f"[policy] {e}\n")
            continue
        except Exception as e:
            print(f"[error] {e}\n")
            continue

        if getattr(res, "retrieved", None):
            retrieved = list(res.retrieved or ())
            if retrieved:
                print("RETRIEVED:")
                for i, ch in enumerate(retrieved[:8], start=1):
                    preview = " ".join((ch.text or "").split())
                    if len(preview) > 160:
                        preview = preview[:160] + "..."
                    print(f"- {i}. trust={ch.trust} source={ch.source_id} score={ch.score}")
                    print(f"  {preview}")
                print("")

        if res.plan.steps:
            print("PLAN:")
            for step in res.plan.steps:
                print(f"- tool={step.tool_name} reason={step.reason!r} args={step.arguments}")
            print("")
        print(f"Sol> {res.text}\n")


def _api_base_url(config: Any) -> str:
    host = str(getattr(getattr(config, "api", None), "host", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(getattr(config, "api", None), "port", 8420) or 8420)
    return f"http://{host}:{port}"


def _provider_error_message(detail: dict[str, Any]) -> str:
    category = str(detail.get("type") or "").strip().lower()
    model = str(detail.get("model") or "").strip()
    base_url = str(detail.get("base_url") or "").strip()
    message = str(detail.get("message") or "").strip()
    if category == "provider_unreachable" and base_url:
        return f"Ollama is unreachable at {base_url}"
    if category == "provider_timeout":
        return message or "Ollama request timed out"
    if category == "model_unavailable" and model:
        return f"Model '{model}' is not available"
    if message:
        return message
    return "Provider request failed"


def _extract_error_message(body: Any) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("type"), str):
            return _provider_error_message(detail)
        if isinstance(detail, str) and detail.strip():
            return f"Unexpected error: {detail.strip()}"
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return f"Unexpected error: {message.strip()}"
    if isinstance(body, str) and body.strip():
        return f"Unexpected error: {body.strip()}"
    return "Unexpected error: request failed"


def _read_json_response(resp: Any) -> Any:
    raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def read_task_file(path: str) -> CliRunResult | str:
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return CliRunResult(ok=False, text=f"File not found: {path}", exit_code=2)
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return CliRunResult(ok=False, text=f"Input file must be UTF-8 text: {path}", exit_code=2)
    except OSError:
        return CliRunResult(ok=False, text=f"Could not read file: {path}", exit_code=2)


def read_stdin_text(stream: Any) -> str | None:
    try:
        if stream.isatty():
            return None
    except Exception:
        return None
    try:
        text = stream.read()
    except Exception:
        return None
    if not isinstance(text, str):
        return None
    return text if text.strip() else None


def compose_run_prompt(task: str, *, file_text: str | None = None, stdin_text: str | None = None) -> CliRunResult | str:
    prompt = task.strip()
    if file_text is not None and stdin_text is not None:
        return CliRunResult(ok=False, text="Use either --file or stdin, not both", exit_code=2)
    if file_text is not None:
        if not file_text.strip():
            return CliRunResult(ok=False, text="No usable input provided", exit_code=2)
        return f"{prompt}\n\n{file_text}" if prompt else file_text
    if stdin_text is not None:
        return f"{prompt}\n\n{stdin_text}" if prompt else stdin_text
    if prompt:
        return prompt
    return CliRunResult(ok=False, text='Usage: nexai run "<task>"', exit_code=2)


def run_task_via_api(config: Any, task: str, *, timeout_s: float = 60.0, status: dict[str, Any] | None = None) -> CliRunResult:
    prompt = task.strip()
    if not prompt:
        return CliRunResult(ok=False, text='Usage: nexai run "<task>"', exit_code=2)

    if isinstance(status, dict):
        services = status.get("services", {}) if isinstance(status.get("services"), dict) else {}
        api = services.get("api", {}) if isinstance(services.get("api"), dict) else {}
        api_state = str(api.get("state", "")).strip().lower()
        api_healthy = api.get("healthy")
        if api_state in {"stopped", "inactive", "failed", "disabled", "not_running"} and api_healthy is False:
            return CliRunResult(ok=False, text="NexAI API is not running. Try: nexai service status", exit_code=1)

    url = f"{_api_base_url(config)}/v1/chat"
    payload = {"message": prompt, "stream": False}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = _read_json_response(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = _read_json_response(exc)
        except Exception:
            body = exc.read().decode("utf-8", errors="replace") if getattr(exc, "fp", None) else ""
        return CliRunResult(ok=False, text=_extract_error_message(body), exit_code=1)
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        return CliRunResult(ok=False, text="NexAI API is not running. Try: nexai service status", exit_code=1)
    except Exception as exc:
        return CliRunResult(ok=False, text=f"Unexpected error: {str(exc).strip() or 'request failed'}", exit_code=1)

    if not isinstance(body, dict):
        return CliRunResult(ok=False, text="Unexpected error: invalid API response", exit_code=1)
    content = body.get("content")
    if isinstance(content, str):
        return CliRunResult(ok=True, text=content, exit_code=0)
    return CliRunResult(ok=False, text="Unexpected error: invalid API response", exit_code=1)
