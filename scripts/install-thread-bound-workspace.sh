#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$HOME/projects/AgentX}"
cd "$ROOT"
echo "[INFO] Installing AgentX thread-bound archive workspace patch in $ROOT"

if [ ! -d "apps/api/agentx_api" ] || [ ! -d "AgentX/agentx" ]; then
  echo "[ERROR] Run this from the AgentX project root or pass the root path." >&2
  exit 1
fi

mkdir -p AgentX/agentx/workbench apps/api/agentx_api/routes

# Ensure required upload dependency exists.
if [ -x ./.venv/bin/pip ]; then
  ./.venv/bin/pip show python-multipart >/dev/null 2>&1 || ./.venv/bin/pip install python-multipart
fi

TS="$(date +%Y%m%d-%H%M%S)"
[ -f apps/api/agentx_api/routes/chat.py ] && cp -a apps/api/agentx_api/routes/chat.py "apps/api/agentx_api/routes/chat.py.bak-thread-workspace-$TS"
[ -f apps/api/agentx_api/routes/workbench.py ] && cp -a apps/api/agentx_api/routes/workbench.py "apps/api/agentx_api/routes/workbench.py.bak-thread-workspace-$TS"
[ -f AgentX/agentx/workbench/archive_workspace.py ] && cp -a AgentX/agentx/workbench/archive_workspace.py "AgentX/agentx/workbench/archive_workspace.py.bak-thread-workspace-$TS" || true
[ -f AgentX/agentx/workbench/playground.py ] && cp -a AgentX/agentx/workbench/playground.py "AgentX/agentx/workbench/playground.py.bak-thread-workspace-$TS" || true

# Install backend workspace persistence module.
cat > AgentX/agentx/workbench/archive_workspace.py <<'PY'
from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

WORKSPACE_ROOT_DEFAULT = Path("work/workbench")
MAPPING_NAME = "thread_workspaces.json"


def _root(workspace_root: str | Path | None = None) -> Path:
    return Path(workspace_root or WORKSPACE_ROOT_DEFAULT).expanduser().resolve(False)


