from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from agentx.core.runtime_models import ArtifactContext
from agentx.core.llm import OllamaConfig, ProviderError, ollama_generate, ollama_generate_stream, provider_error_detail
from agentx.core.response_sanitizer import finalize_response_text

from agentx_api.auth import current_user_id
from agentx_api.config import config
from agentx_api.ollama import normalize_ollama_base_url
from agentx_api.fs_access.errors import FsAccessDenied, FsAccessError, FsNotFound, FsTooLarge
from agentx_api.fs_access.ops import apply_unified_diff, delete_path, list_dir, mkdir, move_path, read_text, write_text
from agentx_api.fs_access.policy import FsPolicy
from agentx_api.routes.settings import _read_settings, effective_collaborative_ollama_routes, effective_ollama_base_url, effective_ollama_endpoint_base_url, effective_ollama_request_timeout_s
from agentx_api.rag.chunking import chunk_text
from agentx_api.rag.session import session_tracker
from agentx_api.rag.store import RagStore
from agentx_api.web_access.errors import WebAccessDenied, WebFetchError
from agentx_api.web_access.fetch import fetch_text
from agentx_api.web_access.policy import WebPolicy
from agentx_api.web_access.search import search as web_search
from agentx_api.routes.threads import _read_thread, ensure_thread_owner
from agentx_api.agentx_bridge import AgentXUnavailable, get_agent_for_thread, get_handle

router = APIRouter(tags=["chat"])


class ArtifactContextRequest(BaseModel):
    type: str
    source: str
    language: str | None = None
    content: str | None = None
    path: str | None = None
    dirty: bool | None = None
    title: str | None = None
    label: str | None = None


class CodingPipelineRequest(BaseModel):
    mode: str = "single"
    draft_model: str | None = None
    review_model: str | None = None


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    response_mode: str = "chat"
    unsafe_enabled: bool | None = None
    active_artifact: ArtifactContextRequest | None = None
    coding_pipeline: CodingPipelineRequest | None = None


class RetrievedChunk(BaseModel):
    text: str
    source_id: str
    ts: float
    tags: list[str] = Field(default_factory=list)
    trust: str
    score: float


class ResponseMetrics(BaseModel):
    duration_ms: int
    first_token_ms: int | None = None
    provider: str | None = None
    model: str | None = None
    response_kind: str = "chat"
    input_chars: int = 0
    output_chars: int = 0
    completed_at: float


def _response_metrics(
    *,
    started_at: float,
    provider: str | None,
    model: str | None,
    user_message: str,
    content: str,
    first_token_at: float | None = None,
) -> ResponseMetrics:
    finished_at = time.perf_counter()
    first_token_ms = None
    if first_token_at is not None:
        first_token_ms = max(0, int(round((first_token_at - started_at) * 1000)))
    return ResponseMetrics(
        duration_ms=max(0, int(round((finished_at - started_at) * 1000))),
        first_token_ms=first_token_ms,
        provider=(provider or None),
        model=(model or None),
        response_kind="code" if _looks_like_coding_request(user_message) else "chat",
        input_chars=len(user_message or ""),
        output_chars=len(content or ""),
        completed_at=time.time(),
    )


class ChatResponse(BaseModel):
    role: str = "assistant"
    content: str
    ts: float
    retrieved: list[RetrievedChunk] | None = None
    audit_tail: list[dict] | None = None
    sources: list[dict[str, str]] | None = None
    verification_level: str | None = None
    verification: dict | None = None
    web: dict | None = None
    response_metrics: ResponseMetrics | None = None
    quality_gate: dict | None = None


def _extract_web_meta(tool_results: object) -> dict | None:
    if not isinstance(tool_results, tuple):
        return None
    last: dict | None = None
    for r in reversed(tool_results):
        if not hasattr(r, "tool") or getattr(r, "tool") != "web.search":
            continue
        output = getattr(r, "output", None)
        if isinstance(output, dict):
            last = output
            break
    if not last:
        return None
    return {
        "providers_used": last.get("providers_used") or (last.get("meta") or {}).get("providers_used") or [],
        "providers_failed": last.get("providers_failed") or (last.get("meta") or {}).get("providers_failed") or [],
        "fetch_blocked": last.get("fetch_blocked") or [],
    }


def _get_agent_pair(thread_id: str, *, user: str) -> tuple[object, object]:
    try:
        if "user" in inspect.signature(get_agent_for_thread).parameters:
            return get_agent_for_thread(thread_id, user=user)
    except Exception:
        pass
    return get_agent_for_thread(thread_id)


def _web_policy() -> WebPolicy:
    return WebPolicy(
        enabled=config.web_enabled,
        allow_all_hosts=config.web_allow_all_hosts,
        allowed_host_suffixes=tuple(config.web_allowed_hosts),
        block_private_networks=config.web_block_private_networks,
        timeout_s=config.web_timeout_s,
        max_bytes=config.web_max_bytes,
        user_agent=config.web_user_agent,
        max_redirects=config.web_max_redirects,
        max_search_results=config.web_max_search_results,
    )


def _fs_policy() -> FsPolicy:
    return FsPolicy(
        enabled=config.fs_enabled,
        allow_all_paths=config.fs_allow_all_paths,
        allowed_roots=tuple(config.fs_allowed_roots),
        allow_write=config.fs_write_enabled,
        allow_delete=config.fs_delete_enabled,
        deny_write_drives=tuple(config.fs_write_deny_drives),
        max_read_bytes=config.fs_max_read_bytes,
        max_write_bytes=config.fs_max_write_bytes,
    )


def _openai_chat(message: str, model: str) -> str:
    url = f"{config.openai_base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.openai_api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.openai_timeout_s) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
        raise HTTPException(status_code=502, detail=f"OpenAI HTTP {e.code}: {body}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {e}")


def _provider_http_exception(exc: ProviderError, *, status_code: int = 502) -> HTTPException:
    payload = provider_error_detail(exc) or {
        "type": "unknown_provider_error",
        "provider": "unknown",
        "message": str(exc),
    }
    return HTTPException(status_code=status_code, detail=payload)


def _ollama_generate(message: str, model: str) -> str:
    settings = _read_settings()
    endpoint = getattr(settings, "ollamaDraftEndpoint", "default") if getattr(settings, "ollamaMultiEndpointEnabled", False) else "default"
    base_url = normalize_ollama_base_url(effective_ollama_endpoint_base_url(settings, endpoint))
    timeout_s = effective_ollama_request_timeout_s(settings)
    try:
        return ollama_generate(
            cfg=OllamaConfig(
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
                max_tool_iters=max(1, int(getattr(config, "ollama_tool_max_iters", 4))),
            ),
            prompt=message,
        )
    except ProviderError as exc:
        raise _provider_http_exception(exc) from exc


def _rag_store() -> RagStore:
    return RagStore(config.rag_db_path)


def _build_retrieval_context(query: str) -> str:
    if not config.rag_enabled:
        return ""
    try:
        hits = _rag_store().query(query, k=config.rag_top_k)
    except Exception:
        return ""
    if not hits:
        return ""
    lines: list[str] = []
    for i, h in enumerate(hits, start=1):
        header = f"[{i}] {h.title} ({h.source})"
        lines.append(header)
        lines.append(h.content)
        lines.append("")
    return "\n".join(lines).strip()


def _tool_rag_upsert(args: dict) -> dict:
    if not config.rag_enabled:
        raise WebFetchError("RAG is disabled (AGENTX_RAG_ENABLED=false).")
    title = str(args.get("title") or "Untitled").strip() or "Untitled"
    source = str(args.get("source") or "web").strip() or "web"
    text = str(args.get("text") or "").strip()
    if not text:
        raise WebFetchError("text is required.")
    if len(text) > max(1, int(config.rag_tool_max_chars)):
        text = text[: max(1, int(config.rag_tool_max_chars))]
    meta = args.get("meta") if isinstance(args.get("meta"), dict) else {}

    doc_id = hashlib.sha256(f"{source}:{title}:{len(text)}".encode("utf-8")).hexdigest()[:24]
    chunks = list(chunk_text(text, chunk_chars=config.rag_chunk_chars, overlap_chars=config.rag_chunk_overlap_chars))
    _rag_store().upsert_document(
        doc_id=doc_id,
        title=title,
        source=source,
        chunks=[(c.chunk_id, c.content) for c in chunks],
        meta=meta,
    )
    return {"doc_id": doc_id, "chunks": len(chunks)}


