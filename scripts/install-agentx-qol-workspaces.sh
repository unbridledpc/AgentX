#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
echo "[INFO] Installing AgentX QoL Workspace patch in $ROOT"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups/qol-$STAMP

# Backup files we may touch
for f in apps/api/agentx_api/app.py AgentXWeb/src/ui/App.tsx; do
  if [ -f "$f" ]; then
    cp -a "$f" "backups/qol-$STAMP/$(echo "$f" | tr '/' '_')"
  fi
done

mkdir -p apps/api/agentx_api/routes AgentXWeb/public
cat > apps/api/agentx_api/routes/qol.py <<'PY'
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
PY

python3 - <<'PY'
from pathlib import Path
p = Path('apps/api/agentx_api/app.py')
text = p.read_text()
if 'qol_router' not in text:
    marker = 'from agentx_api.routes.workbench import router as workbench_router'
    if marker in text:
        text = text.replace(marker, marker + '\nfrom agentx_api.routes.qol import router as qol_router')
    else:
        # fall back to placing near other route imports
        text = text.replace('from fastapi import FastAPI', 'from fastapi import FastAPI')
        text = 'from agentx_api.routes.qol import router as qol_router\n' + text
    # include router after workbench if possible
    include_marker = 'app.include_router(workbench_router, prefix="/v1")'
    if include_marker in text:
        text = text.replace(include_marker, include_marker + '\n    app.include_router(qol_router, prefix="/v1")')
    else:
        # insert before return app
        text = text.replace('    return app', '    app.include_router(qol_router, prefix="/v1")\n    return app', 1)
    p.write_text(text)
    print('[OK] Patched app.py to include QoL router')
else:
    print('[OK] QoL router already included')
PY

