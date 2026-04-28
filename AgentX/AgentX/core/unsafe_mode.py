from __future__ import annotations

import contextvars
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CURRENT_THREAD_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("agentx_current_thread_id", default=None)
_CURRENT_USER: contextvars.ContextVar[str] = contextvars.ContextVar("agentx_current_user", default="local-user")
_CURRENT_UNSAFE_ENABLED: contextvars.ContextVar[bool | None] = contextvars.ContextVar("agentx_current_unsafe_enabled", default=None)
_UNSET = object()

_LOCK = threading.Lock()


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is not None:
        return value
    if name.startswith("AGENTX_"):
        suffix = name.removeprefix("AGENTX_")
        for legacy_name in (f"SOL_{suffix}", f"NEXAI_{suffix}"):
            legacy_value = os.environ.get(legacy_name)
            if legacy_value is not None:
                return legacy_value
    return None


@dataclass(frozen=True)
class UnsafeState:
    thread_id: str
    unsafe_enabled: bool
    enabled_at: str | None
    enabled_by: str | None
    reason: str | None


_STATE_BY_THREAD: dict[str, UnsafeState] = {}


_SENSITIVE_KEY_RE = re.compile(r"(token|apikey|api_key|password|secret|credential)", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_user() -> str:
    for candidate in (
        _env("AGENTX_PROFILE_ID"),
        os.environ.get("USER"),
        os.environ.get("USERNAME"),
    ):
        text = (candidate or "").strip()
        if text:
            return text
    return "local-user"


def set_request_context(
    *,
    thread_id: str | None,
    user: str | None,
    unsafe_enabled: bool | None | object = _UNSET,
) -> tuple[contextvars.Token, contextvars.Token, contextvars.Token]:
    """Set request/tool execution context for thread-scoped policy checks."""
    t1 = _CURRENT_THREAD_ID.set((thread_id or "").strip() or None)
    t2 = _CURRENT_USER.set((user or "").strip() or _default_user())
    if unsafe_enabled is _UNSET:
        t3 = _CURRENT_UNSAFE_ENABLED.set(_CURRENT_UNSAFE_ENABLED.get())
    else:
        t3 = _CURRENT_UNSAFE_ENABLED.set(None if unsafe_enabled is None else bool(unsafe_enabled))
    return t1, t2, t3


def reset_request_context(tokens: tuple[contextvars.Token, contextvars.Token, contextvars.Token]) -> None:
    t1, t2, t3 = tokens
    _CURRENT_THREAD_ID.reset(t1)
    _CURRENT_USER.reset(t2)
    _CURRENT_UNSAFE_ENABLED.reset(t3)


def current_thread_id() -> str | None:
    return _CURRENT_THREAD_ID.get()


def current_user() -> str:
    return _CURRENT_USER.get()


def is_unsafe_enabled(thread_id: str | None = None) -> bool:
    th = (thread_id or "").strip() or current_thread_id()
    req = _CURRENT_UNSAFE_ENABLED.get()
    if req is not None:
        cur = current_thread_id()
        if not th or (cur and th == cur):
            return bool(req)
    if not th:
        return False
    with _LOCK:
        st = _STATE_BY_THREAD.get(th)
    return bool(st and st.unsafe_enabled)


def get_state(thread_id: str) -> UnsafeState:
    th = (thread_id or "").strip()
    if not th:
        return UnsafeState(thread_id="", unsafe_enabled=False, enabled_at=None, enabled_by=None, reason=None)
    with _LOCK:
        st = _STATE_BY_THREAD.get(th)
    return st or UnsafeState(thread_id=th, unsafe_enabled=False, enabled_at=None, enabled_by=None, reason=None)


def enable(thread_id: str, *, reason: str, user: str | None = None, cfg: Any | None = None) -> UnsafeState:
    th = (thread_id or "").strip()
    rsn = (reason or "").strip()
    if not th:
        raise ValueError("thread_id is required")
    if not rsn:
        raise ValueError("reason is required")
    u = (user or "").strip() or _default_user()
    st = UnsafeState(thread_id=th, unsafe_enabled=True, enabled_at=_now_iso(), enabled_by=u, reason=rsn)
    with _LOCK:
        _STATE_BY_THREAD[th] = st
    audit_event(
        cfg=cfg,
        thread_id=th,
        user=u,
        action_type="enable",
        tool_name=None,
        args_summary="",
        reason=rsn,
        result_status="ok",
    )
    return st


def disable(thread_id: str, *, reason: str | None = None, user: str | None = None, cfg: Any | None = None) -> UnsafeState:
    th = (thread_id or "").strip()
    if not th:
        raise ValueError("thread_id is required")
    u = (user or "").strip() or _default_user()
    with _LOCK:
        prev = _STATE_BY_THREAD.get(th)
        if prev and prev.unsafe_enabled:
            st = UnsafeState(thread_id=th, unsafe_enabled=False, enabled_at=prev.enabled_at, enabled_by=prev.enabled_by, reason=prev.reason)
            _STATE_BY_THREAD[th] = st
        else:
            st = prev or UnsafeState(thread_id=th, unsafe_enabled=False, enabled_at=None, enabled_by=None, reason=None)
            _STATE_BY_THREAD[th] = st

    audit_event(
        cfg=cfg,
        thread_id=th,
        user=u,
        action_type="disable",
        tool_name=None,
        args_summary="",
        reason=(reason or "").strip() or "",
        result_status="ok",
    )
    return st


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = str(k)
            if _SENSITIVE_KEY_RE.search(key):
                out[key] = "<redacted>"
            else:
                out[key] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, tuple):
        return [_redact(x) for x in obj]
    return obj


def summarize_args(args: Any, *, max_chars: int = 2000) -> str:
    safe = _redact(args)
    try:
        text = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    except Exception:
        try:
            text = str(safe)
        except Exception:
            text = "<unserializable>"
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 40)] + f"...<truncated len={len(text)}>"
    return text


def _audit_path(cfg: Any | None) -> Path:
    override = (_env("AGENTX_UNSAFE_AUDIT_PATH") or "").strip()
    if override:
        return Path(override)
    if cfg is not None and getattr(cfg, "paths", None) is not None:
        base = Path(getattr(cfg.paths, "audit_dir", cfg.paths.data_dir))
    else:
        runtime_root = Path(_env("AGENTX_RUNTIME_ROOT") or Path.home() / ".local" / "share" / "agentx")
        base = runtime_root / "audit"
    return base / "unsafe.log"


def audit_event(
    *,
    cfg: Any | None,
    thread_id: str,
    user: str,
    action_type: str,
    tool_name: str | None,
    args_summary: str,
    reason: str,
    result_status: str,
) -> None:
    path = _audit_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": _now_iso(),
        "thread_id": str(thread_id or ""),
        "user": str((user or "").strip() or _default_user()),
        "action_type": str(action_type or ""),
        "tool_name": str(tool_name or "") if tool_name else None,
        "args_summary": str(args_summary or ""),
        "reason": str(reason or ""),
        "result_status": str(result_status or ""),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


UNSAFE_BLOCK_MESSAGE = "Destructive action blocked. Enable UNSAFE mode for this thread."