def _mapping_path(workspace_root: str | Path | None = None) -> Path:
    root = _root(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    return root / MAPPING_NAME


def _read_mapping(workspace_root: str | Path | None = None) -> dict[str, Any]:
    p = _mapping_path(workspace_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_mapping(data: dict[str, Any], workspace_root: str | Path | None = None) -> None:
    p = _mapping_path(workspace_root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _safe_rel(path: str) -> str:
    rel = str(path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel == "." or ".." in Path(rel).parts:
        raise ValueError("Unsafe workspace relative path")
    return rel


def attach_workspace_to_thread(
    thread_id: str,
    *,
    project: dict[str, Any] | None = None,
    project_id: str | None = None,
    workspace_path: str | Path | None = None,
    report_path: str | Path | None = None,
    inventory_path: str | Path | None = None,
    original_archive: str | Path | None = None,
    summary: dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    tid = str(thread_id or "").strip()
    if not tid:
        raise ValueError("thread_id is required to attach a workspace")
    project = dict(project or {})
    root = workspace_path or project.get("root")
    if not root:
        raise ValueError("workspace_path/project.root is required")
    root_p = Path(root).expanduser().resolve(False)
    if report_path is None:
        report_path = root_p / "analysis" / "final_report.md"
    if inventory_path is None:
        inventory_path = root_p / "analysis" / "inventory.json"
    if original_archive is None:
        original_archive = project.get("original_archive") or project.get("original_zip")
    record = {
        "thread_id": tid,
        "project_id": project_id or project.get("project_id") or root_p.name,
        "workspace_path": str(root_p),
        "extracted_dir": str(project.get("extracted_dir") or root_p / "extracted"),
        "analysis_dir": str(project.get("analysis_dir") or root_p / "analysis"),
        "report_path": str(Path(report_path).expanduser().resolve(False)),
        "inventory_path": str(Path(inventory_path).expanduser().resolve(False)),
        "original_archive": str(original_archive or ""),
        "summary": dict(summary or {}),
        "attached_at": time.time(),
    }
    data = _read_mapping(workspace_root)
    data[tid] = record
    _write_mapping(data, workspace_root)
    return record


def get_thread_workspace(thread_id: str, *, workspace_root: str | Path | None = None) -> dict[str, Any] | None:
    tid = str(thread_id or "").strip()
    if not tid:
        return None
    data = _read_mapping(workspace_root)
    rec = data.get(tid)
    return rec if isinstance(rec, dict) else None


def _load_inventory(record: dict[str, Any]) -> dict[str, Any]:
    p = Path(str(record.get("inventory_path") or ""))
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _read_report(record: dict[str, Any], limit: int = 12000) -> str:
    p = Path(str(record.get("report_path") or ""))
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def _top_paths(inventory: dict[str, Any], max_paths: int = 120) -> list[str]:
    entries = inventory.get("entries") or []
    if not isinstance(entries, list):
        return []
    important_tokens = (
        "readme", "config", "settings", "main", "app", "server", "startup", "login", "player", "game", "storage",
        "actions", "events", "globalevents", "creaturescripts", "monster", "sql", "schema", "patch", "docker", "compose",
    )
    scored: list[tuple[int, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        low = path.lower()
        score = 0
        for token in important_tokens:
            if token in low:
                score += 4
        if low.endswith((".py", ".lua", ".xml", ".sql", ".cpp", ".h", ".hpp", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".md")):
            score += 1
        score += max(0, 8 - low.count("/"))
        scored.append((score, path))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [p for _, p in scored[:max_paths]]


def build_thread_workspace_context(thread_id: str, query: str | None = None, *, owner_id: str | None = None, workspace_root: str | Path | None = None) -> str:
    record = get_thread_workspace(thread_id, workspace_root=workspace_root)
    if not record:
        return ""
    inventory = _load_inventory(record)
    report = _read_report(record)
    top_paths = _top_paths(inventory, 80)
    summary = record.get("summary") or {}
    lines = [
        "THREAD-BOUND ARCHIVE WORKSPACE CONTEXT",
        "A user-uploaded server/project archive is attached to this chat thread. Use it when the user asks about the uploaded zip/archive/server/files. Do not claim you cannot access the uploaded archive.",
        f"Project ID: {record.get('project_id')}",
        f"Workspace path: {record.get('workspace_path')}",
        f"Extracted sandbox path: {record.get('extracted_dir')}",
        f"Report path: {record.get('report_path')}",
        "Safety: this is an extracted sandbox copy, not live server files. Proposed edits must target this sandbox workspace unless explicitly exported/applied later.",
        "",
        "Summary:",
        f"- Total files: {summary.get('total_files', inventory.get('total_files', 'unknown'))}",
        f"- Analyzed files: {summary.get('analyzed_files', 'unknown')}",
        f"- Syntax errors: {summary.get('syntax_errors', 'unknown')}",
        f"- Risk findings: {summary.get('risk_findings', 'unknown')}",
        f"- Conversion findings: {summary.get('conversion_findings', 'unknown')}",
        "",
        "Important/top file paths:",
    ]
    lines.extend(f"- {path}" for path in top_paths[:80])
    if report:
        lines.extend(["", "Archive analysis report excerpt:", report])
    return "\n".join(lines).strip()


# Compatibility name used by older patches.
def get_thread_workspace_context(*args, **kwargs) -> str:
    return build_thread_workspace_context(*args, **kwargs)


def list_thread_workspace_tree(thread_id: str, *, workspace_root: str | Path | None = None, max_entries: int = 5000) -> dict[str, Any]:
    rec = get_thread_workspace(thread_id, workspace_root=workspace_root)
    if not rec:
        raise FileNotFoundError("No workspace attached to this thread")
    extracted = Path(str(rec.get("extracted_dir") or ""))
    if not extracted.exists():
        raise FileNotFoundError("Workspace extracted directory not found")
    entries = []
    for path in extracted.rglob("*"):
        if len(entries) >= max_entries:
            break
        try:
            rel = path.relative_to(extracted).as_posix()
        except Exception:
            continue
        entries.append({"path": rel, "type": "dir" if path.is_dir() else "file", "size": path.stat().st_size if path.is_file() else 0})
    return {"thread_id": thread_id, "workspace": rec, "entries": entries, "truncated": len(entries) >= max_entries}


def read_thread_workspace_file(thread_id: str, rel_path: str, *, workspace_root: str | Path | None = None, max_bytes: int = 400_000) -> dict[str, Any]:
    rec = get_thread_workspace(thread_id, workspace_root=workspace_root)
    if not rec:
        raise FileNotFoundError("No workspace attached to this thread")
    extracted = Path(str(rec.get("extracted_dir") or "")).resolve(False)
    target = (extracted / _safe_rel(rel_path)).resolve(False)
    target.relative_to(extracted)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("File not found in workspace")
    data = target.read_bytes()[:max_bytes]
    return {"path": _safe_rel(rel_path), "size": target.stat().st_size, "content": data.decode("utf-8", errors="replace"), "truncated": target.stat().st_size > max_bytes}


def write_thread_workspace_file(thread_id: str, rel_path: str, content: str, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    rec = get_thread_workspace(thread_id, workspace_root=workspace_root)
    if not rec:
        raise FileNotFoundError("No workspace attached to this thread")
    extracted = Path(str(rec.get("extracted_dir") or "")).resolve(False)
    target = (extracted / _safe_rel(rel_path)).resolve(False)
    target.relative_to(extracted)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_suffix(target.suffix + f".bak-{int(time.time())}")
        shutil.copy2(target, backup)
    target.write_text(str(content), encoding="utf-8")
    return {"ok": True, "path": _safe_rel(rel_path), "bytes": target.stat().st_size}


def export_thread_workspace(thread_id: str, *, workspace_root: str | Path | None = None) -> dict[str, Any]:
    rec = get_thread_workspace(thread_id, workspace_root=workspace_root)
    if not rec:
        raise FileNotFoundError("No workspace attached to this thread")
    root = Path(str(rec.get("workspace_path") or "")).resolve(False)
    extracted = Path(str(rec.get("extracted_dir") or "")).resolve(False)
    out = root / f"{rec.get('project_id') or 'workspace'}-edited.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in extracted.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(extracted).as_posix())
    return {"ok": True, "path": str(out), "bytes": out.stat().st_size}
PY

# Ensure playground has both import functions.
python3 - <<'PY'
from pathlib import Path
p = Path("AgentX/agentx/workbench/playground.py")
p.parent.mkdir(parents=True, exist_ok=True)
if p.exists():
    text = p.read_text()
else:
    text = "from __future__ import annotations\nfrom pathlib import Path\nfrom typing import Any\nfrom agentx.workbench.analyzer import analyze_archive\n\n"
if "def import_and_analyze_zip" not in text:
    text += "\ndef import_and_analyze_zip(zip_path, workspace_root, *, name=None, project_name=None, **kwargs):\n    return analyze_archive(zip_path, workspace_root, name or project_name)\n"
if "def import_and_analyze_archive" not in text:
    text += "\ndef import_and_analyze_archive(archive_path, workspace_root, *, name=None, project_name=None, **kwargs):\n    return import_and_analyze_zip(archive_path, workspace_root, name=(name or project_name))\n"
p.write_text(text)
PY

# Install a full safe workbench route implementation.
cat > apps/api/agentx_api/routes/workbench.py <<'PY'
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agentx.workbench.archive_workspace import (
    attach_workspace_to_thread,
    export_thread_workspace,
    get_thread_workspace,
    get_thread_workspace_context,
    list_thread_workspace_tree,
    read_thread_workspace_file,
    write_thread_workspace_file,
)
from agentx.workbench.playground import import_and_analyze_archive, import_and_analyze_zip

router = APIRouter(prefix="/workbench", tags=["workbench"])

WORKSPACE_ROOT = Path("work/workbench")
SUPPORTED = {".zip", ".rar", ".7z", ".tar", ".tgz", ".gz"}


class WorkbenchImportZipRequest(BaseModel):
    zip_path: str = Field(..., description="Path to an already-uploaded ZIP/archive on the AgentX VM")
    workspace: str = Field(default="work/workbench", description="Sandbox workspace root")
    name: str = Field(default="", description="Optional project name/id prefix")
    thread_id: str | None = Field(default=None, description="Optional chat thread to attach this workspace to")


class WorkspaceWriteRequest(BaseModel):
    path: str
    content: str


def _summary_from_result(result: dict[str, Any]) -> dict[str, Any]:
    summary = dict(result.get("summary") or {})
    inv = result.get("inventory") or {}
    if isinstance(inv, dict):
        summary.setdefault("total_files", inv.get("total_files"))
        summary.setdefault("counts_by_kind", inv.get("counts_by_kind"))
    return summary


def _attach_if_requested(thread_id: str | None, result: dict[str, Any]) -> dict[str, Any] | None:
    tid = (thread_id or "").strip()
    if not tid:
        return None
    project = dict(result.get("project") or result)
    record = attach_workspace_to_thread(
        tid,
        project=project,
        workspace_path=project.get("root"),
        report_path=result.get("final_report_path") or (Path(str(project.get("analysis_dir") or "")) / "final_report.md"),
        inventory_path=(Path(str(project.get("analysis_dir") or "")) / "inventory.json"),
        original_archive=project.get("original_archive") or project.get("original_zip"),
        summary=_summary_from_result(result),
        workspace_root=WORKSPACE_ROOT,
    )
    return record


@router.post("/import-zip")
def import_zip(payload: WorkbenchImportZipRequest) -> dict[str, Any]:
    try:
        result = import_and_analyze_zip(payload.zip_path, payload.workspace, name=(payload.name.strip() or None))
        record = _attach_if_requested(payload.thread_id, result)
        if record:
            result["thread_workspace"] = record
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workbench import failed: {exc}") from exc


@router.post("/import-archive")
def import_archive(
    file: UploadFile = File(...),
    project_name: str = Form(""),
    thread_id: str = Form(""),
) -> dict[str, Any]:
    filename = file.filename or "archive.zip"
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in (".zip", ".rar", ".7z", ".tar", ".tgz", ".tar.gz")):
        raise HTTPException(status_code=400, detail="Unsupported archive type. Use .zip, .rar, .7z, .tar, .tgz, or .tar.gz")
    try:
        with tempfile.TemporaryDirectory(prefix="agentx-upload-") as tmp:
            upload_path = Path(tmp) / Path(filename).name
            with upload_path.open("wb") as out:
                shutil.copyfileobj(file.file, out)
            result = import_and_analyze_archive(upload_path, WORKSPACE_ROOT, name=(project_name.strip() or None))
        record = _attach_if_requested(thread_id, result)
        if record:
            result["thread_workspace"] = record
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workbench archive import failed: {exc}") from exc


@router.get("/report")
def report(path: str) -> dict[str, Any]:
    report_path = Path(path).expanduser().resolve(False)
    if not report_path.exists() or not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    if report_path.name != "final_report.md":
        raise HTTPException(status_code=400, detail="Only final_report.md is exposed by this helper endpoint")
    return {"path": str(report_path), "content": report_path.read_text(encoding="utf-8", errors="replace")}


@router.get("/thread/{thread_id}")
def thread_workspace(thread_id: str) -> dict[str, Any]:
    rec = get_thread_workspace(thread_id, workspace_root=WORKSPACE_ROOT)
    if not rec:
        raise HTTPException(status_code=404, detail="No workspace attached to this thread")
    return {"ok": True, "workspace": rec, "context": get_thread_workspace_context(thread_id, workspace_root=WORKSPACE_ROOT)}


@router.get("/thread/{thread_id}/tree")
def thread_tree(thread_id: str) -> dict[str, Any]:
    try:
        return list_thread_workspace_tree(thread_id, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/thread/{thread_id}/file")
def thread_file(thread_id: str, path: str) -> dict[str, Any]:
    try:
        return read_thread_workspace_file(thread_id, path, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/thread/{thread_id}/file")
def thread_file_write(thread_id: str, payload: WorkspaceWriteRequest) -> dict[str, Any]:
    try:
        return write_thread_workspace_file(thread_id, payload.path, payload.content, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/thread/{thread_id}/report")
def thread_report(thread_id: str) -> dict[str, Any]:
    rec = get_thread_workspace(thread_id, workspace_root=WORKSPACE_ROOT)
    if not rec:
        raise HTTPException(status_code=404, detail="No workspace attached to this thread")
    path = Path(str(rec.get("report_path") or ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return {"path": str(path), "content": path.read_text(encoding="utf-8", errors="replace")}


@router.get("/thread/{thread_id}/export")
def thread_export(thread_id: str) -> dict[str, Any]:
    try:
        return export_thread_workspace(thread_id, workspace_root=WORKSPACE_ROOT)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
PY

# Patch chat.py safely.
python3 - <<'PY'
from pathlib import Path
p = Path("apps/api/agentx_api/routes/chat.py")
text = p.read_text()
# Remove prior broken insertion lines regardless of indentation.
text = "\n".join([line for line in text.splitlines() if "retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message" not in line]) + "\n"

imp = "from agentx.workbench.archive_workspace import get_thread_workspace_context\n"
if imp not in text:
    anchor = "from agentx_api.agentx_bridge import AgentXUnavailable, get_agent_for_thread, get_handle\n"
    if anchor in text:
        text = text.replace(anchor, anchor + imp)
    else:
        text = imp + text

helper = r'''

def _append_workspace_context(retrieved: str, thread_id: str | None, user_message: str, *, owner_id: str | None = None) -> str:
    if not thread_id:
        return retrieved
    try:
        workspace_context = get_thread_workspace_context(thread_id, query=user_message, owner_id=owner_id)
    except Exception:
        workspace_context = ""
    if not workspace_context:
        return retrieved
    return (retrieved + "\n\n" if retrieved else "") + workspace_context


def _with_workspace_user_message(user_message: str, thread_id: str | None, *, owner_id: str | None = None) -> str:
    if not thread_id:
        return user_message
    try:
        workspace_context = get_thread_workspace_context(thread_id, query=user_message, owner_id=owner_id)
    except Exception:
        workspace_context = ""
    if not workspace_context:
        return user_message
    return (
        f"{user_message}\n\n"
        "Attached archive workspace context for this chat thread:\n"
        f"{workspace_context}\n\n"
        "Use this uploaded archive workspace when answering. Do not claim you cannot access uploaded files."
    )
'''
if "def _append_workspace_context(" not in text:
    anchor = "def _build_retrieval_context(query: str) -> str:\n    return _retrieve_rag(query)[0]\n"
    if anchor in text:
        text = text.replace(anchor, anchor + helper)
    else:
        text = text.replace("router = APIRouter(tags=[\"chat\"])\n", "router = APIRouter(tags=[\"chat\"])\n" + helper)

# Add workspace context after every RAG retrieval assignment if not already followed nearby.
old = "retrieved, rag_sources, rag_hit_count = _retrieve_rag(request.message)"
new = old + "\n                retrieved = _append_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)"
# Use indentation-aware replacement for 16-space blocks.
text = text.replace("                " + old + "\n\n                if config.web_enabled:", "                " + new + "\n\n                if config.web_enabled:")
text = text.replace("                " + old + "\n                draft_base_url", "                " + new + "\n                draft_base_url")
text = text.replace("        " + old + "\n\n        messages", "        " + old + "\n        retrieved = _append_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n\n        messages")
text = text.replace("        " + old + "\n\n        if config.ollama_tools_enabled:", "        " + old + "\n        retrieved = _append_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n\n        if config.ollama_tools_enabled:")
text = text.replace("                " + old + "\n                system_prompt", "                " + old + "\n                retrieved = _append_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n                system_prompt")

# Patch AgentX agent path so the core agent receives workspace context too.
needle = "                user_message=request.message,\n                provider=provider,"
if needle in text:
    text = text.replace(needle, "                user_message=_with_workspace_user_message(request.message, effective_thread_id, owner_id=effective_user),\n                provider=provider,")

p.write_text(text)
PY

# Patch frontend client/App to pass thread_id with archive upload.
python3 - <<'PY'
from pathlib import Path
client = Path("AgentXWeb/src/api/client.ts")
if client.exists():
    text = client.read_text()
    if "function importWorkbenchArchive(file: File, projectName?: string, threadId?: string" not in text:
        text = text.replace(
            "export async function importWorkbenchArchive(file: File, projectName?: string): Promise<WorkbenchImportResponse> {",
            "export async function importWorkbenchArchive(file: File, projectName?: string, threadId?: string | null): Promise<WorkbenchImportResponse> {",
        )
        text = text.replace(
            "  if (projectName?.trim()) form.append(\"project_name\", projectName.trim());\n  const res = await fetch(`${config.apiBase}/v1/workbench/import-archive`, {",
            "  if (projectName?.trim()) form.append(\"project_name\", projectName.trim());\n  if (threadId?.trim()) form.append(\"thread_id\", threadId.trim());\n  const res = await fetch(`${config.apiBase}/v1/workbench/import-archive`, {",
        )
    client.write_text(text)

app = Path("AgentXWeb/src/ui/App.tsx")
if app.exists():
    text = app.read_text()
    text = text.replace("const result = await importWorkbenchArchive(file, name);", "const result = await importWorkbenchArchive(file, name, activeThread?.id ?? null);")
    # Ensure callback dependencies include activeThread?.id where needed.
    text = text.replace("}, [setSystemMessage]);", "}, [activeThread?.id, setSystemMessage]);", 1)
    app.write_text(text)
PY

# Validate Python syntax/imports.
python3 -m py_compile apps/api/agentx_api/routes/chat.py apps/api/agentx_api/routes/workbench.py AgentX/agentx/workbench/archive_workspace.py AgentX/agentx/workbench/playground.py
PYTHONPATH="$ROOT/AgentX:$ROOT/apps/api" ./.venv/bin/python - <<'PY'
from agentx_api.app import create_app
from agentx.workbench.archive_workspace import attach_workspace_to_thread, get_thread_workspace_context
app = create_app()
print('[OK] API imports and app creates')
PY

# Rebuild WebUI if source dependencies exist.
if [ -f AgentXWeb/package.json ]; then
  (cd AgentXWeb && npm run build)
fi

sudo systemctl restart agentx-api
sudo systemctl restart agentx-web || true
sleep 2
curl -fsS http://127.0.0.1:8000/v1/status >/tmp/agentx-status.json && echo "[OK] API status reachable" || (echo "[WARN] API status not reachable; check journalctl -u agentx-api -n 120 --no-pager" >&2; exit 1)

echo "[OK] Thread-bound archive workspace patch installed. Hard refresh the WebUI with Ctrl+F5."
