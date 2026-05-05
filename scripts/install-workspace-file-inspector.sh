#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
echo "[INFO] Installing AgentX Workspace File Inspector in $ROOT"

if [ ! -d AgentXWeb/public ]; then
  mkdir -p AgentXWeb/public
fi
cp -a payload/AgentXWeb/public/workspaces.html AgentXWeb/public/workspaces.html

python3 - <<'PY'
from pathlib import Path

p = Path("apps/api/agentx_api/routes/workbench.py")
if not p.exists():
    raise SystemExit("[ERR] apps/api/agentx_api/routes/workbench.py not found")
text = p.read_text()

# Ensure typing imports include Any already normally. Ensure json/os/time imports for uploads endpoints.
if "import json" not in text:
    text = text.replace("from __future__ import annotations\n\n", "from __future__ import annotations\n\nimport json\n", 1)
if "import time" not in text:
    text = text.replace("import tempfile\n", "import tempfile\nimport time\n", 1)

if '@router.get("/uploads")' not in text:
    block = r'''

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
'''
    marker = '@router.get("/report")'
    if marker not in text:
        raise SystemExit("[ERR] Could not find report route marker in workbench.py")
    text = text.replace(marker, block + "\n\n" + marker, 1)

p.write_text(text)
print("[OK] Ensured workbench upload listing endpoints")
PY

python3 -m py_compile apps/api/agentx_api/routes/workbench.py

# Vite dev server serves source/public; build is still useful as a type/syntax check.
if [ -d AgentXWeb ]; then
  (cd AgentXWeb && npm run build)
fi

sudo systemctl restart agentx-api || true
sudo systemctl restart agentx-web || true

echo "[OK] Installed Workspace File Inspector. Hard refresh AgentX with Ctrl+Shift+R."
