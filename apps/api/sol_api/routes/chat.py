from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sol.core.llm import OllamaConfig, ProviderError, ollama_generate, provider_error_detail
from sol.core.response_sanitizer import finalize_response_text

from sol_api.auth import current_user_id
from sol_api.config import config
from sol_api.ollama import normalize_ollama_base_url
from sol_api.fs_access.errors import FsAccessDenied, FsAccessError, FsNotFound, FsTooLarge
from sol_api.fs_access.ops import apply_unified_diff, delete_path, list_dir, mkdir, move_path, read_text, write_text
from sol_api.fs_access.policy import FsPolicy
from sol_api.routes.settings import _read_settings, effective_ollama_base_url, effective_ollama_request_timeout_s
from sol_api.rag.chunking import chunk_text
from sol_api.rag.session import session_tracker
from sol_api.rag.store import RagStore
from sol_api.web_access.errors import WebAccessDenied, WebFetchError
from sol_api.web_access.fetch import fetch_text
from sol_api.web_access.policy import WebPolicy
from sol_api.web_access.search import search as web_search
from sol_api.routes.threads import _read_thread, ensure_thread_owner
from sol_api.solv2_bridge import SolV2Unavailable, get_agent_for_thread, get_handle

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    response_mode: str = "chat"


class RetrievedChunk(BaseModel):
    text: str
    source_id: str
    ts: float
    tags: list[str] = Field(default_factory=list)
    trust: str
    score: float


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
    base_url = normalize_ollama_base_url(effective_ollama_base_url(settings))
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
        raise WebFetchError("RAG is disabled (SOL_RAG_ENABLED=false).")
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
                return {"ok": False, "error": "Web access is disabled (SOL_WEB_ENABLED=false)."}
            return {"ok": True, **_tool_web_search(args)}
        if n == "web_fetch":
            if not config.web_enabled:
                return {"ok": False, "error": "Web access is disabled (SOL_WEB_ENABLED=false)."}
            return {"ok": True, **_tool_web_fetch(args)}
        if n == "rag_upsert":
            if not config.rag_enabled:
                return {"ok": False, "error": "RAG is disabled (SOL_RAG_ENABLED=false)."}
            return {"ok": True, **_tool_rag_upsert(args)}

        if n == "fs_list_dir":
            if not config.fs_enabled:
                return {"ok": False, "error": "File access is disabled (SOL_FS_ENABLED=false)."}
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
                return {"ok": False, "error": "File access is disabled (SOL_FS_ENABLED=false)."}
            return {"ok": True, **read_text(str(args.get("path") or ""), policy=_fs_policy())}

        if n == "fs_write_text":
            if not (config.fs_enabled and config.fs_write_enabled):
                return {"ok": False, "error": "Write access is disabled (SOL_FS_WRITE_ENABLED=false)."}
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
                return {"ok": False, "error": "Write access is disabled (SOL_FS_WRITE_ENABLED=false)."}
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
                return {"ok": False, "error": "Write access is disabled (SOL_FS_WRITE_ENABLED=false)."}
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
                return {"ok": False, "error": "Write access is disabled (SOL_FS_WRITE_ENABLED=false)."}
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
                return {"ok": False, "error": "Delete is disabled (SOL_FS_DELETE_ENABLED=false)."}
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


_RE_OLLAMA_TOOL = re.compile(r"SOL_TOOL_CALL\\s*:\\s*(\\{.*\\})\\s*$", re.DOTALL)