def _tool_web_fetch(args: dict) -> dict:
    url = str(args.get("url") or "").strip()
    if not url:
        raise WebFetchError("url is required.")
    res = fetch_text(url, policy=_web_policy())
    return {
        "url": res.url,
        "content_type": res.content_type,
        "truncated": res.truncated,
        "text": res.text,
    }


def _tool_web_search(args: dict) -> dict:
    q = str(args.get("query") or "").strip()
    if not q:
        raise WebFetchError("query is required.")
    results = web_search(q, policy=_web_policy())
    return {"results": [{"url": r.url, "title": r.title, "snippet": r.snippet} for r in results]}


def _dispatch_tool_call(name: str, args: dict) -> dict:
    n = (name or "").strip()
    if not n:
        return {"ok": False, "error": "Missing tool name."}
    if not isinstance(args, dict):
        return {"ok": False, "error": "Tool args must be an object."}

    try:
        if n == "web_search":
            if not config.web_enabled:
                return {"ok": False, "error": "Web access is disabled (AGENTX_WEB_ENABLED=false)."}
            return {"ok": True, **_tool_web_search(args)}
        if n == "web_fetch":
            if not config.web_enabled:
                return {"ok": False, "error": "Web access is disabled (AGENTX_WEB_ENABLED=false)."}
            return {"ok": True, **_tool_web_fetch(args)}
        if n == "rag_upsert":
            if not config.rag_enabled:
                return {"ok": False, "error": "RAG is disabled (AGENTX_RAG_ENABLED=false)."}
            return {"ok": True, **_tool_rag_upsert(args)}

        if n == "fs_list_dir":
            if not config.fs_enabled:
                return {"ok": False, "error": "File access is disabled (AGENTX_FS_ENABLED=false)."}
            return {
                "ok": True,
                **list_dir(
                    str(args.get("path") or ""),
                    policy=_fs_policy(),
                    recursive=bool(args.get("recursive") or False),
                    max_entries=int(args.get("max_entries") or 500),
                ),
            }
        if n == "fs_read_text":
            if not config.fs_enabled:
                return {"ok": False, "error": "File access is disabled (AGENTX_FS_ENABLED=false)."}
            return {"ok": True, **read_text(str(args.get("path") or ""), policy=_fs_policy())}

        if n == "fs_write_text":
            if not (config.fs_enabled and config.fs_write_enabled):
                return {"ok": False, "error": "Write access is disabled (AGENTX_FS_WRITE_ENABLED=false)."}
            return {
                "ok": True,
                **write_text(
                    str(args.get("path") or ""),
                    str(args.get("content") or ""),
                    policy=_fs_policy(),
                    create=bool(True if args.get("create") is None else args.get("create")),
                    backup=bool(True if args.get("backup") is None else args.get("backup")),
                ),
            }
        if n == "fs_apply_patch":
            if not (config.fs_enabled and config.fs_write_enabled):
                return {"ok": False, "error": "Write access is disabled (AGENTX_FS_WRITE_ENABLED=false)."}
            return {
                "ok": True,
                **apply_unified_diff(
                    str(args.get("patch_text") or ""),
                    policy=_fs_policy(),
                    backup=bool(True if args.get("backup") is None else args.get("backup")),
                ),
            }
        if n == "fs_mkdir":
            if not (config.fs_enabled and config.fs_write_enabled):
                return {"ok": False, "error": "Write access is disabled (AGENTX_FS_WRITE_ENABLED=false)."}
            return {
                "ok": True,
                **mkdir(
                    str(args.get("path") or ""),
                    policy=_fs_policy(),
                    parents=bool(True if args.get("parents") is None else args.get("parents")),
                    exist_ok=bool(True if args.get("exist_ok") is None else args.get("exist_ok")),
                ),
            }
        if n == "fs_move":
            if not (config.fs_enabled and config.fs_write_enabled):
                return {"ok": False, "error": "Write access is disabled (AGENTX_FS_WRITE_ENABLED=false)."}
            return {
                "ok": True,
                **move_path(
                    str(args.get("src") or ""),
                    str(args.get("dst") or ""),
                    policy=_fs_policy(),
                    overwrite=bool(args.get("overwrite") or False),
                    backup=bool(True if args.get("backup") is None else args.get("backup")),
                ),
            }
        if n == "fs_delete":
            if not (config.fs_enabled and config.fs_write_enabled and config.fs_delete_enabled):
                return {"ok": False, "error": "Delete is disabled (AGENTX_FS_DELETE_ENABLED=false)."}
            return {
                "ok": True,
                **delete_path(
                    str(args.get("path") or ""),
                    policy=_fs_policy(),
                    recursive=bool(args.get("recursive") or False),
                ),
            }
        return {"ok": False, "error": f"Unknown tool: {n}"}
    except (WebAccessDenied, WebFetchError, FsAccessDenied, FsNotFound, FsTooLarge, FsAccessError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Tool failed: {e}"}


_RE_OLLAMA_TOOL = re.compile(r"AGENTX_TOOL_CALL\\s*:\\s*(\\{.*\\})\\s*$", re.DOTALL)


def _parse_ollama_tool_call(text: str) -> tuple[str, dict | None]:
    """Parse a best-effort tool call from an Ollama response.

    Protocol:
    - Either respond normally, OR end the response with:
        AGENTX_TOOL_CALL: {"name":"fs_read_text","args":{...}}
    """
    raw = (text or "").strip()
    m = _RE_OLLAMA_TOOL.search(raw)
    if not m:
        return raw, None
    json_blob = m.group(1).strip()
    assistant_text = raw[: m.start()].strip()
    try:
        data = json.loads(json_blob)
        if not isinstance(data, dict):
            return raw, None
        name = data.get("name")
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        if not isinstance(name, str) or not name.strip():
            return raw, None
        return assistant_text, {"name": name.strip(), "args": args}
    except Exception:
        return raw, None


def _ollama_chat_with_tools(*, short_term: list[dict], retrieved: str, user_message: str, model: str) -> str:
    """Run an Ollama loop that can invoke tools via a simple text protocol."""
    max_iters = max(1, int(config.ollama_tool_max_iters))
    tool_history: list[dict] = []

    system_lines = [
        "You are AgentX.",
        "You may use tools when needed.",
        "If you need to use a tool, end your message with exactly one line:",
        'AGENTX_TOOL_CALL: {"name":"TOOL_NAME","args":{...}}',
        "After the tool result, continue and either call another tool or answer normally.",
        "Never write to drive C: (read-only). Prefer non-C drives.",
    ]
    behavior_contract = _model_behavior_contract(user_message)
    if behavior_contract:
        system_lines.append(behavior_contract)
    if not config.fs_enabled:
        system_lines.append("File tools are disabled (AGENTX_FS_ENABLED=false).")
    if not config.fs_write_enabled:
        system_lines.append("File writes are disabled (AGENTX_FS_WRITE_ENABLED=false).")
    if not config.fs_delete_enabled:
        system_lines.append("Deletes are disabled (AGENTX_FS_DELETE_ENABLED=false).")
    if not config.web_enabled:
        system_lines.append("Web tools are disabled (AGENTX_WEB_ENABLED=false).")
    if not config.rag_enabled:
        system_lines.append("RAG save is disabled (AGENTX_RAG_ENABLED=false).")

    def build_prompt() -> str:
        convo = list(short_term)
        convo.append({"role": "user", "content": user_message})
        # Inject tool results as additional context in the conversation transcript.
        tool_lines: list[str] = []
        for t in tool_history[-10:]:
            tool_lines.append(f"TOOL {t['name']} RESULT:")
            tool_lines.append(t["result_json"])
            tool_lines.append("")
        tool_block = "\n".join(tool_lines).strip()
        combined_retrieved = retrieved
        if tool_block:
            combined_retrieved = (combined_retrieved + "\n\n" if combined_retrieved else "") + tool_block
        return _ollama_prompt("\n".join(system_lines), combined_retrieved, convo)

    for _ in range(max_iters):
        prompt = build_prompt()
        raw = _ollama_generate(prompt, model=model)
        if not raw:
            return ""
        assistant_text, tool_call = _parse_ollama_tool_call(raw)
        if not tool_call:
            return raw.strip()
        result = _dispatch_tool_call(tool_call["name"], tool_call.get("args") or {})
        tool_history.append({"name": tool_call["name"], "result_json": json.dumps(result, ensure_ascii=False)})
        # Keep looping; model will see the tool results via prompt injection.
        # If the model produced text before the tool call line, we drop it to keep the protocol strict.

    return "Tool loop exceeded AGENTX_OLLAMA_TOOL_MAX_ITERS."


def _openai_call(payload: dict) -> dict:
    url = f"{config.openai_base_url.rstrip('/')}/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.openai_api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.openai_timeout_s) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
        raise HTTPException(status_code=502, detail=f"OpenAI HTTP {e.code}: {body}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {e}")


def _openai_chat_with_tools(*, model: str, messages: list[dict]) -> str:
    tools: list[dict] = []
    if config.web_enabled:
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web (DuckDuckGo HTML) for relevant pages.",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "description": "Fetch a URL and extract readable text. Respects AGENTX_WEB_* policy.",
                        "parameters": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"],
                        },
                    },
                },
            ]
        )
    if config.rag_enabled:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "rag_upsert",
                    "description": "Save text into AgentX RAG for later retrieval. Use only when the user asks to remember.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "source": {"type": "string"},
                            "text": {"type": "string"},
                            "meta": {"type": "object"},
                        },
                        "required": ["title", "source", "text"],
                    },
                },
            }
        )

    if config.fs_enabled:
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "fs_list_dir",
                        "description": "List a directory. Respects AGENTX_FS_* policy.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "recursive": {"type": "boolean"},
                                "max_entries": {"type": "integer"},
                            },
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "fs_read_text",
                        "description": "Read a UTF-8 text file. Respects AGENTX_FS_* policy.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                },
            ]
        )

    if config.fs_enabled and config.fs_write_enabled:
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "fs_write_text",
                        "description": "Write a UTF-8 text file. Denies writes to drives in AGENTX_FS_WRITE_DENY_DRIVES (default C).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                                "create": {"type": "boolean"},
                                "backup": {"type": "boolean"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "fs_apply_patch",
                        "description": "Apply a unified diff patch. Denies writes to drives in AGENTX_FS_WRITE_DENY_DRIVES (default C).",
                        "parameters": {
                            "type": "object",
                            "properties": {"patch_text": {"type": "string"}, "backup": {"type": "boolean"}},
                            "required": ["patch_text"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "fs_mkdir",
                        "description": "Create a directory. Denies writes to drives in AGENTX_FS_WRITE_DENY_DRIVES (default C).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "parents": {"type": "boolean"},
                                "exist_ok": {"type": "boolean"},
                            },
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "fs_move",
                        "description": "Move/rename a path. Denies writes to drives in AGENTX_FS_WRITE_DENY_DRIVES (default C).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "src": {"type": "string"},
                                "dst": {"type": "string"},
                                "overwrite": {"type": "boolean"},
                                "backup": {"type": "boolean"},
                            },
                            "required": ["src", "dst"],
                        },
                    },
                },
            ]
        )

    if config.fs_enabled and config.fs_write_enabled and config.fs_delete_enabled:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "fs_delete",
                    "description": "Delete a path (recursive optional). Denies deletes to drives in AGENTX_FS_WRITE_DENY_DRIVES (default C).",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean"}},
                        "required": ["path"],
                    },
                },
            }
        )

    max_iters = max(1, int(config.openai_tool_max_iters))
    for _ in range(max_iters):
        payload: dict = {"model": model or config.openai_model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = _openai_call(payload)
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return str(msg.get("content") or "")

        # Append the assistant tool call message, then tool results.
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
        for tc in tool_calls:
            tc_id = tc.get("id") or ""
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            args_raw = str(fn.get("arguments") or "{}")
            try:
                args = json.loads(args_raw) if args_raw.strip() else {}
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except Exception as e:
                out = {"ok": False, "error": f"Invalid tool arguments: {e}"}
            else:
                try:
                    if name == "web_search":
                        out = {"ok": True, **_tool_web_search(args)}
                    elif name == "web_fetch":
                        out = {"ok": True, **_tool_web_fetch(args)}
                    elif name == "rag_upsert":
                        out = {"ok": True, **_tool_rag_upsert(args)}
                    elif name == "fs_list_dir":
                        out = {
                            "ok": True,
                            **list_dir(
                                str(args.get("path") or ""),
                                policy=_fs_policy(),
                                recursive=bool(args.get("recursive") or False),
                                max_entries=int(args.get("max_entries") or 500),
                            ),
                        }
                    elif name == "fs_read_text":
                        out = {"ok": True, **read_text(str(args.get("path") or ""), policy=_fs_policy())}
                    elif name == "fs_write_text":
                        out = {
                            "ok": True,
                            **write_text(
                                str(args.get("path") or ""),
                                str(args.get("content") or ""),
                                policy=_fs_policy(),
                                create=bool(True if args.get("create") is None else args.get("create")),
                                backup=bool(True if args.get("backup") is None else args.get("backup")),
                            ),
                        }
                    elif name == "fs_apply_patch":
                        out = {
                            "ok": True,
                            **apply_unified_diff(
                                str(args.get("patch_text") or ""),
                                policy=_fs_policy(),
                                backup=bool(True if args.get("backup") is None else args.get("backup")),
                            ),
                        }
                    elif name == "fs_mkdir":
                        out = {
                            "ok": True,
                            **mkdir(
                                str(args.get("path") or ""),
                                policy=_fs_policy(),
                                parents=bool(True if args.get("parents") is None else args.get("parents")),
                                exist_ok=bool(True if args.get("exist_ok") is None else args.get("exist_ok")),
                            ),
                        }
                    elif name == "fs_move":
                        out = {
                            "ok": True,
                            **move_path(
                                str(args.get("src") or ""),
                                str(args.get("dst") or ""),
                                policy=_fs_policy(),
                                overwrite=bool(args.get("overwrite") or False),
                                backup=bool(True if args.get("backup") is None else args.get("backup")),
                            ),
                        }
                    elif name == "fs_delete":
                        out = {
                            "ok": True,
                            **delete_path(
                                str(args.get("path") or ""),
                                policy=_fs_policy(),
                                recursive=bool(args.get("recursive") or False),
                            ),
                        }
                    else:
                        out = {"ok": False, "error": f"Unknown tool: {name}"}
                except (WebAccessDenied, WebFetchError, FsAccessDenied, FsNotFound, FsTooLarge, FsAccessError) as e:
                    out = {"ok": False, "error": str(e)}
                except Exception as e:
                    out = {"ok": False, "error": f"Tool failed: {e}"}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": name,
                    "content": json.dumps(out, ensure_ascii=False),
                }
            )

    raise HTTPException(status_code=502, detail="OpenAI tool loop exceeded AGENTX_OPENAI_TOOL_MAX_ITERS.")


