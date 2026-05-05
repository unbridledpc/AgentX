#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"

echo "[INFO] Installing AgentX chat archive workspace patch in $ROOT"

if [ -x ./.venv/bin/pip ]; then
  ./.venv/bin/pip install python-multipart >/tmp/agentx-python-multipart.log 2>&1 || {
    cat /tmp/agentx-python-multipart.log
    exit 1
  }
  echo "[OK] python-multipart installed/available"
fi

mkdir -p AgentX/agentx/workbench
cp -a payload/workbench/* AgentX/agentx/workbench/
touch AgentX/agentx/workbench/__init__.py

echo "[OK] Installed workbench archive workspace module"

ROUTES="apps/api/agentx_api/routes/workbench.py"
if [ ! -f "$ROUTES" ]; then
  mkdir -p apps/api/agentx_api/routes
  cat > "$ROUTES" <<'PY'
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1/workbench", tags=["workbench"])
PY
fi

cp -a "$ROUTES" "$ROUTES.bak-chat-workspace-$(date +%Y%m%d-%H%M%S)"

if ! grep -q "CHAT_ARCHIVE_WORKSPACE_PATCH_START" "$ROUTES"; then
cat >> "$ROUTES" <<'PY'

# CHAT_ARCHIVE_WORKSPACE_PATCH_START
from typing import Any as _Any
from fastapi import HTTPException as _HTTPException
from fastapi.responses import FileResponse as _FileResponse
from pydantic import BaseModel as _BaseModel

from agentx.workbench.archive_workspace import (
    attach_thread_workspace as _attach_thread_workspace,
    export_thread_workspace as _export_thread_workspace,
    get_thread_workspace as _get_thread_workspace,
    read_thread_report as _read_thread_report,
    read_workspace_file as _read_workspace_file,
    workspace_file_tree as _workspace_file_tree,
    write_workspace_file as _write_workspace_file,
)

class _WorkspaceAttachBody(_BaseModel):
    thread_id: str
    project_id: str
    archive_name: str | None = None
    extracted_dir: str
    analysis_dir: str | None = None
    final_report: str | None = None
    metadata: dict[str, _Any] | None = None

class _WorkspaceWriteBody(_BaseModel):
    path: str
    text: str

@router.post("/thread/attach")
def attach_archive_workspace_to_thread(body: _WorkspaceAttachBody):
    try:
        return _attach_thread_workspace(
            body.thread_id,
            project_id=body.project_id,
            archive_name=body.archive_name,
            extracted_dir=body.extracted_dir,
            analysis_dir=body.analysis_dir,
            final_report=body.final_report,
            metadata=body.metadata,
        )
    except Exception as exc:
        raise _HTTPException(status_code=400, detail=str(exc))

@router.get("/thread/{thread_id}")
def get_archive_workspace_for_thread(thread_id: str):
    ws = _get_thread_workspace(thread_id)
    if not ws:
        raise _HTTPException(status_code=404, detail="No archive workspace attached to this thread")
    return ws

@router.get("/thread/{thread_id}/tree")
def get_archive_workspace_tree(thread_id: str, max_files: int = 5000):
    try:
        return _workspace_file_tree(thread_id, max_files=max_files)
    except Exception as exc:
        raise _HTTPException(status_code=404, detail=str(exc))

@router.get("/thread/{thread_id}/file")
def get_archive_workspace_file(thread_id: str, path: str, max_bytes: int = 1000000):
    try:
        return _read_workspace_file(thread_id, path, max_bytes=max_bytes)
    except PermissionError as exc:
        raise _HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise _HTTPException(status_code=404, detail=str(exc))

@router.post("/thread/{thread_id}/file")
def put_archive_workspace_file(thread_id: str, body: _WorkspaceWriteBody):
    try:
        return _write_workspace_file(thread_id, body.path, body.text)
    except PermissionError as exc:
        raise _HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise _HTTPException(status_code=400, detail=str(exc))

@router.get("/thread/{thread_id}/report")
def get_archive_workspace_report(thread_id: str):
    try:
        return _read_thread_report(thread_id)
    except Exception as exc:
        raise _HTTPException(status_code=404, detail=str(exc))

@router.get("/thread/{thread_id}/export")
def export_archive_workspace_for_thread(thread_id: str):
    try:
        result = _export_thread_workspace(thread_id)
        return _FileResponse(result["archive_path"], filename=result["archive_path"].split("/")[-1])
    except Exception as exc:
        raise _HTTPException(status_code=404, detail=str(exc))
# CHAT_ARCHIVE_WORKSPACE_PATCH_END
PY
  echo "[OK] Added thread workspace endpoints to $ROUTES"
else
  echo "[SKIP] Thread workspace endpoints already present in $ROUTES"
fi

# Best-effort patch: after existing import archive analysis, attach to thread if request has thread_id.
# This is intentionally conservative; if your route uses a different signature, manual integration may still be needed.
if grep -q "def .*import.*archive" "$ROUTES" && ! grep -q "thread_id.*Form" "$ROUTES"; then
  echo "[NOTE] Existing import-archive route may need manual thread_id integration if the frontend does not call /thread/attach."
fi

# Ensure API service can import both packages.
sudo mkdir -p /etc/systemd/system/agentx-api.service.d
sudo tee /etc/systemd/system/agentx-api.service.d/20-pythonpath.conf >/dev/null <<EOF
[Service]
Environment="PYTHONPATH=$ROOT/AgentX:$ROOT/apps/api"
EOF
sudo systemctl daemon-reload

PYTHONPATH="$ROOT/AgentX:$ROOT/apps/api" python3 - <<'PY'
from agentx.workbench.archive_workspace import attach_thread_workspace, workspace_file_tree
print("[OK] archive workspace module import works")
PY

sudo systemctl restart agentx-api
sudo systemctl restart agentx-web || true

echo "[OK] Installed chat archive workspace patch"
echo "[NEXT] Hard refresh the browser with Ctrl+F5"
