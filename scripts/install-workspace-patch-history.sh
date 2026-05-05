#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"

echo "[INFO] Installing AgentX workspace patch history in $ROOT"

if [ ! -f apps/api/agentx_api/routes/workbench.py ]; then
  echo "[ERR] apps/api/agentx_api/routes/workbench.py not found. Run from AgentX repo root or pass path." >&2
  exit 1
fi
if [ ! -f AgentXWeb/public/workspaces.html ]; then
  echo "[ERR] AgentXWeb/public/workspaces.html not found. Run from AgentX repo root or pass path." >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
cp -a apps/api/agentx_api/routes/workbench.py "apps/api/agentx_api/routes/workbench.py.bak-patch-history-$TS"
cp -a AgentXWeb/public/workspaces.html "AgentXWeb/public/workspaces.html.bak-patch-history-$TS"
if [ -f AgentXWeb/dist/workspaces.html ]; then
  cp -a AgentXWeb/dist/workspaces.html "AgentXWeb/dist/workspaces.html.bak-patch-history-$TS"
fi

python3 - <<'PY'
from pathlib import Path
p = Path('apps/api/agentx_api/routes/workbench.py')
text = p.read_text()

patch = r'''

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
'''

if 'Workspace patch history + rollback endpoints' not in text:
    text += patch
else:
    print('[INFO] Patch history backend already present; skipping append')

p.write_text(text)
PY

python3 - <<'PY'
from pathlib import Path
p = Path('AgentXWeb/public/workspaces.html')
text = p.read_text()

# Add history button to tabs if absent.
if 'data-tab="history"' not in text:
    text = text.replace(
        '<button class="tab" data-tab="report">Report</button>',
        '<button class="tab" data-tab="report">Report</button>\n          <button class="tab" data-tab="history">History</button>',
        1,
    )

# Add history pane if absent.
if 'id="tab-history"' not in text:
    needle = '<div id="tab-report" class="tabPane hidden" style="height:100%;"><pre id="reportContent">No report loaded.</pre></div>'
    repl = needle + '''

        <div id="tab-history" class="tabPane hidden" style="height:100%; display:grid; grid-template-rows:auto minmax(0,1fr); gap:8px;">
          <div class="row">
            <button id="refreshHistoryBtn">Refresh history</button>
            <span class="sub">Sandbox patch history and rollback for this uploaded workspace.</span>
          </div>
          <div id="patchHistory" class="list" style="max-height:70vh; overflow:auto;"><div class="sub">No patch history loaded.</div></div>
        </div>'''
    if needle not in text:
        raise SystemExit('[ERR] Could not find report pane insertion point')
    text = text.replace(needle, repl, 1)

# Add CSS for history cards.
css = '''
<style id="agentx-patch-history-css">
  .historyCard {
    width: 100%;
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    background: rgba(15, 23, 42, 0.72);
    padding: 10px;
    text-align: left;
    color: #dbeafe;
    margin-bottom: 8px;
  }
  .historyCard strong { color: #f1f5f9; }
  .historyMeta { color: #8fa3bd; font-size: 11px; margin-top: 4px; overflow-wrap: anywhere; }
  .historyActions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .historyActions button { width: auto !important; }
</style>
'''
if 'agentx-patch-history-css' not in text:
    text = text.replace('</head>', css + '\n</head>', 1)