def _build_short_term_messages(thread_id: str | None, user_message: str, *, owner_id: str | None) -> list[dict]:
    if not thread_id or not owner_id:
        return [{"role": "user", "content": user_message}]

    try:
        thread = _read_thread(thread_id, owner_id=owner_id)
    except Exception:
        return [{"role": "user", "content": user_message}]

    msgs = thread.messages[-max(1, config.short_term_max_messages) :]
    out: list[dict] = []
    # If the last message is the same user text, drop it and add the request message at the end.
    if msgs and msgs[-1].role == "user" and msgs[-1].content.strip() == user_message.strip():
        msgs = msgs[:-1]
    for m in msgs:
        out.append({"role": m.role, "content": m.content})
    out.append({"role": "user", "content": user_message})
    return out


def _ollama_prompt(system: str, retrieved: str, conversation: list[dict]) -> str:
    parts: list[str] = [system.strip()]
    if retrieved:
        parts.append("")
        parts.append("RETRIEVED CONTEXT (use if relevant):")
        parts.append(retrieved.strip())
    parts.append("")
    parts.append("RECENT CONVERSATION:")
    for m in conversation:
        role = m["role"]
        content = m["content"]
        parts.append(f"{role.upper()}: {content}")
    parts.append("")
    parts.append("ASSISTANT:")
    return "\n".join(parts)


