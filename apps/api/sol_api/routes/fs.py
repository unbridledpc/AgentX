from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from sol_api.auth import current_user_id
from sol_api.config import config
from sol_api.fs_access.errors import FsAccessDenied, FsAccessError, FsNotFound, FsTooLarge
from sol_api.fs_access.ops import apply_unified_diff, delete_path, list_dir, mkdir, move_path, read_text, write_text
from sol_api.fs_access.policy import FsPolicy, validate_path
from sol_api.rag.session import session_tracker
from sol_api.solv2_bridge import SolV2Unavailable, get_handle
from sol_api.routes.threads import ensure_thread_owner

router = APIRouter(tags=["fs"])


def _infer_thread_id(thread_id: str | None, req: Request) -> str | None:
    user_id = current_user_id(req)
    th = (thread_id or "").strip() or None
    if th:
        if user_id:
            ensure_thread_owner(th, owner_id=user_id)
        return th
    active = session_tracker.get_active_thread(user_id or "")
    if active and user_id:
        ensure_thread_owner(active, owner_id=user_id)
    return active


def _unsafe_enabled(thread_id: str | None) -> tuple[bool, object | None]:
    try:
        h = get_handle()
    except SolV2Unavailable:
        return False, None
    try:
        from sol.core.unsafe_mode import is_unsafe_enabled

        return bool(is_unsafe_enabled(thread_id)), h.cfg
    except Exception:
        return False, h.cfg


def _policy(thread_id: str | None) -> FsPolicy:
    unsafe, _cfg = _unsafe_enabled(thread_id)
    if unsafe:
        return FsPolicy(
            enabled=True,
            allow_all_paths=True,
            allowed_roots=tuple(),
            allow_write=True,
            allow_delete=True,
            deny_write_drives=tuple(),
            max_read_bytes=config.fs_max_read_bytes,
            max_write_bytes=config.fs_max_write_bytes,
        )
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


class FsStatus(BaseModel):
    enabled: bool
    allow_all_paths: bool
    allow_write: bool
    allow_delete: bool
    deny_write_drives: list[str]
    allowed_roots: list[str]
    max_read_bytes: int
    max_write_bytes: int


@router.get("/fs/status", response_model=FsStatus)
def fs_status() -> FsStatus:
    # Status is global config; unsafe mode is per-thread and not reflected here.
    p = FsPolicy(
        enabled=config.fs_enabled,
        allow_all_paths=config.fs_allow_all_paths,
        allowed_roots=tuple(config.fs_allowed_roots),
        allow_write=config.fs_write_enabled,
        allow_delete=config.fs_delete_enabled,
        deny_write_drives=tuple(config.fs_write_deny_drives),
        max_read_bytes=config.fs_max_read_bytes,
        max_write_bytes=config.fs_max_write_bytes,
    )
    return FsStatus(
        enabled=p.enabled,
        allow_all_paths=p.allow_all_paths,
        allow_write=p.allow_write,
        allow_delete=p.allow_delete,
        deny_write_drives=[str(d) for d in p.deny_write_drives],
        allowed_roots=[str(r) for r in p.allowed_roots],
        max_read_bytes=p.max_read_bytes,
        max_write_bytes=p.max_write_bytes,
    )


class FsReadIn(BaseModel):
    path: str = Field(..., min_length=1)
    thread_id: str | None = None