# JS bridge. Appended near body end so it can wrap existing functions.
js = r'''
<script id="agentx-patch-history-ui">
(function () {
  function getSelectedWorkspace() { return (window.state && window.state.selected) || null; }
  function getCurrentFile() { return (window.state && window.state.file) || null; }
  function setStatus(msg) { if (typeof status === "function") status(msg); }
  function apiBaseUrl() {
    try { return window.apiBase || localStorage.getItem("agentx.apiBase") || `${location.protocol}//${location.hostname}:8000`; }
    catch { return `${location.protocol}//${location.hostname}:8000`; }
  }
  async function callApi(path, opts = {}) {
    if (typeof api === "function") return api(path, opts);
    const res = await fetch(`${apiBaseUrl()}${path}`, opts);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
    return res.json();
  }
  function escapeHtmlLocal(s) {
    if (typeof esc === "function") return esc(s);
    return String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
  }
  function validationSummary(v) {
    if (!v) return "validation unknown";
    const ok = v.ok ?? v.status === "pass" ?? v.validation?.ok;
    const status = ok ? "pass" : "fail";
    const check = v.check || v.validator || v.validation?.validator || v.validation?.check || "validator";
    return `${check}: ${status}`;
  }
  async function loadPatchHistory() {
    const u = getSelectedWorkspace();
    const root = document.getElementById("patchHistory");
    if (!root) return;
    if (!u || !u.thread_id) { root.innerHTML = '<div class="sub">Select a thread-linked workspace first.</div>'; return; }
    root.innerHTML = '<div class="sub">Loading patch history...</div>';
    try {
      const data = await callApi(`/v1/workbench/thread/${encodeURIComponent(u.thread_id)}/patch-history`);
      const history = Array.isArray(data.history) ? data.history : [];
      if (!history.length) { root.innerHTML = '<div class="sub">No patches applied yet.</div>'; return; }
      root.innerHTML = history.map((entry, idx) => {
        const action = entry.action || 'apply';
        const path = entry.path || 'unknown';
        const when = entry.timestamp || (entry.ts ? new Date(entry.ts * 1000).toLocaleString() : 'unknown time');
        const backup = entry.backup_path || '';
        const validation = validationSummary(entry.validation || {});
        const canRestore = backup && action !== 'restore';
        return `<div class="historyCard" data-history-index="${idx}">
          <div><strong>${escapeHtmlLocal(action.toUpperCase())}</strong> ${escapeHtmlLocal(path)}</div>
          <div class="historyMeta">${escapeHtmlLocal(when)} · ${escapeHtmlLocal(validation)}</div>
          ${backup ? `<div class="historyMeta">backup: ${escapeHtmlLocal(backup)}</div>` : `<div class="historyMeta">backup: none recorded</div>`}
          <div class="historyActions">
            ${canRestore ? `<button type="button" data-restore-index="${idx}">Restore backup</button>` : ''}
          </div>
        </div>`;
      }).join('');
      root.querySelectorAll('[data-restore-index]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const idx = Number(btn.getAttribute('data-restore-index'));
          const entry = history[idx];
          if (!entry || !entry.backup_path) return;
          if (!confirm(`Restore sandbox file from backup?\n\n${entry.path}\n\n${entry.backup_path}`)) return;
          await restorePatchBackup(entry.backup_path, entry.path);
        });
      });
    } catch (err) {
      root.innerHTML = `<div class="sub">Failed to load patch history: ${escapeHtmlLocal(err.message || err)}</div>`;
    }
  }
  async function recordPatchHistory(validationResult) {
    const u = getSelectedWorkspace();
    const f = getCurrentFile();
    if (!u || !u.thread_id || !f || !f.path) return;
    try {
      await callApi(`/v1/workbench/thread/${encodeURIComponent(u.thread_id)}/patch-history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: f.path,
          action: 'apply',
          validation: validationResult || window.agentxLastValidationResult || {},
          message: 'Applied from Workspaces Patch Preview.'
        })
      });
      await loadPatchHistory();
    } catch (err) {
      setStatus(`Patch applied, but history record failed: ${err.message || err}`);
    }
  }
  async function restorePatchBackup(backupPath, relPath) {
    const u = getSelectedWorkspace();
    if (!u || !u.thread_id) return;
    try {
      setStatus(`Restoring ${relPath} from backup...`);
      await callApi(`/v1/workbench/thread/${encodeURIComponent(u.thread_id)}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_path: backupPath })
      });
      await loadPatchHistory();
      if (typeof openFile === 'function' && relPath) await openFile(relPath);
      setStatus(`Restored ${relPath} from backup.`);
    } catch (err) {
      setStatus(`Restore failed: ${err.message || err}`);
    }
  }
  function wireHistoryButton() {
    const btn = document.getElementById('refreshHistoryBtn');
    if (btn && btn.dataset.agentxHistoryWired !== '1') {
      btn.dataset.agentxHistoryWired = '1';
      btn.addEventListener('click', () => void loadPatchHistory());
    }
  }
  function wrapValidateProposal() {
    if (typeof window.validateProposal !== 'function' || window.validateProposal.__agentxHistoryWrapped) return;
    const original = window.validateProposal;
    window.validateProposal = async function (...args) {
      const result = await original.apply(this, args);
      window.agentxLastValidationResult = result || window.agentxLastValidationResult || {};
      return result;
    };
    window.validateProposal.__agentxHistoryWrapped = true;
  }
  function wrapApplyPatch() {
    if (typeof window.applyPatch !== 'function' || window.applyPatch.__agentxHistoryWrapped) return;
    const original = window.applyPatch;
    window.applyPatch = async function (...args) {
      const beforeFile = getCurrentFile();
      const result = await original.apply(this, args);
      // Existing applyPatch re-opens the file. Record after it finishes so backend can find backup files.
      await recordPatchHistory(window.agentxLastValidationResult || {});
      return result;
    };
    window.applyPatch.__agentxHistoryWrapped = true;
  }
  function autoLoadOnHistoryTab() {
    document.querySelectorAll('[data-tab="history"]').forEach(btn => {
      if (btn.dataset.agentxHistoryTabWired === '1') return;
      btn.dataset.agentxHistoryTabWired = '1';
      btn.addEventListener('click', () => setTimeout(loadPatchHistory, 100));
    });
  }
  function boot() {
    wireHistoryButton();
    wrapValidateProposal();
    wrapApplyPatch();
    autoLoadOnHistoryTab();
  }
  window.agentxLoadPatchHistory = loadPatchHistory;
  boot();
  setInterval(boot, 750);
})();
</script>
'''
if 'agentx-patch-history-ui' not in text:
    text = text.replace('</body>', js + '\n</body>', 1)

