from __future__ import annotations

import json
import shutil
import tempfile
import time
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
import subprocess
import sys
import xml.etree.ElementTree as ET


class WorkbenchValidateRequest(BaseModel):
    path: str
    content: str | None = None

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
    print(f"[WORKBENCH DEBUG] import_archive filename={file.filename!r} project_name={project_name!r} thread_id={thread_id!r}", flush=True)
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




def _upload_project_dirs() -> list[Path]:
    imports = WORKSPACE_ROOT / "imports"
    if not imports.exists():
        return []
    return sorted([p for p in imports.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)


def _load_thread_workspace_mapping() -> dict[str, Any]:
    mapping = WORKSPACE_ROOT / "thread_workspaces.json"
    if not mapping.exists():
        return {}
    try:
        data = json.loads(mapping.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _upload_record(project_dir: Path) -> dict[str, Any]:
    project_id = project_dir.name
    analysis_dir = project_dir / "analysis"
    extracted_dir = project_dir / "extracted"
    original_dir = project_dir / "original"
    report_path = analysis_dir / "final_report.md"
    inventory_path = analysis_dir / "inventory.json"
    summary_path = analysis_dir / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            summary = {}
    original_archive = ""
    if original_dir.exists():
        files = [p for p in original_dir.iterdir() if p.is_file()]
        if files:
            original_archive = str(files[0].resolve(False))
    thread_id = ""
    for tid, rec in _load_thread_workspace_mapping().items():
        if not isinstance(rec, dict):
            continue
        if Path(str(rec.get("workspace_path") or "")).resolve(False) == project_dir.resolve(False):
            thread_id = str(tid)
            break
    return {
        "project_id": project_id,
        "thread_id": thread_id,
        "workspace_path": str(project_dir.resolve(False)),
        "extracted_dir": str(extracted_dir.resolve(False)),
        "analysis_dir": str(analysis_dir.resolve(False)),
        "report_path": str(report_path.resolve(False)),
        "inventory_path": str(inventory_path.resolve(False)),
        "original_archive": original_archive,
        "summary": summary,
        "created_at": project_dir.stat().st_mtime,
        "attached_at": _load_thread_workspace_mapping().get(thread_id, {}).get("attached_at") if thread_id else None,
    }


def _project_dir_or_404(project_id: str) -> Path:
    safe = Path(project_id).name
    p = WORKSPACE_ROOT / "imports" / safe
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Workspace upload not found")
    return p


@router.get("/uploads")
def list_uploads() -> dict[str, Any]:
    uploads = [_upload_record(p) for p in _upload_project_dirs()]
    return {"ok": True, "uploads": uploads}


@router.get("/uploads/{project_id}")
def get_upload(project_id: str) -> dict[str, Any]:
    return {"ok": True, "upload": _upload_record(_project_dir_or_404(project_id))}


@router.get("/uploads/{project_id}/tree")
def get_upload_tree(project_id: str, max_entries: int = 5000) -> dict[str, Any]:
    root = _project_dir_or_404(project_id)
    extracted = root / "extracted"
    if not extracted.exists():
        raise HTTPException(status_code=404, detail="Extracted directory not found")
    entries = []
    for path in extracted.rglob("*"):
        if len(entries) >= max_entries:
            break
        try:
            rel = path.relative_to(extracted).as_posix()
        except Exception:
            continue
        entries.append({"path": rel, "type": "dir" if path.is_dir() else "file", "size": path.stat().st_size if path.is_file() else 0})
    return {"ok": True, "project_id": project_id, "entries": entries, "truncated": len(entries) >= max_entries}


@router.get("/uploads/{project_id}/report")
def get_upload_report(project_id: str) -> dict[str, Any]:
    p = _project_dir_or_404(project_id) / "analysis" / "final_report.md"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return {"ok": True, "path": str(p.resolve(False)), "content": p.read_text(encoding="utf-8", errors="replace")}


@router.delete("/uploads/{project_id}")
def delete_upload(project_id: str) -> dict[str, Any]:
    p = _project_dir_or_404(project_id)
    mapping_path = WORKSPACE_ROOT / "thread_workspaces.json"
    if mapping_path.exists():
        data = _load_thread_workspace_mapping()
        data = {tid: rec for tid, rec in data.items() if Path(str((rec or {}).get("workspace_path") or "")).resolve(False) != p.resolve(False)}
        mapping_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    shutil.rmtree(p)
    return {"ok": True, "deleted": project_id}


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




def _workspace_record_for_thread_validate(thread_id: str) -> dict:
    # Prefer existing helper names when available. This patch intentionally avoids
    # assuming the exact internal API beyond the thread_workspaces.json file.
    base = Path("work/workbench/thread_workspaces.json")
    if not base.exists():
        raise HTTPException(status_code=404, detail="No thread workspace mapping found")
    try:
        data = json.loads(base.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read thread workspace mapping: {exc}")
    record = data.get(thread_id)
    if not record:
        raise HTTPException(status_code=404, detail="No workspace attached to this thread")
    return record


def _safe_workspace_file_validate(thread_id: str, rel_path: str) -> tuple[Path, Path, dict]:
    record = _workspace_record_for_thread_validate(thread_id)
    root_raw = record.get("extracted_dir") or record.get("root") or record.get("workspace_path")
    if not root_raw:
        raise HTTPException(status_code=404, detail="Workspace has no extracted_dir/root path")
    root = Path(root_raw).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes workspace sandbox")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found in workspace")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    return root, target, record


def _run_validation_command(cmd: list[str], *, cwd: Path | None = None, input_text: str | None = None, timeout: int = 20) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-12000:],
            "command": cmd,
        }
    except FileNotFoundError as exc:
        return {"ok": None, "exit_code": None, "stdout": "", "stderr": str(exc), "command": cmd, "skipped": True}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "exit_code": None, "stdout": (exc.stdout or "")[-12000:], "stderr": f"Validation timed out after {timeout}s\n" + (exc.stderr or "")[-12000:], "command": cmd, "timeout": True}


