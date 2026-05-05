from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from agentx_api.config import config
from agentx_api.runtime_guard import request_id_var

router = APIRouter(tags=["runtime"])


class RuntimeDiagnosticsResponse(BaseModel):
    ok: bool
    ts: float
    request_id: str
    config: dict[str, Any]
    warnings: list[str]
    errors: list[str]


@router.get("/runtime/diagnostics", response_model=RuntimeDiagnosticsResponse)
def runtime_diagnostics() -> RuntimeDiagnosticsResponse:
    report = config.runtime_diagnostics()
    return RuntimeDiagnosticsResponse(
        ok=not report["errors"],
        ts=time.time(),
        request_id=request_id_var.get(),
        config=report["config"],
        warnings=report["warnings"],
        errors=report["errors"],
    )