p.write_text(text)
PY

# Patch existing applyPatch to record validation result more reliably if exact function exists.
python3 - <<'PY'
from pathlib import Path
p = Path('AgentXWeb/public/workspaces.html')
text = p.read_text()
# Make validateProposal return the API result if it currently does not.
if 'async function validateProposal()' in text and 'return result;' not in text[text.find('async function validateProposal()'):text.find('async function validateCurrentFile()', text.find('async function validateProposal()'))]:
    start = text.find('async function validateProposal()')
    end = text.find('async function validateCurrentFile()', start)
    block = text[start:end]
    block2 = block.replace('    renderValidation(result);', '    window.agentxLastValidationResult = result;\n    renderValidation(result);\n    return result;', 1)
    text = text[:start] + block2 + text[end:]
# Same for validateCurrentFile if present.
if 'async function validateCurrentFile()' in text:
    start = text.find('async function validateCurrentFile()')
    end = text.find('async function applyPatch()', start)
    if end != -1:
        block = text[start:end]
        if 'return result;' not in block:
            block2 = block.replace('    renderValidation(result);', '    window.agentxLastValidationResult = result;\n    renderValidation(result);\n    return result;', 1)
            text = text[:start] + block2 + text[end:]
p.write_text(text)
PY

# Keep dist synced because this install may run against either dev/public or dist serving.
if [ -d AgentXWeb/dist ]; then
  cp -a AgentXWeb/public/workspaces.html AgentXWeb/dist/workspaces.html
fi

python3 -m py_compile apps/api/agentx_api/routes/workbench.py
PYTHONPATH="$PWD/AgentX:$PWD/apps/api" ./.venv/bin/python - <<'PY'
from agentx_api.app import create_app
app = create_app()
print('[OK] API app imports')
PY

if [ -d AgentXWeb ]; then
  (cd AgentXWeb && npm run build)
fi
if [ -f AgentXWeb/public/workspaces.html ] && [ -d AgentXWeb/dist ]; then
  cp -a AgentXWeb/public/workspaces.html AgentXWeb/dist/workspaces.html
fi

sudo systemctl restart agentx-api || true
sudo systemctl restart agentx-web || true

echo "[OK] Installed workspace patch history + rollback. Hard refresh AgentX with Ctrl+Shift+R."
