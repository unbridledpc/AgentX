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