# Add a standalone Workspaces page served by Vite public dir. This is deliberately simple and safe.
cat > AgentXWeb/public/workspaces.html <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AgentX Uploads & Workspaces</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background:#020617; color:#e2e8f0; }
    body { margin:0; padding:24px; }
    a { color:#67e8f9; }
    .shell { max-width:1120px; margin:0 auto; display:grid; gap:16px; }
    .card { border:1px solid rgba(148,163,184,.22); background:rgba(15,23,42,.82); border-radius:22px; padding:18px; box-shadow:0 18px 55px rgba(0,0,0,.22); }
    .row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; }
    button { border:1px solid rgba(103,232,249,.35); background:rgba(8,145,178,.18); color:#e0f2fe; border-radius:12px; padding:9px 12px; font-weight:700; cursor:pointer; }
    button.danger { border-color:rgba(248,113,113,.35); background:rgba(127,29,29,.45); color:#fecaca; }
    button.secondary { border-color:rgba(148,163,184,.25); background:rgba(30,41,59,.75); color:#cbd5e1; }
    .drop { border:2px dashed rgba(103,232,249,.38); border-radius:20px; padding:32px; text-align:center; background:rgba(8,145,178,.08); }
    .drop.drag { border-color:#22d3ee; background:rgba(8,145,178,.20); }
    .muted { color:#94a3b8; font-size:13px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }
    .upload { border:1px solid rgba(148,163,184,.18); background:rgba(2,6,23,.62); border-radius:16px; padding:14px; display:grid; gap:8px; }
    pre { white-space:pre-wrap; max-height:420px; overflow:auto; background:#020617; border:1px solid rgba(148,163,184,.18); border-radius:14px; padding:12px; }
    code { color:#bae6fd; }
    input[type=file] { display:none; }
  </style>
</head>
<body>
  <main class="shell">
    <div class="row">
      <div>
        <h1>AgentX Uploads & Workspaces</h1>
        <div class="muted">Manage uploaded archive workspaces, clear chats, and drag/drop archives into AgentX.</div>
      </div>
      <a href="/">Back to chat</a>
    </div>

    <section class="card">
      <h2>Drag & Drop Upload</h2>
      <div id="drop" class="drop">
        <strong>Drop ZIP/RAR/7z/TAR archives here</strong>
        <div class="muted">AgentX will create a chat thread, import the archive, analyze it, and attach the workspace to that thread.</div>
        <p><button id="pick">Choose archive</button></p>
        <input id="file" type="file" accept=".zip,.rar,.7z,.tar,.tgz,.tar.gz" />
      </div>
      <p id="uploadStatus" class="muted"></p>
    </section>

    <section class="card">
      <div class="row">
        <div>
          <h2>Chats</h2>
          <div class="muted">Clears all chat threads and thread-workspace mappings. Uploaded workspace folders are kept unless checked.</div>
        </div>
        <label class="muted"><input id="deleteWorkspaces" type="checkbox" /> also delete uploaded workspaces</label>
      </div>
      <p><button id="clearChats" class="danger">Clear all chats</button></p>
    </section>

    <section class="card">
      <div class="row">
        <div>
          <h2>Uploaded Workspaces</h2>
          <div class="muted">Archives imported into <code>work/workbench/imports/</code>.</div>
        </div>
        <button id="refresh" class="secondary">Refresh</button>
      </div>
      <div id="uploads" class="grid"></div>
    </section>

    <section class="card">
      <h2>Preview</h2>
      <pre id="preview">Select a report or tree.</pre>
    </section>
  </main>
<script>
const apiBase = `${location.protocol}//${location.hostname}:8000`;
const uploadsEl = document.getElementById('uploads');
const preview = document.getElementById('preview');
const statusEl = document.getElementById('uploadStatus');
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');

function archiveName(name) { return name.replace(/\.(zip|rar|7z|tar|tgz|tar\.gz)$/i, '').replace(/[^a-z0-9._-]+/gi, '-').replace(/^-+|-+$/g, '') || 'server-import'; }
async function api(path, opts={}) { const r = await fetch(apiBase + path, opts); if (!r.ok) throw new Error(await r.text() || `HTTP ${r.status}`); return r.json(); }
async function createThread() { return api('/v1/threads', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ title:'Uploaded workspace' }) }); }
async function uploadArchive(file) {
  statusEl.textContent = `Creating thread for ${file.name}...`;
  const thread = await createThread();
  const form = new FormData();
  form.append('file', file);
  form.append('project_name', archiveName(file.name));
  form.append('thread_id', thread.id);
  statusEl.textContent = `Uploading and analyzing ${file.name}...`;
  const res = await api('/v1/workbench/import-archive', { method:'POST', body: form });
  statusEl.textContent = `Done. Workspace attached to thread ${thread.id}. Open chat and select that thread.`;
  preview.textContent = JSON.stringify(res, null, 2).slice(0, 15000);
  await loadUploads();
}
async function loadUploads() {
  const data = await api('/v1/workbench/uploads');
  uploadsEl.innerHTML = '';
  for (const u of data.uploads || []) {
    const s = u.summary || {};
    const div = document.createElement('div');
    div.className = 'upload';
    div.innerHTML = `<strong>${u.project_id}</strong>
      <div class="muted">${(u.original_files||[]).join(', ') || 'archive'}</div>
      <div class="muted">Threads: ${(u.linked_thread_ids||[]).join(', ') || 'none'}</div>
      <div>Total files: ${s.total_files ?? 'unknown'} · Syntax: ${s.syntax_errors ?? 'unknown'} · Risks: ${s.risk_findings ?? 'unknown'}</div>
      <div class="row"><button data-report="${u.project_id}">Report</button><button data-tree="${u.project_id}" class="secondary">Tree</button><button data-delete="${u.project_id}" class="danger">Delete</button></div>`;
    uploadsEl.appendChild(div);
  }
}

document.getElementById('refresh').onclick = () => loadUploads().catch(e => preview.textContent = String(e));
document.getElementById('pick').onclick = () => fileInput.click();
fileInput.onchange = () => fileInput.files?.[0] && uploadArchive(fileInput.files[0]).catch(e => statusEl.textContent = String(e));

drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); const f = e.dataTransfer.files?.[0]; if (f) uploadArchive(f).catch(err => statusEl.textContent = String(err)); });

document.getElementById('clearChats').onclick = async () => {
  const del = document.getElementById('deleteWorkspaces').checked;
  if (!confirm(del ? 'Delete ALL chats and uploaded workspaces?' : 'Delete ALL chats? Uploaded workspaces will be kept.')) return;
  const out = await api(`/v1/threads?delete_workspaces=${del}`, { method:'DELETE' });
  preview.textContent = JSON.stringify(out, null, 2);
  await loadUploads();
};

uploadsEl.addEventListener('click', async e => {
  const btn = e.target.closest('button'); if (!btn) return;
  const report = btn.dataset.report, tree = btn.dataset.tree, del = btn.dataset.delete;
  try {
    if (report) preview.textContent = (await api(`/v1/workbench/uploads/${encodeURIComponent(report)}/report`)).content;
    if (tree) preview.textContent = JSON.stringify(await api(`/v1/workbench/uploads/${encodeURIComponent(tree)}/tree?max_entries=1000`), null, 2);
    if (del && confirm(`Delete workspace ${del}?`)) { preview.textContent = JSON.stringify(await api(`/v1/workbench/uploads/${encodeURIComponent(del)}`, { method:'DELETE' }), null, 2); await loadUploads(); }
  } catch (err) { preview.textContent = String(err); }
});
loadUploads().catch(e => preview.textContent = String(e));
</script>
</body>
</html>
HTML

# Patch React App to support window-level drag/drop archive import using the already-fixed importWorkbenchArchives function.
python3 - <<'PY'
from pathlib import Path
p = Path('AgentXWeb/src/ui/App.tsx')
if not p.exists():
    print('[WARN] App.tsx not found; skipping React drag/drop patch')
    raise SystemExit(0)
text = p.read_text()
if 'agentx-workbench-global-drop' in text:
    print('[OK] React drag/drop patch already present')
else:
    marker = '  const insertFileSearchPrompt = useCallback(() => {'
    block = '''  // agentx-workbench-global-drop
  useEffect(() => {
    const isArchive = (file: File) => /\\.(zip|rar|7z|tar|tgz|tar\\.gz)$/i.test(file.name);
    const onDragOver = (event: DragEvent) => {
      const files = event.dataTransfer?.files;
      if (files && files.length > 0 && Array.from(files).some(isArchive)) {
        event.preventDefault();
      }
    };
    const onDrop = (event: DragEvent) => {
      const files = event.dataTransfer?.files;
      if (!files || files.length === 0 || !Array.from(files).some(isArchive)) return;
      event.preventDefault();
      void importWorkbenchArchives(files);
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [importWorkbenchArchives]);

'''
    if marker in text:
        text = text.replace(marker, block + marker, 1)
        p.write_text(text)
        print('[OK] Added React global archive drag/drop handler')
    else:
        print('[WARN] Could not find insert point for React drag/drop patch')
PY

# Verify syntax/imports.
PYTHONPATH="$ROOT/AgentX:$ROOT/apps/api" "$ROOT/.venv/bin/python" - <<'PY'
from agentx_api.app import create_app
app = create_app()
print('[OK] API app imports with QoL routes')
PY

if [ -d AgentXWeb ]; then
  cd AgentXWeb
  npm run build || true
  cd "$ROOT"
fi

sudo systemctl restart agentx-api
sudo systemctl restart agentx-web

echo "[OK] Installed. Open: http://<agentx-vm-ip>:5173/workspaces.html"
