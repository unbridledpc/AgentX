from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class SolV2Unavailable(RuntimeError):
    pass


def _repo_root() -> Path:
    app_root = (os.environ.get("SOL_APP_ROOT") or "").strip()
    if app_root:
        return Path(app_root).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _solv2_root() -> Path:
    return _repo_root() / "SolVersion2"


@dataclass(frozen=True)
class SolV2Handle:
    cfg: Any
    agent: Any
    tools: Any
    ctx: Any
    started_at: float


_LOCK = threading.Lock()
_HANDLE: SolV2Handle | None = None
_INIT_ERROR: str | None = None
_SESSION_WEB_ALLOWED: dict[tuple[str, str], set[str]] = {}


def _audit_agent_info(*, handle: SolV2Handle, summary: str, reason: str, meta: dict[str, Any] | None, success: bool, error: str | None) -> None:
    from sol.core.audit import AuditEvent

    ok, err = handle.ctx.audit.ensure_writable()
    if not ok:
        raise SolV2Unavailable(f"SolVersion2 audit log not writable: {err}")
    a_ok, a_err = handle.ctx.audit.append(
        AuditEvent(
            ts=time.time(),
            mode=str(handle.cfg.agent.mode),
            event="agent_info",
            tool="agent",
            args=meta or {},
            reason=reason,
            duration_ms=None,
            success=success,
            summary=summary,
            error=error,
            invocation_id=None,
        )
    )
    if not a_ok:
        raise SolV2Unavailable(f"SolVersion2 audit append failed: {a_err}")


def _with_cwd(path: Path) -> Callable[[], None]:
    prev = os.getcwd()
    os.chdir(str(path))

    def restore() -> None:
        os.chdir(prev)

    return restore


def get_handle() -> SolV2Handle:
    global _HANDLE, _INIT_ERROR
    with _LOCK:
        if _HANDLE is not None:
            return _HANDLE
        if _INIT_ERROR is not None:
            raise SolV2Unavailable(_INIT_ERROR)

        root = _solv2_root()
        if not root.exists():
            _INIT_ERROR = f"SolVersion2 folder not found at {root}"
            raise SolV2Unavailable(_INIT_ERROR)

        # Ensure the SolVersion2 package root is importable (contains `sol/`).
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            restore = _with_cwd(root)
            try:
                from sol.runtime.bootstrap import build_runtime_services_from_config
            finally:
                restore()

            def confirm(_: str) -> bool:
                # The UI is inherently supervised (a user clicked "Send"). This bridge is localhost-only
                # and still enforces SolVersion2 filesystem policy + journaling. Treat a user-initiated
                # request as confirmation for tools that require it.
                return True

            restore = _with_cwd(root)
            try:
                services = build_runtime_services_from_config(config_path=str(_config_path()), confirm=confirm)
            finally:
                restore()
            _HANDLE = SolV2Handle(cfg=services.cfg, agent=services.agent, tools=services.tools, ctx=services.ctx, started_at=time.time())
            return _HANDLE
        except SolV2Unavailable:
            raise
        except Exception as e:
            tb = traceback.format_exc(limit=50)
            _INIT_ERROR = f"Failed to initialize SolVersion2: {e}\n{tb}"
            raise SolV2Unavailable(_INIT_ERROR)