def _validate_content_for_path(target: Path, rel_path: str, content: str | None) -> dict:
    suffix = target.suffix.lower()
    language = suffix.lstrip(".") or "unknown"
    source_text = content
    if source_text is None:
        try:
            source_text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {
                "ok": None,
                "language": language,
                "kind": "binary_or_non_utf8",
                "message": "File is not UTF-8 text; validation skipped.",
                "checks": [],
            }

    checks: list[dict] = []

    if suffix == ".py":
        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as tmp:
            tmp.write(source_text)
            tmp_path = Path(tmp.name)
        try:
            res = _run_validation_command([sys.executable, "-m", "py_compile", str(tmp_path)])
            res["name"] = "python py_compile"
            checks.append(res)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    elif suffix == ".json":
        try:
            json.loads(source_text)
            checks.append({"name": "json parse", "ok": True, "exit_code": 0, "stdout": "JSON parsed successfully.", "stderr": "", "command": ["python", "json.loads"]})
        except Exception as exc:
            checks.append({"name": "json parse", "ok": False, "exit_code": 1, "stdout": "", "stderr": str(exc), "command": ["python", "json.loads"]})
    elif suffix == ".xml":
        try:
            ET.fromstring(source_text)
            checks.append({"name": "xml parse", "ok": True, "exit_code": 0, "stdout": "XML parsed successfully.", "stderr": "", "command": ["python", "xml.etree.ElementTree.fromstring"]})
        except Exception as exc:
            checks.append({"name": "xml parse", "ok": False, "exit_code": 1, "stdout": "", "stderr": str(exc), "command": ["python", "xml.etree.ElementTree.fromstring"]})
    elif suffix in {".sh", ".bash"}:
        res = _run_validation_command(["bash", "-n", str(target)]) if content is None else None
        if content is not None:
            with tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8", delete=False) as tmp:
                tmp.write(source_text)
                tmp_path = Path(tmp.name)
            try:
                res = _run_validation_command(["bash", "-n", str(tmp_path)])
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        res["name"] = "bash syntax"
        checks.append(res)
    elif suffix == ".lua":
        # Prefer luac/lua if installed; otherwise return a clear skipped result.
        res = _run_validation_command(["luac", "-p", str(target)]) if content is None else None
        if content is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".lua", encoding="utf-8", delete=False) as tmp:
                tmp.write(source_text)
                tmp_path = Path(tmp.name)
            try:
                res = _run_validation_command(["luac", "-p", str(tmp_path)])
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        if res.get("skipped"):
            res = {"name": "lua syntax", "ok": None, "exit_code": None, "stdout": "", "stderr": "luac not installed; Lua syntax validation skipped.", "command": ["luac", "-p"], "skipped": True}
        else:
            res["name"] = "lua syntax"
        checks.append(res)
    else:
        checks.append({"name": "text validation", "ok": None, "exit_code": None, "stdout": "No validator configured for this file type.", "stderr": "", "command": [], "skipped": True})

    failing = [c for c in checks if c.get("ok") is False]
    passing = [c for c in checks if c.get("ok") is True]
    skipped = [c for c in checks if c.get("ok") is None]
    overall = False if failing else (True if passing else None)
    return {
        "ok": overall,
        "language": language,
        "kind": "syntax_validation",
        "message": "Validation passed." if overall is True else ("Validation failed." if overall is False else "Validation skipped/no validator available."),
        "checks": checks,
        "path": rel_path,
    }