def _parse_ollama_tool_call(text: str) -> tuple[str, dict | None]:
    """Parse a best-effort tool call from an Ollama response.

    Protocol:
    - Either respond normally, OR end the response with:
        SOL_TOOL_CALL: {"name":"fs_read_text","args":{...}}
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
        "You are Sol.",
        "You may use tools when needed.",
        "If you need to use a tool, end your message with exactly one line:",
        'SOL_TOOL_CALL: {"name":"TOOL_NAME","args":{...}}',
        "After the tool result, continue and either call another tool or answer normally.",
        "Never write to drive C: (read-only). Prefer non-C drives.",
    ]
    if not config.fs_enabled:
        system_lines.append("File tools are disabled (SOL_FS_ENABLED=false).")
    if not config.fs_write_enabled:
        system_lines.append("File writes are disabled (SOL_FS_WRITE_ENABLED=false).")
    if not config.fs_delete_enabled:
        system_lines.append("Deletes are disabled (SOL_FS_DELETE_ENABLED=false).")
    if not config.web_enabled:
        system_lines.append("Web tools are disabled (SOL_WEB_ENABLED=false).")
    if not config.rag_enabled:
        system_lines.append("RAG save is disabled (SOL_RAG_ENABLED=false).")

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

    return "Tool loop exceeded SOL_OLLAMA_TOOL_MAX_ITERS."


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
                        "description": "Fetch a URL and extract readable text. Respects SOL_WEB_* policy.",
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
                    "description": "Save text into Sol RAG for later retrieval. Use only when the user asks to remember.",
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
                        "description": "List a directory. Respects SOL_FS_* policy.",
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
                        "description": "Read a UTF-8 text file. Respects SOL_FS_* policy.",
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
                        "description": "Write a UTF-8 text file. Denies writes to drives in SOL_FS_WRITE_DENY_DRIVES (default C).",
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
                        "description": "Apply a unified diff patch. Denies writes to drives in SOL_FS_WRITE_DENY_DRIVES (default C).",
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
                        "description": "Create a directory. Denies writes to drives in SOL_FS_WRITE_DENY_DRIVES (default C).",
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
                        "description": "Move/rename a path. Denies writes to drives in SOL_FS_WRITE_DENY_DRIVES (default C).",
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
                    "description": "Delete a path (recursive optional). Denies deletes to drives in SOL_FS_WRITE_DENY_DRIVES (default C).",
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

    raise HTTPException(status_code=502, detail="OpenAI tool loop exceeded SOL_OPENAI_TOOL_MAX_ITERS.")


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


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http: Request) -> ChatResponse:
    settings = _read_settings()
    provider = (getattr(settings, "chatProvider", "stub") or "stub").strip().lower()
    model = (getattr(settings, "chatModel", "stub") or "stub").strip()
    response_mode = (request.response_mode or "chat").strip().lower() or "chat"
    user_id = current_user_id(http)
    requested_thread_id = (request.thread_id or "").strip() or None
    if requested_thread_id and user_id:
        ensure_thread_owner(requested_thread_id, owner_id=user_id)

    # Prefer SolVersion2 agent loop when available to guarantee a single path:
    # UI -> API -> Agent -> Tools -> Audit -> Memory.
    #
    # We keep the legacy implementation below as a compatibility fallback if SolVersion2
    # cannot be imported/initialized in this environment.
    if provider == "openai" and not config.openai_api_key:
        raise HTTPException(status_code=400, detail="OpenAI provider selected but SOL_OPENAI_API_KEY is not set.")
    if provider == "ollama" and (not model or model == "stub"):
        raise HTTPException(status_code=400, detail="Ollama provider selected but no model is configured.")

    try:
        inferred_thread_id = requested_thread_id or session_tracker.get_active_thread(user_id or "")
        if inferred_thread_id and user_id:
            ensure_thread_owner(inferred_thread_id, owner_id=user_id)
        h, agent = _get_agent_pair(inferred_thread_id, user=(user_id or "unknown"))
        handle_cfg = getattr(h, "cfg", None)
        if provider == "ollama" and isinstance(getattr(handle_cfg, "llm", None), dict):
            llm_cfg = handle_cfg.llm
            ollama_cfg = dict(llm_cfg.get("ollama") or {})
            ollama_cfg["base_url"] = effective_ollama_base_url(settings)
            ollama_cfg["timeout_s"] = effective_ollama_request_timeout_s(settings)
            llm_cfg["ollama"] = ollama_cfg
        res = agent.chat(
            user_message=request.message,
            provider=provider,
            model=model,
            thread_id=inferred_thread_id,
            response_mode=response_mode,
        )
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
        return ChatResponse(
            content=finalize_response_text(res.text, response_mode=response_mode),
            ts=time.time(),
            retrieved=retrieved,
            audit_tail=h.ctx.audit.tail(limit=50),
            sources=[{"title": str(s.get("title") or ""), "url": str(s.get("url") or ""), "trust": (str(s.get("trust") or "").strip() or "unknown")} for s in (res.sources or ())],
            verification_level=(getattr(res, "verification_level", None).value if getattr(res, "verification_level", None) is not None else None),
            verification=(getattr(res, "verification", None) if getattr(res, "verification", None) is not None else None),
            web=_extract_web_meta(getattr(res, "tool_results", None)),
        )
    except SolV2Unavailable:
        pass
    except ProviderError as e:
        raise _provider_http_exception(e) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"SolVersion2 agent error: {e}")

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
                    "You are Sol.\n"
                    "You may use tools when needed.\n"
                    "- Use web_search/web_fetch only if SOL_WEB_ENABLED=true.\n"
                    "- Only save to RAG via rag_upsert when the user explicitly asks you to remember something.\n"
                    "- File-system tools are available only if SOL_FS_ENABLED=true. Writes are further gated by SOL_FS_WRITE_ENABLED.\n"
                    "- Never write to drive C: (read-only). Prefer working in non-C drives.\n"
                ),
            }
        ]
        if response_mode == "spoken":
            messages[0]["content"] += (
                " Spoken mode: answer directly, keep it short, sound natural when read aloud, do not include hidden reasoning,"
                " no markdown, and no bullet lists unless the user explicitly asks for them."
            )
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
        return ChatResponse(content=content, ts=time.time())

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

            system_prompt = "You are Sol."
            if response_mode == "spoken":
                system_prompt += " Spoken mode: answer directly, keep it short, sound natural when read aloud, do not include hidden reasoning, no markdown, and no bullet lists unless the user explicitly asks for them."
            prompt = _ollama_prompt(system_prompt, retrieved, short_term)
            content = _ollama_generate(prompt, model=model)
        if not content:
            raise HTTPException(status_code=502, detail="Ollama returned an empty response.")
        return ChatResponse(content=finalize_response_text(content, response_mode=response_mode), ts=time.time())

    reply = finalize_response_text(f"Sol says: {request.message}", response_mode=response_mode)
    return ChatResponse(content=reply, ts=time.time())