def _config_path() -> Path:
    override = (os.environ.get("SOL_CONFIG_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _solv2_root() / "config" / "sol.toml"


def _replace_or_insert_managed_block(text: str, *, block: str) -> str:
    begin = "# BEGIN SOL MANAGED WEB POLICY"
    end = "# END SOL MANAGED WEB POLICY"
    if begin in text and end in text:
        pre, rest = text.split(begin, 1)
        _mid, post = rest.split(end, 1)
        return pre.rstrip() + "\n" + begin + "\n" + block.rstrip() + "\n" + end + "\n" + post.lstrip()

    # Replace existing [web.policy] section if present; otherwise append a managed block.
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        if line.strip() == "[web.policy]" and not replaced:
            # Skip until next section header.
            replaced = True
            out.append(begin)
            out.extend(block.rstrip().splitlines())
            out.append(end)
            i += 1
            while i < len(lines) and not (lines[i].strip().startswith("[") and lines[i].strip().endswith("]")):
                i += 1
            continue
        out.append(line)
        i += 1
    if not replaced:
        out.append("")
        out.append(begin)
        out.extend(block.rstrip().splitlines())
        out.append(end)
    return "\n".join(out).rstrip() + "\n"


def _session_key(*, user: str | None, thread_id: str | None) -> tuple[str, str] | None:
    th = (thread_id or "").strip()
    if not th:
        return None
    return ((user or "").strip().lower(), th)


def get_session_overrides_count(*, thread_id: str | None = None, user: str | None = None) -> int:
    key = _session_key(user=user, thread_id=thread_id)
    if key is None:
        return sum(len(v) for v in _SESSION_WEB_ALLOWED.values())
    return len(_SESSION_WEB_ALLOWED.get(key, set()))


def get_session_allowed_domains(thread_id: str | None, *, user: str | None) -> frozenset[str]:
    key = _session_key(user=user, thread_id=thread_id)
    if key is None:
        return frozenset()
    return frozenset(sorted(_SESSION_WEB_ALLOWED.get(key, set())))


def session_allow_domain(*, thread_id: str, domain: str, reason: str, client_host: str | None, user: str | None) -> None:
    th = (thread_id or "").strip()
    dom = (domain or "").strip().lower()
    key = _session_key(user=user, thread_id=th)
    if key is None or not dom:
        raise SolV2Unavailable("thread_id and domain are required.")
    h = get_handle()
    _SESSION_WEB_ALLOWED.setdefault(key, set()).add(dom)
    _audit_agent_info(
        handle=h,
        summary="web_policy_session_allow",
        reason=reason,
        meta={"thread_id": th, "domain": dom, "client_host": client_host, "user": (user or "").strip().lower()},
        success=True,
        error=None,
    )


def session_clear(*, thread_id: str, reason: str, client_host: str | None, user: str | None) -> None:
    th = (thread_id or "").strip()
    key = _session_key(user=user, thread_id=th)
    if key is None:
        raise SolV2Unavailable("thread_id is required.")
    h = get_handle()
    removed = sorted(_SESSION_WEB_ALLOWED.pop(key, set()))
    _audit_agent_info(
        handle=h,
        summary="web_policy_session_clear",
        reason=reason,
        meta={"thread_id": th, "removed": removed, "client_host": client_host, "user": (user or "").strip().lower()},
        success=True,
        error=None,
    )


def update_web_policy(
    *,
    allow_all_hosts: bool | None,
    allowed_domains_add: list[str],
    allowed_domains_remove: list[str],
    allowed_host_suffixes_add: list[str],
    allowed_host_suffixes_remove: list[str],
    denied_domains_add: list[str],
    denied_domains_remove: list[str],
    reason: str,
    client_host: str | None,
) -> dict[str, Any]:
    h = get_handle()
    path = _config_path()
    if not path.exists():
        raise SolV2Unavailable(f"SolVersion2 config not found: {path}")

    # Load existing config through SolVersion2 to get current policy values.
    restore = _with_cwd(_solv2_root())
    try:
        from sol.config import load_config
        cfg = load_config(str(path))
    finally:
        restore()

    cur_allow_all = bool(getattr(cfg.web, "policy_allow_all_hosts", False))
    cur_allowed_domains = set(getattr(cfg.web, "policy_allowed_domains", ()) or ())
    cur_allowed_suffixes = set(getattr(cfg.web, "policy_allowed_host_suffixes", ()) or ())
    cur_denied_domains = set(getattr(cfg.web, "policy_denied_domains", ()) or ())

    if allow_all_hosts is not None:
        cur_allow_all = bool(allow_all_hosts)
    for d in allowed_domains_add:
        if d:
            cur_allowed_domains.add(d)
    for d in allowed_domains_remove:
        cur_allowed_domains.discard(d)
    for s in allowed_host_suffixes_add:
        if s:
            cur_allowed_suffixes.add(s)
    for s in allowed_host_suffixes_remove:
        cur_allowed_suffixes.discard(s)
    for d in denied_domains_add:
        if d:
            cur_denied_domains.add(d)
    for d in denied_domains_remove:
        cur_denied_domains.discard(d)

    block = "\n".join(
        [
            "[web.policy]",
            f"allow_all_hosts = {'true' if cur_allow_all else 'false'}",
            f"allowed_suffixes = {sorted(cur_allowed_suffixes)!r}".replace("'", "\""),
            f"allowed_domains = {sorted(cur_allowed_domains)!r}".replace("'", "\""),
            f"denied_domains = {sorted(cur_denied_domains)!r}".replace("'", "\""),
        ]
    )

    before = path.read_text(encoding="utf-8", errors="replace")
    after = _replace_or_insert_managed_block(before, block=block)
    if after == before:
        return {"changed": False}

    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(after, encoding="utf-8")

    # Validate load before replacing.
    restore = _with_cwd(_solv2_root())
    try:
        from sol.config import load_config as _load

        _ = _load(str(tmp))
    finally:
        restore()

    tmp.replace(path)

    # Reload handle so new policy takes effect in tools immediately.
    with _LOCK:
        global _HANDLE, _INIT_ERROR
        _HANDLE = None
        _INIT_ERROR = None
    h2 = get_handle()

    _audit_agent_info(
        handle=h2,
        summary="web_policy_updated",
        reason=reason,
        meta={
            "client_host": client_host,
            "allow_all_hosts": cur_allow_all,
            "allowed_domains": sorted(cur_allowed_domains),
            "allowed_suffixes": sorted(cur_allowed_suffixes),
            "allowed_host_suffixes": sorted(cur_allowed_suffixes),
            "denied_domains": sorted(cur_denied_domains),
        },
        success=True,
        error=None,
    )
    return {
        "changed": True,
        "allow_all_hosts": cur_allow_all,
        "allowed_domains": sorted(cur_allowed_domains),
        "allowed_suffixes": sorted(cur_allowed_suffixes),
        "allowed_host_suffixes": sorted(cur_allowed_suffixes),
        "denied_domains": sorted(cur_denied_domains),
    }


def get_agent_for_thread(thread_id: str | None, *, user: str | None = None) -> tuple[SolV2Handle, Any]:
    """Return a per-request Agent whose context includes per-thread session web allow overrides."""
    h = get_handle()
    restore = _with_cwd(_solv2_root())
    try:
        from sol.core.agent import Agent
        from sol.core.context import SolContext
        from sol.core.journal import Journal
    finally:
        restore()
    session = get_session_allowed_domains(thread_id, user=user)
    ctx = SolContext(
        cfg=h.cfg,
        journal=Journal(h.cfg),
        audit=h.ctx.audit,
        confirm=h.ctx.confirm,
        web_session_thread_id=thread_id,
        web_session_user=(user or None),
        web_session_allowed_domains=session,
    )
    ctx.runtime = getattr(h.ctx, "runtime", None)
    ctx.plugin_manager = getattr(h.ctx, "plugin_manager", None)
    ctx.skill_manager = getattr(h.ctx, "skill_manager", None)
    ctx.hint_store = getattr(h.ctx, "hint_store", None)
    ctx.job_store = getattr(h.ctx, "job_store", None)
    ctx.working_memory_manager = getattr(h.ctx, "working_memory_manager", None)
    if ctx.working_memory_manager is not None:
        ctx.working_memory = ctx.working_memory_manager.for_scope(user_id=(user or None), thread_id=thread_id)
    agent = Agent.create(ctx=ctx, tools=h.tools)
    return h, agent
