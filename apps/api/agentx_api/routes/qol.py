from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

try:
    from agentx_api.auth import current_user_id  # type: ignore
except Exception:  # pragma: no cover
    def current_user_id(_request: Request) -> str | None:  # type: ignore
        return None

try:
    from agentx_api.settings import config  # type: ignore
except Exception:  # pragma: no cover
    config = None  # type: ignore

router = APIRouter(tags=["qol"])

ROOT = Path.cwd()
WORKBENCH_ROOT = ROOT / "work" / "workbench"
IMPORTS_DIR = WORKBENCH_ROOT / "imports"
MAPPING_PATH = WORKBENCH_ROOT / "thread_workspaces.json"


def _safe_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _candidate_thread_dirs(owner_id: str | None) -> list[Path]:
    dirs: list[Path] = []
    cfg_threads = getattr(config, "threads_dir", None) if config is not None else None
    if cfg_threads:
        base = Path(str(cfg_threads))
        dirs.append(base)
        if owner_id:
            dirs.append(base / owner_id)
    dirs.extend([
        ROOT / "work" / "threads",
        ROOT / "AgentX" / "work" / "threads",
        ROOT / "data" / "threads",
    ])
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        try:
            r = str(d.expanduser().resolve(False))
        except Exception:
            r = str(d)
        if r not in seen:
            seen.add(r)
            out.append(Path(r))
    return out


def _iter_thread_files(owner_id: str | None) -> list[Path]:
    files: list[Path] = []
    for d in _candidate_thread_dirs(owner_id):
        if d.exists() and d.is_dir():
            files.extend([p for p in d.glob("*.json") if p.is_file()])
    return sorted(set(files), key=lambda p: str(p))


@router.delete("/threads")
def clear_all_threads(
    http: Request,
    delete_workspaces: bool = Query(default=False, description="Also delete uploaded archive workspaces."),
) -> dict[str, Any]:
    """Delete all chat thread JSON files. Uploaded workspaces are kept unless requested."""
    owner_id = current_user_id(http) or "default"
    removed: list[str] = []
    for p in _iter_thread_files(owner_id):
        try:
            p.unlink()
            removed.append(str(p))
        except FileNotFoundError:
            pass

    removed_mappings = 0
    if MAPPING_PATH.exists():
        mapping = _safe_json(MAPPING_PATH, {})
        if isinstance(mapping, dict):
            removed_mappings = len(mapping)
            _write_json(MAPPING_PATH, {})

    removed_uploads = 0
    if delete_workspaces and IMPORTS_DIR.exists():
        for child in IMPORTS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                removed_uploads += 1

    return {
        "ok": True,
        "removed_threads": len(removed),
        "removed_thread_files": removed,
        "cleared_workspace_mappings": removed_mappings,
        "removed_upload_workspaces": removed_uploads,
        "delete_workspaces": delete_workspaces,
    }


@router.get("/workbench/uploads")
def list_workbench_uploads() -> dict[str, Any]:
    mapping = _safe_json(MAPPING_PATH, {})
    linked_by_project: dict[str, list[str]] = {}
    if isinstance(mapping, dict):
        for tid, rec in mapping.items():
            if isinstance(rec, dict):
                pid = str(rec.get("project_id") or Path(str(rec.get("workspace_path") or "")).name)
                linked_by_project.setdefault(pid, []).append(str(tid))

    uploads: list[dict[str, Any]] = []
    if IMPORTS_DIR.exists():
        for root in sorted([p for p in IMPORTS_DIR.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
            analysis_dir = root / "analysis"
            summary = _safe_json(analysis_dir / "summary.json", {})
            inv = _safe_json(analysis_dir / "inventory.json", {})
            original_files = []
            original_dir = root / "original"
            if original_dir.exists():
                original_files = [p.name for p in original_dir.iterdir() if p.is_file()]
            uploads.append({
                "project_id": root.name,
                "workspace_path": str(root),
                "extracted_dir": str(root / "extracted"),
                "analysis_dir": str(analysis_dir),
                "report_path": str(analysis_dir / "final_report.md"),
                "inventory_path": str(analysis_dir / "inventory.json"),
                "original_files": original_files,
                "linked_thread_ids": linked_by_project.get(root.name, []),
                "summary": summary if isinstance(summary, dict) and summary else {
                    "total_files": inv.get("total_files") if isinstance(inv, dict) else None,
                    "counts_by_kind": inv.get("counts_by_kind") if isinstance(inv, dict) else None,
                },
                "created_at": root.stat().st_mtime,
            })
    return {"ok": True, "uploads": uploads, "count": len(uploads)}


def _project_root(project_id: str) -> Path:
    safe = Path(project_id).name
    root = (IMPORTS_DIR / safe).resolve(False)
    imports = IMPORTS_DIR.resolve(False)
    try:
        root.relative_to(imports)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Unsafe project id") from exc
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Upload workspace not found")
    return root


@router.get("/workbench/uploads/{project_id}")
def get_workbench_upload(project_id: str) -> dict[str, Any]:
    root = _project_root(project_id)
    summary = _safe_json(root / "analysis" / "summary.json", {})
    return {"ok": True, "project_id": root.name, "workspace_path": str(root), "summary": summary}


@router.get("/workbench/uploads/{project_id}/report")
def get_workbench_upload_report(project_id: str) -> dict[str, Any]:
    root = _project_root(project_id)
    path = root / "analysis" / "final_report.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return {"ok": True, "project_id": root.name, "path": str(path), "content": path.read_text(encoding="utf-8", errors="replace")}


@router.get("/workbench/uploads/{project_id}/tree")
def get_workbench_upload_tree(project_id: str, max_entries: int = Query(default=5000, ge=1, le=50000)) -> dict[str, Any]:
    root = _project_root(project_id)
    extracted = root / "extracted"
    entries: list[dict[str, Any]] = []
    if extracted.exists():
        for p in extracted.rglob("*"):
            if len(entries) >= max_entries:
                break
            try:
                rel = p.relative_to(extracted).as_posix()
            except Exception:
                continue
            entries.append({"path": rel, "type": "dir" if p.is_dir() else "file", "size": p.stat().st_size if p.is_file() else 0})
    return {"ok": True, "project_id": root.name, "entries": entries, "truncated": len(entries) >= max_entries}


@router.delete("/workbench/uploads/{project_id}")
def delete_workbench_upload(project_id: str) -> dict[str, Any]:
    root = _project_root(project_id)
    project = root.name
    shutil.rmtree(root, ignore_errors=True)
    mapping = _safe_json(MAPPING_PATH, {})
    removed_thread_ids: list[str] = []
    if isinstance(mapping, dict):
        for tid, rec in list(mapping.items()):
            if isinstance(rec, dict) and (rec.get("project_id") == project or Path(str(rec.get("workspace_path") or "")).name == project):
                mapping.pop(tid, None)
                removed_thread_ids.append(str(tid))
        _write_json(MAPPING_PATH, mapping)
    return {"ok": True, "deleted_project_id": project, "removed_thread_ids": removed_thread_ids}