class FsWriteIn(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""
    create: bool = True
    backup: bool = True
    thread_id: str | None = None
    reason: str | None = None


class FsListIn(BaseModel):
    path: str = Field(..., min_length=1)
    recursive: bool = False
    max_entries: int = 500
    thread_id: str | None = None


class FsPatchIn(BaseModel):
    patch_text: str = Field(..., min_length=1)
    backup: bool = True
    thread_id: str | None = None
    reason: str | None = None


class FsMkdirIn(BaseModel):
    path: str = Field(..., min_length=1)
    parents: bool = True
    exist_ok: bool = True
    thread_id: str | None = None


class FsDeleteIn(BaseModel):
    path: str = Field(..., min_length=1)
    recursive: bool = False
    thread_id: str | None = None
    reason: str | None = None


class FsMoveIn(BaseModel):
    src: str = Field(..., min_length=1)
    dst: str = Field(..., min_length=1)
    overwrite: bool = False
    backup: bool = True
    thread_id: str | None = None
    reason: str | None = None


def _handle_error(e: Exception) -> None:
    if isinstance(e, FsAccessDenied):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, FsNotFound):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, FsTooLarge):
        raise HTTPException(status_code=413, detail=str(e))
    if isinstance(e, FsAccessError):
        raise HTTPException(status_code=400, detail=str(e))
    raise HTTPException(status_code=500, detail=str(e))