@router.post("/thread/{thread_id}/validate")
def validate_thread_workspace_file(thread_id: str, request: WorkbenchValidateRequest) -> dict[str, Any]:
    rel_path = (request.path or "").strip().lstrip("/")
    if not rel_path:
        raise HTTPException(status_code=400, detail="path is required")
    _, target, record = _safe_workspace_file_validate(thread_id, rel_path)
    result = _validate_content_for_path(target, rel_path, request.content)
    result["project_id"] = record.get("project_id")
    result["file_size"] = target.stat().st_size
    return result



# --- Workspace patch history + rollback endpoints ---
# These endpoints are intentionally sandbox-scoped. They only read/write files
# inside the attached extracted workspace and use backups created by the
# existing sandbox file write endpoint when available.
from datetime import datetime as _agentx_dt
import json as _agentx_json
import shutil as _agentx_shutil
from pathlib import Path as _AgentXPath
from pydantic import BaseModel as _AgentXBaseModel

class WorkspaceRestoreRequest(_AgentXBaseModel):
    backup_path: str

class WorkspacePatchHistoryNoteRequest(_AgentXBaseModel):
    path: str
    action: str = "apply"
    validation: dict | None = None
    backup_path: str | None = None
    message: str | None = None


def _agentx_history_path_for_record(record: dict) -> _AgentXPath:
    workspace = _AgentXPath(record.get("workspace_path") or record.get("root") or "")
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace path missing")
    history_dir = workspace / "analysis"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / "patch_history.json"


