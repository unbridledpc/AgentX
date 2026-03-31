from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from sol_api.auth import current_user_id
from sol_api.solv2_bridge import SolV2Unavailable, get_handle
from sol_api.routes.threads import ensure_thread_owner

router = APIRouter(tags=["agent"])


class UnsafeStatusResponse(BaseModel):
    ok: bool = True
    thread_id: str
    unsafe_enabled: bool
    enabled_at: str | None = None
    enabled_by: str | None = None
    reason: str | None = None
    ts: float = Field(default_factory=time.time)


class UnsafeEnableBody(BaseModel):
    reason: str = Field(..., min_length=1)


class UnsafeDisableBody(BaseModel):
    reason: str | None = None


def _to_response(st: Any) -> UnsafeStatusResponse:
    return UnsafeStatusResponse(
        thread_id=str(getattr(st, "thread_id", "") or ""),
        unsafe_enabled=bool(getattr(st, "unsafe_enabled", False)),
        enabled_at=getattr(st, "enabled_at", None),
        enabled_by=getattr(st, "enabled_by", None),
        reason=getattr(st, "reason", None),
    )


@router.get("/agent/unsafe/{thread_id}", response_model=UnsafeStatusResponse)
def get_unsafe_state(thread_id: str, http: Request) -> UnsafeStatusResponse:
    user_id = current_user_id(http)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    ensure_thread_owner(thread_id, owner_id=user_id)
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    from sol.core.unsafe_mode import get_state

    st = get_state(thread_id)
    return _to_response(st)


@router.post("/agent/unsafe/{thread_id}/enable", response_model=UnsafeStatusResponse)
def enable_unsafe_mode(thread_id: str, http: Request, body: UnsafeEnableBody = Body(...)) -> UnsafeStatusResponse:
    user_id = current_user_id(http)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    ensure_thread_owner(thread_id, owner_id=user_id)
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    from sol.core.unsafe_mode import enable

    try:
        st = enable(thread_id, reason=body.reason, user=user_id, cfg=h.cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(st)


@router.post("/agent/unsafe/{thread_id}/disable", response_model=UnsafeStatusResponse)
def disable_unsafe_mode(thread_id: str, http: Request, body: UnsafeDisableBody = Body(...)) -> UnsafeStatusResponse:
    user_id = current_user_id(http)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    ensure_thread_owner(thread_id, owner_id=user_id)
    try:
        h = get_handle()
    except SolV2Unavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    from sol.core.unsafe_mode import disable

    try:
        st = disable(thread_id, reason=(body.reason or None), user=user_id, cfg=h.cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(st)