@router.post("/fs/read_text")
def fs_read_text(body: FsReadIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        return read_text(body.path, policy=_policy(thread_id))
    except Exception as e:
        _handle_error(e)
        return {}


@router.post("/fs/write_text")
def fs_write_text(body: FsWriteIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        unsafe, cfg = _unsafe_enabled(thread_id)
        pol = _policy(thread_id)

        overwriting = False
        try:
            p = validate_path(Path(body.path), policy=pol, for_write=True)
            overwriting = p.exists() or p.is_symlink()
        except Exception:
            overwriting = False

        if overwriting and not unsafe:
            msg = "Destructive action blocked. Enable UNSAFE mode for this thread."
            try:
                from sol.core.unsafe_mode import audit_event, summarize_args

                audit_event(
                    cfg=cfg,
                    thread_id=str(thread_id or ""),
                    user=(current_user_id(http) or "unknown"),
                    action_type="tool_call",
                    tool_name="fs.write_text",
                    args_summary=summarize_args({"path": body.path, "create": bool(body.create), "backup": bool(body.backup)}),
                    reason=(body.reason or "").strip(),
                    result_status="blocked",
                )
            except Exception:
                pass
            raise FsAccessDenied(msg)

        out = write_text(body.path, body.content, policy=pol, create=body.create, backup=body.backup)
        if overwriting:
            try:
                from sol.core.unsafe_mode import audit_event, summarize_args

                audit_event(
                    cfg=cfg,
                    thread_id=str(thread_id or ""),
                    user=(current_user_id(http) or "unknown"),
                    action_type="tool_call",
                    tool_name="fs.write_text",
                    args_summary=summarize_args({"path": body.path, "create": bool(body.create), "backup": bool(body.backup)}),
                    reason=(body.reason or "").strip(),
                    result_status="ok",
                )
            except Exception:
                pass
        return out
    except Exception as e:
        _handle_error(e)
        return {}


@router.post("/fs/list_dir")
def fs_list_dir(body: FsListIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        return list_dir(body.path, policy=_policy(thread_id), recursive=body.recursive, max_entries=body.max_entries)
    except Exception as e:
        _handle_error(e)
        return {}


@router.post("/fs/apply_patch")
def fs_apply_patch(body: FsPatchIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        unsafe, cfg = _unsafe_enabled(thread_id)
        if not unsafe:
            msg = "Destructive action blocked. Enable UNSAFE mode for this thread."
            try:
                from sol.core.unsafe_mode import audit_event, summarize_args

                audit_event(
                    cfg=cfg,
                    thread_id=str(thread_id or ""),
                    user=(current_user_id(http) or "unknown"),
                    action_type="tool_call",
                    tool_name="patch_apply",
                    args_summary=summarize_args({"backup": bool(body.backup)}),
                    reason=(body.reason or "").strip(),
                    result_status="blocked",
                )
            except Exception:
                pass
            raise FsAccessDenied(msg)

        out = apply_unified_diff(body.patch_text, policy=_policy(thread_id), backup=body.backup)
        try:
            from sol.core.unsafe_mode import audit_event, summarize_args

            audit_event(
                cfg=cfg,
                thread_id=str(thread_id or ""),
                user=(current_user_id(http) or "unknown"),
                action_type="tool_call",
                tool_name="patch_apply",
                args_summary=summarize_args({"backup": bool(body.backup)}),
                reason=(body.reason or "").strip(),
                result_status="ok",
            )
        except Exception:
            pass
        return out
    except Exception as e:
        _handle_error(e)
        return {}


@router.post("/fs/mkdir")
def fs_mkdir(body: FsMkdirIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        return mkdir(body.path, policy=_policy(thread_id), parents=body.parents, exist_ok=body.exist_ok)
    except Exception as e:
        _handle_error(e)
        return {}


@router.post("/fs/delete")
def fs_delete(body: FsDeleteIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        unsafe, cfg = _unsafe_enabled(thread_id)
        if not unsafe:
            msg = "Destructive action blocked. Enable UNSAFE mode for this thread."
            try:
                from sol.core.unsafe_mode import audit_event, summarize_args

                audit_event(
                    cfg=cfg,
                    thread_id=str(thread_id or ""),
                    user=(current_user_id(http) or "unknown"),
                    action_type="tool_call",
                    tool_name="fs.delete",
                    args_summary=summarize_args({"path": body.path, "recursive": bool(body.recursive)}),
                    reason=(body.reason or "").strip(),
                    result_status="blocked",
                )
            except Exception:
                pass
            raise FsAccessDenied(msg)

        out = delete_path(body.path, policy=_policy(thread_id), recursive=body.recursive)
        try:
            from sol.core.unsafe_mode import audit_event, summarize_args

            audit_event(
                cfg=cfg,
                thread_id=str(thread_id or ""),
                user=(current_user_id(http) or "unknown"),
                action_type="tool_call",
                tool_name="fs.delete",
                args_summary=summarize_args({"path": body.path, "recursive": bool(body.recursive)}),
                reason=(body.reason or "").strip(),
                result_status="ok",
            )
        except Exception:
            pass
        return out
    except Exception as e:
        _handle_error(e)
        return {}


@router.post("/fs/move")
def fs_move(body: FsMoveIn, http: Request) -> dict:
    try:
        thread_id = _infer_thread_id(body.thread_id, http)
        unsafe, cfg = _unsafe_enabled(thread_id)
        destructive = str(body.src).strip() != str(body.dst).strip()
        if destructive and not unsafe:
            msg = "Destructive action blocked. Enable UNSAFE mode for this thread."
            try:
                from sol.core.unsafe_mode import audit_event, summarize_args

                audit_event(
                    cfg=cfg,
                    thread_id=str(thread_id or ""),
                    user=(current_user_id(http) or "unknown"),
                    action_type="tool_call",
                    tool_name="fs.move",
                    args_summary=summarize_args({"src": body.src, "dst": body.dst, "overwrite": bool(body.overwrite), "backup": bool(body.backup)}),
                    reason=(body.reason or "").strip(),
                    result_status="blocked",
                )
            except Exception:
                pass
            raise FsAccessDenied(msg)

        out = move_path(body.src, body.dst, policy=_policy(thread_id), overwrite=body.overwrite, backup=body.backup)
        if destructive:
            try:
                from sol.core.unsafe_mode import audit_event, summarize_args

                audit_event(
                cfg=cfg,
                thread_id=str(thread_id or ""),
                user=(current_user_id(http) or "unknown"),
                action_type="tool_call",
                    tool_name="fs.move",
                    args_summary=summarize_args({"src": body.src, "dst": body.dst, "overwrite": bool(body.overwrite), "backup": bool(body.backup)}),
                    reason=(body.reason or "").strip(),
                    result_status="ok",
                )
            except Exception:
                pass
        return out
    except Exception as e:
        _handle_error(e)
        return {}