_CODING_INTENT_RE = re.compile(
    r"\b("
    r"code|coding|script|program|function|class|cli|api|app|web ?app|component|"
    r"debug|bug|fix|refactor|implement|build|create|generate|write|make|"
    r"python|javascript|typescript|react|node|bash|powershell|sql|docker|yaml"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_coding_request(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if "```" in cleaned:
        return True
    return bool(_CODING_INTENT_RE.search(cleaned))


def _behavior_flag(behavior: object, name: str, default: bool = True) -> bool:
    try:
        return bool(getattr(behavior, name, default))
    except Exception:
        return default


def _behavior_text(behavior: object, name: str, default: str = "") -> str:
    try:
        return str(getattr(behavior, name, default) or "").strip()
    except Exception:
        return default.strip()


def _coding_output_contract() -> str:
    settings = _read_settings()
    behavior = getattr(settings, "modelBehavior", None)
    custom = _behavior_text(behavior, "codingContract", "")
    if custom:
        lines = ["Coding output contract:", custom]
    else:
        lines = [
            "Coding output contract:",
            "- When the user asks for code, return complete, runnable code in one proper fenced code block such as ```python ... ```.",
            "- Never write literal labels like 'Copy code' or fake USER/ASSISTANT transcript lines.",
            "- Preserve indentation exactly. Do not flatten code blocks.",
            "- Prefer the Python standard library unless the user asks for dependencies.",
            "- For CLI scripts, prefer argparse, validate inputs, and handle PermissionError/OSError without crashing.",
            "- Include Windows-friendly run examples when paths or commands matter.",
            "- Keep explanations brief and place them outside the fenced code block.",
        ]
    if behavior is not None:
        if _behavior_flag(behavior, "requireFencedCode", True):
            lines.append("- Required: use fenced code blocks with the language name for code.")
        if _behavior_flag(behavior, "preferStandardLibrary", True):
            lines.append("- Required: prefer the standard library unless the user asks for dependencies.")
        if _behavior_flag(behavior, "windowsAwareExamples", True):
            lines.append("- Required: include Windows-friendly run examples when commands or paths matter.")
    return "\n".join(lines)


def _collaborative_reviewer_contract() -> str:
    settings = _read_settings()
    behavior = getattr(settings, "modelBehavior", None)
    if behavior is None or not _behavior_flag(behavior, "collaborativeReviewerContractEnabled", True):
        return ""
    custom = _behavior_text(behavior, "collaborativeReviewerContract", "")
    if custom:
        return "Collaborative coding reviewer contract:\n" + custom
    return (
        "Collaborative coding reviewer contract:\n"
        "- Treat the original user request as the source of truth. The draft is only a starting point.\n"
        "- Return one complete final answer, not a review memo.\n"
        "- Preserve correct draft functionality while fixing bugs, gaps, bad assumptions, and weak structure.\n"
        "- Use proper fenced code blocks with the language name.\n"
        "- Remove literal labels like 'Copy code', fake transcripts, duplicate code, and placeholder-only solutions.\n"
        "- For CLI scripts, use argparse, clear help text, and Windows-friendly run examples.\n"
        "- Validate user-provided paths and inputs before doing work.\n"
        "- Handle PermissionError and OSError around file access.\n"
        "- Handle output/write errors when creating CSV, reports, or generated files.\n"
        "- Do not hardcode placeholder paths as the final solution.\n"
        "- If scanning files, include useful CSV/report columns when relevant: filename, full path, size_bytes, size_gb, and modified time."
    )


def _model_behavior_contract(user_message: str) -> str:
    settings = _read_settings()
    behavior = getattr(settings, "modelBehavior", None)
    if behavior is None or not _behavior_flag(behavior, "enabled", True):
        return ""
    parts: list[str] = []
    global_instructions = _behavior_text(behavior, "globalInstructions", "")
    if global_instructions:
        parts.append("Global model behavior contract:\n" + global_instructions)
    if _looks_like_coding_request(user_message) and _behavior_flag(behavior, "codingContractEnabled", True):
        parts.append(_coding_output_contract())
    return "\n\n".join(part for part in parts if part.strip())


def _system_prompt_for_request(response_mode: str, user_message: str) -> str:
    system_prompt = "You are AgentX. Answer directly and helpfully."
    behavior_contract = _model_behavior_contract(user_message)
    if behavior_contract:
        system_prompt += "\n\n" + behavior_contract
    if (response_mode or "chat").strip().lower() == "spoken":
        system_prompt += (
            " Spoken mode: answer directly, keep it short, sound natural when read aloud,"
            " do not include hidden reasoning, no markdown, and no bullet lists unless the user explicitly asks for them."
        )
    return system_prompt


def _collaborative_pipeline_requested(request: ChatRequest) -> bool:
    pipeline = request.coding_pipeline
    if pipeline is None:
        return False
    return (pipeline.mode or "").strip().lower() in {"draft_review", "collaborative"}


def _collaborative_models(request: ChatRequest, fallback_model: str, settings=None) -> tuple[str, str]:
    settings = settings or _read_settings()
    pipeline = request.coding_pipeline
    draft_model = (getattr(pipeline, "draft_model", None) or "").strip() if pipeline else ""
    review_model = (getattr(pipeline, "review_model", None) or "").strip() if pipeline else ""
    if not draft_model:
        draft_model = (getattr(settings, "ollamaFastModel", "") or "").strip() or "qwen2.5-coder:7b-4k-gpu"
    if not review_model:
        review_model = (getattr(settings, "ollamaHeavyModel", "") or "").strip() or fallback_model or "devstral-small-2:24b-4k-gpu"
    return draft_model, review_model


def _collaborative_draft_prompt(system_prompt: str, retrieved: str, short_term: list[dict]) -> str:
    draft_system = (
        system_prompt
        + "\n\nCollaborative coding pipeline stage 1: fast draft. "
        + "Create a complete first-pass implementation that satisfies the user request. "
        + "Prefer clear, runnable code over explanation. The reviewer model will improve it next."
    )
    return _ollama_prompt(draft_system, retrieved, short_term)


def _collaborative_review_prompt(
    *,
    system_prompt: str,
    retrieved: str,
    original_request: str,
    draft_model: str,
    review_model: str,
    draft: str,
) -> str:
    review_user = "\n".join(
        [
            "You are the code reviewer and finalizer in AgentX Collaborative Coding mode.",
            "",
            "You will receive the original user request and a first-draft implementation from another model.",
            "Your job:",
            "- Verify the draft satisfies every user requirement.",
            "- Fix incorrect logic, missing imports, missing CLI handling, hardcoded placeholder paths, and incomplete output/export behavior.",
            "- Preserve clean formatting and indentation.",
            "- Return one complete final answer with production-ready code and brief run instructions.",
            "",
            _collaborative_reviewer_contract(),
            "",
            f"Draft model: {draft_model}",
            f"Review/final model: {review_model}",
            "",
            "Original user request:",
            original_request,
            "",
            "First-draft implementation:",
            draft,
        ]
    )
    review_system = system_prompt + "\n\nCollaborative coding pipeline stage 2: review, fix, and finalize."
    return _ollama_prompt(review_system, retrieved, [{"role": "user", "content": review_user}])



def _wants_third_party_dependencies(user_message: str) -> bool:
    text = (user_message or "").lower()
    return any(phrase in text for phrase in (
        "use watchdog", "watchdog", "use dependencies", "external dependency",
        "third-party", "third party", "pip install", "package", "library",
        "file watcher", "filesystem watcher",
    ))


def _extract_fenced_code_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"```([A-Za-z0-9_+.-]*)\s*\n(.*?)```", text or "", re.DOTALL):
        blocks.append(((match.group(1) or "").strip().lower(), match.group(2) or ""))
    return blocks


def _primary_code_text(text: str) -> str:
    blocks = _extract_fenced_code_blocks(text)
    if not blocks:
        return text or ""
    return max((code for _, code in blocks), key=len, default=text or "")


def _detect_code_language(text: str, user_message: str) -> str:
    requested = (user_message or "").lower()
    if "powershell" in requested or ".ps1" in requested:
        return "powershell"
    if "python" in requested or ".py" in requested:
        return "python"
    for lang, _code in _extract_fenced_code_blocks(text):
        if lang in {"python", "py"}:
            return "python"
        if lang in {"powershell", "ps1", "pwsh"}:
            return "powershell"
    code = _primary_code_text(text)
    if "param(" in code or "Get-ChildItem" in code or "Export-Csv" in code:
        return "powershell"
    if "argparse" in code or "def main" in code or "import " in code:
        return "python"
    return "unknown"


def _collaborative_quality_gate(original_request: str, final_answer: str) -> dict:
    """Heuristic quality checks for collaborative coding output.

    These checks do not execute generated code. They catch recurring misses and feed a
    concise failure list into one repair pass.
    """
    request = (original_request or "").lower()
    answer = final_answer or ""
    answer_l = answer.lower()
    code = _primary_code_text(answer)
    code_l = code.lower()
    lang = _detect_code_language(answer, original_request)
    failures: list[str] = []
    warnings: list[str] = []

    def has_any(*needles: str) -> bool:
        return any(needle.lower() in code_l for needle in needles)

    wants_cli = any(word in request for word in ("script", "cli", "command", "powershell", "python"))
    wants_monitor = any(word in request for word in ("monitor", "watch", "watcher", "continuously", "poll"))
    wants_report = any(word in request for word in ("csv", "export", "report"))
    moves_files = any(word in request for word in ("move", "moving", "delete", "deleting", "rename", "renaming"))
    duplicate_hash = "duplicate" in request and any(word in request for word in ("hash", "files", "file"))
    folder_organizer = any(word in request for word in ("extension", "categorized", "category", "organize", "folder")) and moves_files

    if "copy code" in answer_l:
        failures.append("Remove literal 'Copy code' labels from the final answer.")
    if "c:\\path\\to" in answer_l or "c:/path/to" in answer_l:
        failures.append("Do not leave placeholder paths like C:\\path\\to in the final solution.")
    if "from draftreview" in code_l or "import draftreview" in code_l:
        failures.append("Remove the fake/unrequested draftreview dependency; Draft Review is a workflow label, not a Python package.")
    if "pip install os" in answer_l or "pip install argparse" in answer_l or "pip install shutil" in answer_l:
        failures.append("Do not include pip install commands for Python standard-library modules such as os, argparse, or shutil.")
    if "import watchdog" in code_l or "from watchdog" in code_l:
        if not _wants_third_party_dependencies(original_request):
            failures.append("Remove watchdog/Observer imports and rewrite monitoring with a standard-library polling loop unless the user explicitly requested third-party file watcher dependencies.")
    if ("pip install watchdog" in answer_l or "watchdog library" in answer_l) and not _wants_third_party_dependencies(original_request):
        failures.append("Do not recommend or require watchdog unless the user explicitly requested third-party dependencies; use standard-library polling instead.")
    if "production-ready" in answer_l and ("watchdog" in code_l or "except exception" in code_l):
        failures.append("Do not call the result production-ready when it still uses unrequested dependencies or broad exception handling.")
    if "handles all edge cases" in answer_l or "all edge cases" in answer_l:
        failures.append("Do not claim the script handles all edge cases; keep the explanation accurate and modest.")
    if wants_report and not has_any("csv", "export-csv", "dictwriter", "writerow", "export_csv", "export_to_csv"):
        failures.append("The user asked for CSV/export/report output; implement real CSV/report output.")

    if lang == "python":
        if wants_cli and "argparse" not in code_l:
            failures.append("Python CLI scripts must use argparse.")
        if "os.scandir" in code_l and re.search(r"\bentry\.suffix\b|\bentry\.stem\b", code):
            failures.append("Do not use pathlib-only attributes like .suffix or .stem directly on os.DirEntry; use Path(entry.path) or Path.iterdir().")
        if "--interval" in code_l and not re.search(r"time\.sleep\([^\)]*interval", code, re.IGNORECASE):
            failures.append("The --interval argument is declared but not used in the monitoring sleep loop.")
        if wants_monitor and not ("while true" in code_l or "observer" in code_l or "watchdog" in code_l or "time.sleep" in code_l):
            failures.append("The user asked to monitor; implement continuous monitoring/polling rather than a one-time scan.")
        if moves_files and "--dry-run" not in code_l:
            failures.append("File-moving/deleting scripts should include --dry-run when practical.")
        if moves_files and not re.search(r"while\s+.*exists\s*\(", code, re.IGNORECASE) and "unique" not in code_l and "counter" not in code_l:
            failures.append("Handle destination filename collisions by generating a unique destination path instead of overwriting or silently skipping.")
        if wants_monitor and moves_files and not any(term in code_l for term in ("stable", "stability", "wait_for_file", "is_file_ready", "size_before", "size_after")):
            failures.append("Monitoring scripts that move files should include a simple file-stability check before moving active/copying/downloading files.")
        if wants_monitor and moves_files and ("stable" in code_l or "stability" in code_l):
            has_size_based_stability = any(term in code_l for term in ("st_size", ".stat().st_size", "size_before", "size_after", "first_size", "second_size"))
            if not has_size_based_stability:
                failures.append("File-stability checks should compare file size/metadata across a short delay, not only open or seek the file once.")
        if moves_files and "shutil.move" in code_l and re.search(r"print\([^\n]*(ext_dir\s*/\s*item\.name|/\s*item\.name)", code):
            failures.append("When collision handling may rename the destination, log the actual final destination path, not the original filename path.")
        if re.search(r"for\s+\w+\s+in[^:]+:\s*\n\s*.*MoveFileHandler\(", code, re.IGNORECASE | re.DOTALL):
            failures.append("Do not instantiate the monitoring/file handler inside the per-file loop; create it once and reuse it.")
        if "--interval" in code_l and not re.search(r"interval\s*<\s*=?\s*0|interval\s*<\s*1|parser\.error\([^\)]*interval", code, re.IGNORECASE):
            failures.append("Validate that --interval is positive before starting the monitoring loop.")
        if folder_organizer and "--dest-root" not in code_l and "dest_root" not in code_l and "dest root" not in answer_l and "--dest" not in code_l:
            warnings.append("Consider using --dest-root/--dest so categorized folders have clear, predictable placement.")
        if "exit(1)" in code_l and "sys.exit" not in code_l:
            warnings.append("Prefer sys.exit(1) over bare exit(1) in Python scripts.")
        if "production-ready" in answer_l:
            required = "--dry-run" in code_l and ("counter" in code_l or "unique" in code_l) and ("stable" in code_l or "stability" in code_l)
            if not required:
                failures.append("Do not call the result production-ready unless it includes dry-run, collision handling, input validation, destination safety, and file-stability handling.")

    if lang == "powershell":
        if wants_cli and "param(" not in code_l:
            failures.append("PowerShell scripts should use a param() block instead of hardcoded variables or Read-Host unless interactive mode is requested.")
        if "read-host" in code_l and "interactive" not in request:
            failures.append("Use param() instead of Read-Host unless the user requested interactive input.")
        if "import-module" in code_l and any(term in code_l for term in ("psscriptanalyzer", "hashtable", "hashtableutils", "compression.powershellutils")):
            failures.append("Remove unnecessary/fake Import-Module statements for built-in PowerShell functionality.")
        if duplicate_hash:
            if "get-filehash" not in code_l:
                failures.append("Duplicate-by-hash scripts must use Get-FileHash or another explicit hashing method.")
            if "get-filehash -path" in code_l and "get-filehash -literalpath" not in code_l:
                failures.append("Use Get-FileHash -LiteralPath for discovered filesystem paths.")
            if "export-csv" not in code_l:
                failures.append("Duplicate report scripts should export results with Export-Csv, not Add-Content or manual strings.")
            for column in ("hash", "filename", "fullpath", "sizebytes", "modifiedtime", "duplicatecount"):
                if column not in code_l:
                    failures.append(f"Duplicate report is missing the {column} column/field.")
            if "readallbytes" in code_l:
                failures.append("Avoid loading whole large files into memory when hashing; use Get-FileHash -LiteralPath.")
        if "add-content" in code_l and wants_report:
            failures.append("Use Export-Csv for CSV reports instead of Add-Content/manual CSV text.")
        if "-jo" in code_l:
            failures.append("Remove invalid/made-up PowerShell operators such as -jo; use the real -join operator if needed.")
        if re.search(r"Generic\.List\[[^\]]+\]\]::new\([^\)]*(FileInfo|\$file)", code):
            failures.append("Initialize Generic.List empty, then call .Add(); do not pass FileInfo directly to ::new().")
        if re.search(r"\$\([^\)]*\bgroups\)", code, re.IGNORECASE):
            failures.append("Do not put invalid expressions inside expandable strings; calculate group counts before Write-Host/Write-Output.")

    return {"passed": not failures, "language": lang, "failures": failures, "warnings": warnings}


def _quality_gate_report(
    *,
    initial_gate: dict | None,
    final_gate: dict | None,
    repair_attempted: bool,
    repaired: bool,
    draft_model: str | None = None,
    review_model: str | None = None,
    endpoints: dict | None = None,
) -> dict:
    initial = initial_gate or {"passed": True, "failures": [], "warnings": [], "language": "unknown"}
    final = final_gate or initial
    initial_failures = list(initial.get("failures") or [])
    final_failures = list(final.get("failures") or [])
    final_warnings = list(final.get("warnings") or [])
    fixed_failures = [failure for failure in initial_failures if failure not in final_failures]

    if final_failures:
        status = "warning" if repair_attempted else "failed"
    elif repaired:
        status = "repaired"
    else:
        status = "passed"

    checks_failed = len(final_failures)
    checks_fixed = len(fixed_failures)
    checks_warned = len(final_warnings)
    checks_passed = max(0, len(initial_failures) - checks_failed)

    return {
        "status": status,
        "passed": not final_failures,
        "language": final.get("language") or initial.get("language") or "unknown",
        "repair_attempted": repair_attempted,
        "repaired": repaired,
        "initial_failures": initial_failures,
        "failures": final_failures,
        "fixed_failures": fixed_failures,
        "warnings": final_warnings,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "checks_fixed": checks_fixed,
        "checks_warned": checks_warned,
        "draft_model": draft_model,
        "review_model": review_model,
        "endpoints": endpoints or {},
    }


def _collaborative_repair_prompt(
    *,
    system_prompt: str,
    retrieved: str,
    original_request: str,
    draft_model: str,
    review_model: str,
    draft: str,
    reviewed_answer: str,
    gate: dict,
) -> str:
    failures = gate.get("failures") or []
    warnings = gate.get("warnings") or []
    lines = [
        "You are the repair pass in AgentX Collaborative Coding mode.",
        "The previous reviewed/finalized answer failed deterministic quality checks.",
        "Repair the answer. Return one complete final answer only.",
        "Do not explain the checklist. Do not return a diff. Do not return the failed version unchanged.",
        "The original user request is the source of truth.",
        "Every quality gate failure below is mandatory. If a failure says to remove a dependency, rewrite the code so that dependency is gone.",
        "For Python folder monitors, default to standard-library polling unless the user explicitly requested watchdog or third-party file watcher packages.",
        "",
        _collaborative_reviewer_contract(),
        "",
        f"Draft model: {draft_model}",
        f"Review/final model: {review_model}",
        f"Detected language: {gate.get('language') or 'unknown'}",
        "",
        "Quality gate failures to fix:",
    ]
    lines.extend(f"- {failure}" for failure in failures)
    if warnings:
        lines.append("")
        lines.append("Quality gate warnings to consider:")
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend([
        "",
        "Original user request:",
        original_request,
        "",
        "First draft:",
        draft,
        "",
        "Reviewed answer that failed checks:",
        reviewed_answer,
    ])
    repair_system = system_prompt + "\n\nCollaborative coding pipeline stage 3: deterministic quality-gate repair."
    return _ollama_prompt(repair_system, retrieved, [{"role": "user", "content": "\n".join(lines)}])

def _stream_event(event: str, payload: dict | None = None) -> str:
    data = {"event": event}
    if payload:
        data.update(payload)
    return json.dumps(data, ensure_ascii=False) + "\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest, http: Request) -> StreamingResponse:
    """Stream assistant output as newline-delimited JSON events.

    Event shapes:
    - {"event":"meta", "provider":"ollama", "model":"..."}
    - {"event":"delta", "content":"..."}
    - {"event":"done", "content":"full final response", ...ChatResponse fields}
    - {"event":"error", "message":"...", "detail":{...}}
    """

    def events():
        request_started_at = time.perf_counter()
        first_token_at: float | None = None
        try:
            settings = _read_settings()
            provider = (getattr(settings, "chatProvider", "stub") or "stub").strip().lower()
            model = (getattr(settings, "chatModel", "stub") or "stub").strip()
            response_mode = (request.response_mode or "chat").strip().lower() or "chat"
            user_id = current_user_id(http)
            requested_thread_id = (request.thread_id or "").strip() or None
            if requested_thread_id and user_id:
                thread = ensure_thread_owner(requested_thread_id, owner_id=user_id)
                provider = (thread.chat_provider or provider or "stub").strip().lower()
                model = (thread.chat_model or model or "stub").strip()

            yield _stream_event("meta", {"provider": provider, "model": model, "ts": time.time()})

            if provider == "ollama" and _collaborative_pipeline_requested(request):
                settings = _read_settings()
                draft_model, review_model = _collaborative_models(request, model, settings)
                routes = effective_collaborative_ollama_routes(settings)
                thread_id = requested_thread_id or session_tracker.get_active_thread(user_id or "")
                if thread_id and user_id:
                    ensure_thread_owner(thread_id, owner_id=user_id)
                short_term = _build_short_term_messages(thread_id, request.message, owner_id=user_id)
                retrieved = _build_retrieval_context(request.message)

                if config.web_enabled:
                    urls = re.findall(r"https?://\S+", request.message or "")
                    urls = [u.rstrip(").,;!\"'") for u in urls][:3]
                    web_parts: list[str] = []
                    for u in urls:
                        try:
                            res = fetch_text(u, policy=_web_policy())
                            web_parts.append(f"URL: {res.url}\n{res.text[:4000]}")
                        except Exception:
                            continue
                    if web_parts:
                        retrieved = (retrieved + "\n\n" if retrieved else "") + "\n\n".join(web_parts)

                draft_base_url = normalize_ollama_base_url(routes.get("draft_base_url") or effective_ollama_base_url(settings))
                review_base_url = normalize_ollama_base_url(routes.get("review_base_url") or effective_ollama_base_url(settings))
                repair_base_url = normalize_ollama_base_url(routes.get("repair_base_url") or review_base_url)
                timeout_s = effective_ollama_request_timeout_s(settings)
                system_prompt = _system_prompt_for_request(response_mode, request.message)

                yield _stream_event(
                    "meta",
                    {
                        "stage": "draft",
                        "provider": "ollama",
                        "model": draft_model,
                        "review_model": review_model,
                        "endpoint": routes.get("draft_endpoint"),
                        "base_url": draft_base_url,
                        "ts": time.time(),
                    },
                )
                draft_prompt = _collaborative_draft_prompt(system_prompt, retrieved, short_term)
                draft = ollama_generate(
                    cfg=OllamaConfig(
                        base_url=draft_base_url,
                        model=draft_model,
                        timeout_s=timeout_s,
                        max_tool_iters=max(1, int(getattr(config, "ollama_tool_max_iters", 4))),
                    ),
                    prompt=draft_prompt,
                )
                draft = finalize_response_text(draft, response_mode="chat")
                if not draft:
                    raise HTTPException(status_code=502, detail=f"Draft model {draft_model} returned an empty response.")

                yield _stream_event(
                    "meta",
                    {
                        "stage": "review",
                        "provider": "ollama",
                        "model": review_model,
                        "draft_model": draft_model,
                        "endpoint": routes.get("review_endpoint"),
                        "base_url": review_base_url,
                        "ts": time.time(),
                    },
                )
                review_prompt = _collaborative_review_prompt(
                    system_prompt=system_prompt,
                    retrieved=retrieved,
                    original_request=request.message,
                    draft_model=draft_model,
                    review_model=review_model,
                    draft=draft,
                )
                content = ollama_generate(
                    cfg=OllamaConfig(
                        base_url=review_base_url,
                        model=review_model,
                        timeout_s=timeout_s,
                        max_tool_iters=max(1, int(getattr(config, "ollama_tool_max_iters", 4))),
                    ),
                    prompt=review_prompt,
                )
                content = finalize_response_text(content, response_mode=response_mode)
                if not content:
                    raise HTTPException(status_code=502, detail=f"Review model {review_model} returned an empty response.")

                initial_gate = _collaborative_quality_gate(request.message, content)
                gate = initial_gate
                repair_attempted = False
                repaired_successfully = False
                behavior = getattr(settings, "modelBehavior", None)
                if _behavior_flag(behavior, "autoRepairEnabled", True):
                    repair_pass = 0
                    max_repair_passes = 2
                    while not gate.get("passed") and repair_pass < max_repair_passes:
                        repair_pass += 1
                        repair_attempted = True
                        yield _stream_event(
                            "meta",
                            {
                                "stage": "repair",
                                "provider": "ollama",
                                "model": review_model,
                                "repair_pass": repair_pass,
                                "quality_gate": gate,
                                "endpoint": routes.get("repair_endpoint"),
                                "base_url": repair_base_url,
                                "ts": time.time(),
                            },
                        )
                        repair_prompt = _collaborative_repair_prompt(
                            system_prompt=system_prompt,
                            retrieved=retrieved,
                            original_request=request.message,
                            draft_model=draft_model,
                            review_model=review_model,
                            draft=draft,
                            reviewed_answer=content,
                            gate=gate,
                        )
                        repaired = ollama_generate(
                            cfg=OllamaConfig(
                                base_url=repair_base_url,
                                model=review_model,
                                timeout_s=timeout_s,
                                max_tool_iters=max(1, int(getattr(config, "ollama_tool_max_iters", 4))),
                            ),
                            prompt=repair_prompt,
                        )
                        repaired = finalize_response_text(repaired, response_mode=response_mode)
                        if not repaired:
                            break
                        content = repaired
                        repaired_successfully = True
                        gate = _collaborative_quality_gate(request.message, content)

                quality_gate_report = _quality_gate_report(
                    initial_gate=initial_gate,
                    final_gate=gate,
                    repair_attempted=repair_attempted,
                    repaired=repaired_successfully,
                    draft_model=draft_model,
                    review_model=review_model,
                    endpoints={
                        "multi_endpoint_enabled": routes.get("enabled"),
                        "draft_endpoint": routes.get("draft_endpoint"),
                        "draft_base_url": draft_base_url,
                        "review_endpoint": routes.get("review_endpoint"),
                        "review_base_url": review_base_url,
                        "repair_endpoint": routes.get("repair_endpoint"),
                        "repair_base_url": repair_base_url,
                        "fast_gpu_pin": routes.get("fast_gpu_pin"),
                        "heavy_gpu_pin": routes.get("heavy_gpu_pin"),
                    },
                )

                first_token_at = time.perf_counter()
                yield _stream_event("delta", {"content": content})
                metrics = _response_metrics(
                    started_at=request_started_at,
                    first_token_at=first_token_at,
                    provider="ollama",
                    model=f"{draft_model} -> {review_model}",
                    user_message=request.message,
                    content=content,
                )
                yield _stream_event("done", {"role": "assistant", "content": content, "ts": time.time(), "response_metrics": metrics.model_dump(), "quality_gate": quality_gate_report})
                return

            if provider == "ollama" and not config.ollama_tools_enabled:
                if not model or model == "stub":
                    raise HTTPException(status_code=400, detail="Ollama provider selected but no model is configured.")
                thread_id = requested_thread_id or session_tracker.get_active_thread(user_id or "")
                if thread_id and user_id:
                    ensure_thread_owner(thread_id, owner_id=user_id)
                short_term = _build_short_term_messages(thread_id, request.message, owner_id=user_id)
                retrieved = _build_retrieval_context(request.message)

                if config.web_enabled:
                    urls = re.findall(r"https?://\\S+", request.message or "")
                    urls = [u.rstrip(").,;!\"'") for u in urls][:3]
                    web_parts: list[str] = []
                    for u in urls:
                        try:
                            res = fetch_text(u, policy=_web_policy())
                            web_parts.append(f"URL: {res.url}\n{res.text[:4000]}")
                        except Exception:
                            continue
                    if web_parts:
                        retrieved = (retrieved + "\n\n" if retrieved else "") + "\n\n".join(web_parts)

                system_prompt = _system_prompt_for_request(response_mode, request.message)
                prompt = _ollama_prompt(system_prompt, retrieved, short_term)
                settings = _read_settings()
                endpoint = getattr(settings, "ollamaDraftEndpoint", "default") if getattr(settings, "ollamaMultiEndpointEnabled", False) else "default"
                base_url = normalize_ollama_base_url(effective_ollama_endpoint_base_url(settings, endpoint))
                timeout_s = effective_ollama_request_timeout_s(settings)
                chunks: list[str] = []
                for chunk in ollama_generate_stream(
                    cfg=OllamaConfig(
                        base_url=base_url,
                        model=model,
                        timeout_s=timeout_s,
                        max_tool_iters=max(1, int(getattr(config, "ollama_tool_max_iters", 4))),
                    ),
                    prompt=prompt,
                ):
                    if first_token_at is None and chunk:
                        first_token_at = time.perf_counter()
                    chunks.append(chunk)
                    yield _stream_event("delta", {"content": chunk})
                content = finalize_response_text("".join(chunks), response_mode=response_mode)
                if not content:
                    raise HTTPException(status_code=502, detail="Ollama returned an empty response.")
                metrics = _response_metrics(
                    started_at=request_started_at,
                    first_token_at=first_token_at,
                    provider=provider,
                    model=model,
                    user_message=request.message,
                    content=content,
                )
                yield _stream_event("done", {"role": "assistant", "content": content, "ts": time.time(), "response_metrics": metrics.model_dump()})
                return

            # Compatibility fallback for OpenAI, stub, and Ollama tool mode. This is not token-streamed,
            # but the frontend still gets a consistent stream protocol.
            response = chat(request, http)
            yield _stream_event("delta", {"content": response.content})
            yield _stream_event(
                "done",
                {
                    "role": response.role,
                    "content": response.content,
                    "ts": response.ts,
                    "retrieved": [chunk.model_dump() for chunk in (response.retrieved or [])],
                    "audit_tail": response.audit_tail or [],
                    "sources": response.sources or [],
                    "verification_level": response.verification_level,
                    "verification": response.verification,
                    "web": response.web,
                    "response_metrics": response.response_metrics.model_dump() if response.response_metrics is not None else None,
                },
            )
        except ProviderError as exc:
            yield _stream_event("error", {"message": str(exc), "detail": provider_error_detail(exc)})
        except HTTPException as exc:
            yield _stream_event("error", {"message": str(exc.detail), "detail": exc.detail, "status_code": exc.status_code})
        except Exception as exc:
            yield _stream_event("error", {"message": str(exc)})

    return StreamingResponse(events(), media_type="application/x-ndjson")

@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http: Request) -> ChatResponse:
    request_started_at = time.perf_counter()
    settings = _read_settings()
    provider = (getattr(settings, "chatProvider", "stub") or "stub").strip().lower()
    model = (getattr(settings, "chatModel", "stub") or "stub").strip()
    response_mode = (request.response_mode or "chat").strip().lower() or "chat"
    user_id = current_user_id(http)
    requested_thread_id = (request.thread_id or "").strip() or None
    if requested_thread_id and user_id:
        thread = ensure_thread_owner(requested_thread_id, owner_id=user_id)
        provider = (thread.chat_provider or provider or "stub").strip().lower()
        model = (thread.chat_model or model or "stub").strip()

    # Prefer AgentX agent loop when available to guarantee a single path:
    # UI -> API -> Agent -> Tools -> Audit -> Memory.
    #
    # We keep the legacy implementation below as a compatibility fallback if AgentX
    # cannot be imported/initialized in this environment.
    if provider == "openai" and not config.openai_api_key:
        raise HTTPException(status_code=400, detail="OpenAI provider selected but AGENTX_OPENAI_API_KEY is not set.")
    if provider == "ollama" and (not model or model == "stub"):
        raise HTTPException(status_code=400, detail="Ollama provider selected but no model is configured.")

    try:
        from agentx.core.unsafe_mode import is_unsafe_enabled, reset_request_context, set_request_context

        inferred_thread_id = requested_thread_id or session_tracker.get_active_thread(user_id or "")
        if inferred_thread_id and user_id:
            ensure_thread_owner(inferred_thread_id, owner_id=user_id)
        h, agent = _get_agent_pair(inferred_thread_id, user=(user_id or "unknown"))
        agent_ctx = getattr(agent, "ctx", None)
        effective_thread_id = inferred_thread_id or getattr(agent_ctx, "web_session_thread_id", None)
        effective_user = (user_id or getattr(agent_ctx, "web_session_user", None) or "unknown")
        backend_unsafe_enabled = bool(effective_thread_id and is_unsafe_enabled(effective_thread_id))
        request_unsafe_enabled = backend_unsafe_enabled if request.unsafe_enabled is None else bool(request.unsafe_enabled and effective_thread_id)
        if agent_ctx is not None:
            setattr(agent_ctx, "web_session_thread_id", effective_thread_id)
            setattr(agent_ctx, "web_session_user", effective_user)
            setattr(agent_ctx, "request_unsafe_enabled", request_unsafe_enabled)
            setattr(agent_ctx, "request_agent_mode", "unsafe" if request_unsafe_enabled else str(getattr(agent_ctx.cfg.agent, "mode", "supervised")))
            setattr(
                agent_ctx,
                "request_artifact_context",
                (
                    ArtifactContext(
                        source=str(request.active_artifact.source or "").strip(),
                        type=str(request.active_artifact.type or "").strip(),
                        language=(str(request.active_artifact.language).strip() if request.active_artifact.language is not None else None),
                        content=(str(request.active_artifact.content) if request.active_artifact.content is not None else None),
                        path=(str(request.active_artifact.path).strip() if request.active_artifact.path is not None else None),
                        dirty=request.active_artifact.dirty,
                        title=(str(request.active_artifact.title).strip() if request.active_artifact.title is not None else None),
                        label=(str(request.active_artifact.label).strip() if request.active_artifact.label is not None else None),
                    )
                    if request.active_artifact is not None
                    else None
                ),
            )
            setattr(agent_ctx, "request_model_behavior_contract", _model_behavior_contract(request.message))
        tokens = set_request_context(thread_id=effective_thread_id, user=effective_user, unsafe_enabled=request_unsafe_enabled)
        handle_cfg = getattr(h, "cfg", None)
        if provider == "ollama" and isinstance(getattr(handle_cfg, "llm", None), dict):
            llm_cfg = handle_cfg.llm
            ollama_cfg = dict(llm_cfg.get("ollama") or {})
            ollama_cfg["base_url"] = effective_ollama_base_url(settings)
            ollama_cfg["timeout_s"] = effective_ollama_request_timeout_s(settings)
            llm_cfg["ollama"] = ollama_cfg
        try:
            res = agent.chat(
                user_message=request.message,
                provider=provider,
                model=model,
                thread_id=effective_thread_id,
                response_mode=response_mode,
            )
        finally:
            reset_request_context(tokens)
        retrieved = [
            RetrievedChunk(
                text=ch.text,
                source_id=ch.source_id,
                ts=float(ch.ts),
                tags=list(ch.tags or []),
                trust=str(ch.trust),
                score=float(ch.score),
            )
            for ch in (res.retrieved or ())
        ]
        content = finalize_response_text(res.text, response_mode=response_mode)
        return ChatResponse(
            content=content,
            ts=time.time(),
            response_metrics=_response_metrics(started_at=request_started_at, provider=provider, model=model, user_message=request.message, content=content),
            retrieved=retrieved,
            audit_tail=h.ctx.audit.tail(limit=50),
            sources=[{"title": str(s.get("title") or ""), "url": str(s.get("url") or ""), "trust": (str(s.get("trust") or "").strip() or "unknown")} for s in (res.sources or ())],
            verification_level=(getattr(res, "verification_level", None).value if getattr(res, "verification_level", None) is not None else None),
            verification=(getattr(res, "verification", None) if getattr(res, "verification", None) is not None else None),
            web=_extract_web_meta(getattr(res, "tool_results", None)),
        )
    except AgentXUnavailable:
        pass
    except ProviderError as e:
        raise _provider_http_exception(e) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AgentX agent error: {e}")

    if provider == "openai":
        thread_id = requested_thread_id or session_tracker.get_active_thread(user_id or "")
        if thread_id and user_id:
            ensure_thread_owner(thread_id, owner_id=user_id)
        short_term = _build_short_term_messages(thread_id, request.message, owner_id=user_id)
        retrieved = _build_retrieval_context(request.message)

        messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    _system_prompt_for_request(response_mode, request.message)
                    + "\nYou may use tools when needed.\n"
                    + "- Use web_search/web_fetch only if AGENTX_WEB_ENABLED=true.\n"
                    + "- Only save to RAG via rag_upsert when the user explicitly asks you to remember something.\n"
                    + "- File-system tools are available only if AGENTX_FS_ENABLED=true. Writes are further gated by AGENTX_FS_WRITE_ENABLED.\n"
                    + "- Never write to drive C: (read-only). Prefer working in non-C drives.\n"
                ),
            }
        ]
        if retrieved:
            messages.append(
                {
                    "role": "system",
                    "content": "Use the retrieved context below if relevant. If it is not relevant, ignore it.\n\n"
                    + retrieved,
                }
            )
        messages.extend(short_term)
        content = finalize_response_text(
            _openai_chat_with_tools(model=model or config.openai_model, messages=messages),
            response_mode=response_mode,
        )
        return ChatResponse(
            content=content,
            ts=time.time(),
            response_metrics=_response_metrics(started_at=request_started_at, provider=provider, model=model, user_message=request.message, content=content),
        )

    if provider == "ollama":
        thread_id = requested_thread_id or session_tracker.get_active_thread(user_id or "")
        if thread_id and user_id:
            ensure_thread_owner(thread_id, owner_id=user_id)
        short_term = _build_short_term_messages(thread_id, request.message, owner_id=user_id)
        retrieved = _build_retrieval_context(request.message)

        if config.ollama_tools_enabled:
            content = _ollama_chat_with_tools(
                short_term=short_term, retrieved=retrieved, user_message=request.message, model=model
            )
        else:
            # Minimal web assist for non-tool models: if the user includes URLs, fetch and include them.
            if config.web_enabled:
                urls = re.findall(r"https?://\\S+", request.message or "")
                urls = [u.rstrip(").,;!\"'") for u in urls][:3]
                web_parts: list[str] = []
                for u in urls:
                    try:
                        res = fetch_text(u, policy=_web_policy())
                        web_parts.append(f"URL: {res.url}\n{res.text[:4000]}")
                    except Exception:
                        continue
                if web_parts:
                    retrieved = (retrieved + "\n\n" if retrieved else "") + "\n\n".join(web_parts)

            system_prompt = _system_prompt_for_request(response_mode, request.message)
            prompt = _ollama_prompt(system_prompt, retrieved, short_term)
            content = _ollama_generate(prompt, model=model)
        if not content:
            raise HTTPException(status_code=502, detail="Ollama returned an empty response.")
        content = finalize_response_text(content, response_mode=response_mode)
        return ChatResponse(
            content=content,
            ts=time.time(),
            response_metrics=_response_metrics(started_at=request_started_at, provider=provider, model=model, user_message=request.message, content=content),
        )

    reply = finalize_response_text(f"AgentX says: {request.message}", response_mode=response_mode)
    return ChatResponse(
        content=reply,
        ts=time.time(),
        response_metrics=_response_metrics(started_at=request_started_at, provider=provider, model=model, user_message=request.message, content=reply),
    )