def _agentx_read_patch_history(record: dict) -> list[dict]:
    path = _agentx_history_path_for_record(record)
    if not path.exists():
        return []
    try:
        data = _agentx_json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _agentx_write_patch_history(record: dict, entries: list[dict]) -> None:
    path = _agentx_history_path_for_record(record)
    path.write_text(_agentx_json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")


def _agentx_workspace_record_for_history(thread_id: str) -> dict:
    # Prefer existing helpers when present in this file.
    for name in ("_workspace_record_for_thread_validate", "_workspace_record_for_thread", "workspace_record_for_thread"):
        fn = globals().get(name)
        if callable(fn):
            record = fn(thread_id)
            if record:
                return record
    # Fallback to thread_workspaces.json.
    root = _AgentXPath.cwd()
    mapping = root / "work" / "workbench" / "thread_workspaces.json"
    if mapping.exists():
        data = _agentx_json.loads(mapping.read_text(encoding="utf-8"))
        record = data.get(thread_id)
        if record:
            return record
    raise HTTPException(status_code=404, detail="No workspace attached to this thread")


def _agentx_safe_workspace_target(record: dict, rel_path: str) -> tuple[_AgentXPath, _AgentXPath]:
    extracted = _AgentXPath(record.get("extracted_dir") or record.get("root") or "")
    if not extracted:
        raise HTTPException(status_code=404, detail="Workspace extracted directory missing")
    extracted = extracted.resolve()
    rel = _AgentXPath(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="Invalid workspace path")
    target = (extracted / rel).resolve()
    try:
        target.relative_to(extracted)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return extracted, target


def _agentx_guess_backup_path(record: dict, rel_path: str) -> str | None:
    _, target = _agentx_safe_workspace_target(record, rel_path)
    parent = target.parent
    if not parent.exists():
        return None
    patterns = [
        f"{target.name}.bak*",
        f"{target.name}.backup*",
        f".{target.name}.bak*",
    ]
    found = []
    for pat in patterns:
        found.extend(parent.glob(pat))
    found = [x for x in found if x.is_file()]
    if not found:
        return None
    found.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return str(found[0])


def _agentx_record_patch_history_entry(thread_id: str, req: WorkspacePatchHistoryNoteRequest) -> dict:
    record = _agentx_workspace_record_for_history(thread_id)
    _, target = _agentx_safe_workspace_target(record, req.path)
    entry = {
        "id": f"patch-{int(_agentx_dt.utcnow().timestamp() * 1000)}",
        "thread_id": thread_id,
        "project_id": record.get("project_id"),
        "path": req.path,
        "action": req.action or "apply",
        "ts": _agentx_dt.utcnow().timestamp(),
        "timestamp": _agentx_dt.utcnow().isoformat(timespec="seconds") + "Z",
        "target_path": str(target),
        "backup_path": req.backup_path or _agentx_guess_backup_path(record, req.path),
        "validation": req.validation or {},
        "message": req.message or "Sandbox patch applied.",
    }
    entries = _agentx_read_patch_history(record)
    entries.insert(0, entry)
    _agentx_write_patch_history(record, entries[:500])
    return entry


@router.get("/thread/{thread_id}/patch-history")
def get_thread_patch_history(thread_id: str) -> dict:
    record = _agentx_workspace_record_for_history(thread_id)
    return {"ok": True, "thread_id": thread_id, "history": _agentx_read_patch_history(record)}


@router.post("/thread/{thread_id}/patch-history")
def note_thread_patch_history(thread_id: str, req: WorkspacePatchHistoryNoteRequest) -> dict:
    return {"ok": True, "entry": _agentx_record_patch_history_entry(thread_id, req)}


@router.post("/thread/{thread_id}/restore")
def restore_thread_workspace_file(thread_id: str, req: WorkspaceRestoreRequest) -> dict:
    record = _agentx_workspace_record_for_history(thread_id)
    backup = _AgentXPath(req.backup_path).expanduser().resolve()
    workspace = _AgentXPath(record.get("workspace_path") or "").resolve()
    extracted = _AgentXPath(record.get("extracted_dir") or "").resolve()
    if not backup.exists() or not backup.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")
    # Backup must live inside this workspace folder.
    try:
        backup.relative_to(workspace)
    except ValueError:
        raise HTTPException(status_code=400, detail="Backup path is outside this workspace")

    history = _agentx_read_patch_history(record)
    match = next((e for e in history if str(e.get("backup_path") or "") == str(backup)), None)
    if not match:
        raise HTTPException(status_code=404, detail="Backup is not present in this workspace patch history")
    rel_path = match.get("path") or ""
    _, target = _agentx_safe_workspace_target(record, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Backup current state before restore.
    restore_backup = None
    if target.exists():
        stamp = _agentx_dt.utcnow().strftime("%Y%m%d-%H%M%S")
        restore_backup = target.with_name(f"{target.name}.pre-restore-{stamp}.bak")
        _agentx_shutil.copy2(target, restore_backup)
    _agentx_shutil.copy2(backup, target)
    restore_entry = {
        "id": f"restore-{int(_agentx_dt.utcnow().timestamp() * 1000)}",
        "thread_id": thread_id,
        "project_id": record.get("project_id"),
        "path": rel_path,
        "action": "restore",
        "ts": _agentx_dt.utcnow().timestamp(),
        "timestamp": _agentx_dt.utcnow().isoformat(timespec="seconds") + "Z",
        "target_path": str(target),
        "backup_path": str(backup),
        "pre_restore_backup_path": str(restore_backup) if restore_backup else None,
        "validation": {},
        "message": "Restored sandbox file from patch-history backup.",
    }
    history.insert(0, restore_entry)
    _agentx_write_patch_history(record, history[:500])
    return {"ok": True, "restored": restore_entry}
