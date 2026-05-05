#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"

echo "[INFO] Installing AgentX workspace validation patch in $ROOT"

if [ ! -f apps/api/agentx_api/routes/workbench.py ]; then
  echo "[ERR] apps/api/agentx_api/routes/workbench.py not found. Run from AgentX repo root or pass repo path." >&2
  exit 1
fi
if [ ! -f AgentXWeb/public/workspaces.html ]; then
  echo "[ERR] AgentXWeb/public/workspaces.html not found." >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
cp -a apps/api/agentx_api/routes/workbench.py "apps/api/agentx_api/routes/workbench.py.bak-workspace-validation-$TS"
cp -a AgentXWeb/public/workspaces.html "AgentXWeb/public/workspaces.html.bak-workspace-validation-$TS"
[ -f AgentXWeb/dist/workspaces.html ] && cp -a AgentXWeb/dist/workspaces.html "AgentXWeb/dist/workspaces.html.bak-workspace-validation-$TS" || true

python3 - <<'PY'
from pathlib import Path

p = Path('apps/api/agentx_api/routes/workbench.py')
text = p.read_text()

# Ensure imports we need are present.
if 'import subprocess' not in text:
    # Insert after import block near the top.
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:80]):
        if line.startswith('import ') or line.startswith('from '):
            insert_at = i + 1
    lines.insert(insert_at, 'import subprocess')
    text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')

if 'import sys' not in text:
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:80]):
        if line.startswith('import ') or line.startswith('from '):
            insert_at = i + 1
    lines.insert(insert_at, 'import sys')
    text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')

if 'import tempfile' not in text:
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:80]):
        if line.startswith('import ') or line.startswith('from '):
            insert_at = i + 1
    lines.insert(insert_at, 'import tempfile')
    text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')

if 'import xml.etree.ElementTree as ET' not in text:
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:100]):
        if line.startswith('import ') or line.startswith('from '):
            insert_at = i + 1
    lines.insert(insert_at, 'import xml.etree.ElementTree as ET')
    text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')

if 'class WorkbenchValidateRequest' not in text:
    # Add request model after existing BaseModel classes if possible, otherwise after imports.
    marker = 'class WorkbenchFileWriteRequest'
    if marker in text:
        idx = text.find(marker)
        # Put validation model before file write request to avoid dependency issues.
        model = '''\nclass WorkbenchValidateRequest(BaseModel):\n    path: str\n    content: str | None = None\n\n'''
        text = text[:idx] + model + text[idx:]
    else:
        # Find first router assignment or after imports.
        idx = text.find('router =')
        if idx == -1:
            raise SystemExit('[ERR] Could not find insertion point for WorkbenchValidateRequest')
        text = text[:idx] + '''\nclass WorkbenchValidateRequest(BaseModel):\n    path: str\n    content: str | None = None\n\n''' + text[idx:]

endpoint_marker = '@router.post("/workbench/thread/{thread_id}/validate")'
if endpoint_marker not in text:
    endpoint = r'''

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


@router.post("/workbench/thread/{thread_id}/validate")
def validate_thread_workspace_file(thread_id: str, request: WorkbenchValidateRequest) -> dict[str, Any]:
    rel_path = (request.path or "").strip().lstrip("/")
    if not rel_path:
        raise HTTPException(status_code=400, detail="path is required")
    _, target, record = _safe_workspace_file_validate(thread_id, rel_path)
    result = _validate_content_for_path(target, rel_path, request.content)
    result["project_id"] = record.get("project_id")
    result["file_size"] = target.stat().st_size
    return result
'''
    text += '\n\n' + endpoint + '\n'

p.write_text(text)
print('[OK] Patched backend validation endpoint')
PY

python3 -m py_compile apps/api/agentx_api/routes/workbench.py

python3 - <<'PY'
from pathlib import Path

p = Path('AgentXWeb/public/workspaces.html')
text = p.read_text()

# Add validation status box CSS.
css = '''
<style id="agentx-validation-ui-css">
  #validationBox {
    border: 1px solid rgba(148, 163, 184, 0.22);
    background: rgba(15, 23, 42, 0.72);
    border-radius: 14px;
    padding: 10px;
    color: #dbeafe;
    font-size: 12px;
    overflow: auto;
    max-height: 180px;
    white-space: pre-wrap;
  }
  #validationBox.ok { border-color: rgba(16, 185, 129, 0.45); background: rgba(6, 78, 59, 0.20); }
  #validationBox.bad { border-color: rgba(244, 63, 94, 0.50); background: rgba(127, 29, 29, 0.22); }
  #validationBox.skip { border-color: rgba(245, 158, 11, 0.45); background: rgba(120, 53, 15, 0.22); }
</style>
'''
if 'agentx-validation-ui-css' not in text:
    text = text.replace('</head>', css + '\n</head>', 1)

# Add validation box/button near patch buttons.
old = '''          <div class="row">
            <button id="copyCurrentBtn" disabled>Copy current to proposal</button>
            <button id="previewDiffBtn" disabled>Preview diff</button>
            <button id="applyPatchBtn" class="primary" disabled>Apply to sandbox</button>
          </div>'''
new = '''          <div class="row">
            <button id="copyCurrentBtn" disabled>Copy current to proposal</button>
            <button id="previewDiffBtn" disabled>Preview diff</button>
            <button id="validatePatchBtn" disabled>Validate proposal</button>
            <button id="applyPatchBtn" class="primary" disabled>Apply to sandbox</button>
          </div>
          <div id="validationBox" class="skip">No validation run yet.</div>'''
if old in text and 'validatePatchBtn' not in text:
    text = text.replace(old, new, 1)

# Add helper renderer/function before applyPatch.
if 'function renderValidationResult' not in text:
    marker = 'async function applyPatch() {'
    helper = r'''
function renderValidationResult(result) {
  const box = $('validationBox');
  if (!box) return;
  box.className = result.ok === true ? 'ok' : result.ok === false ? 'bad' : 'skip';
  const lines = [];
  lines.push(result.message || (result.ok === true ? 'Validation passed.' : result.ok === false ? 'Validation failed.' : 'Validation skipped.'));
  if (result.path) lines.push(`File: ${result.path}`);
  if (result.language) lines.push(`Type: ${result.language}`);
  for (const check of result.checks || []) {
    lines.push('');
    lines.push(`Check: ${check.name || 'validator'}`);
    lines.push(`Status: ${check.ok === true ? 'pass' : check.ok === false ? 'fail' : 'skipped'}`);
    if (check.command && check.command.length) lines.push(`Command: ${check.command.join(' ')}`);
    if (check.stdout) lines.push(`stdout:\n${check.stdout}`);
    if (check.stderr) lines.push(`stderr:\n${check.stderr}`);
  }
  box.textContent = lines.join('\n');
}

async function validateProposal() {
  const u = state.selected, f = state.file;
  if (!u?.thread_id || !f?.path) return null;
  status(`Validating proposal for ${f.path}...`);
  try {
    const result = await api(`/v1/workbench/thread/${encodeURIComponent(u.thread_id)}/validate`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: f.path, content: $('proposedContent').value})
    });
    renderValidationResult(result);
    status(result.message || 'Validation complete.');
    return result;
  } catch (e) {
    const result = {ok: false, message: `Validation request failed: ${e.message}`, checks: []};
    renderValidationResult(result);
    status(result.message);
    return result;
  }
}

async function validateCurrentFile() {
  const u = state.selected, f = state.file;
  if (!u?.thread_id || !f?.path) return null;
  status(`Validating current sandbox file ${f.path}...`);
  try {
    const result = await api(`/v1/workbench/thread/${encodeURIComponent(u.thread_id)}/validate`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: f.path})
    });
    renderValidationResult(result);
    status(result.message || 'Validation complete.');
    return result;
  } catch (e) {
    const result = {ok: false, message: `Validation request failed: ${e.message}`, checks: []};
    renderValidationResult(result);
    status(result.message);
    return result;
  }
}

'''
    if marker not in text:
        raise SystemExit('[ERR] Could not find applyPatch() insertion point')
    text = text.replace(marker, helper + marker, 1)

# Update openFile to enable validation and reset box.
text = text.replace(
    "$('copyCurrentBtn').disabled = false; $('previewDiffBtn').disabled = false; $('applyPatchBtn').disabled = false; $('findMatchesBtn').disabled = false;",
    "$('copyCurrentBtn').disabled = false; $('previewDiffBtn').disabled = false; $('applyPatchBtn').disabled = false; if ($('validatePatchBtn')) $('validatePatchBtn').disabled = false; $('findMatchesBtn').disabled = false; if ($('validationBox')) { $('validationBox').className = 'skip'; $('validationBox').textContent = 'No validation run yet.'; }"
)

# After applying patch, validate the current file automatically.
text = text.replace(
    "await openFile(f.path);\n    status(`Applied sandbox edit to ${f.path}.`);",
    "await openFile(f.path);\n    await validateCurrentFile();\n    status(`Applied sandbox edit to ${f.path} and validation finished.`);"
)

# Wire button event near existing event listeners.
if "$('validatePatchBtn').onclick" not in text:
    # Add near preview/apply listeners if present, otherwise before loadUploads.
    listener = "if ($('validatePatchBtn')) $('validatePatchBtn').onclick = () => void validateProposal();\n"
    marker = "$('applyPatchBtn').onclick = () => void applyPatch();"
    if marker in text:
        text = text.replace(marker, marker + "\n" + listener, 1)
    else:
        marker2 = "loadUploads();"
        if marker2 not in text:
            raise SystemExit('[ERR] Could not find listener insertion point')
        text = text.replace(marker2, listener + marker2, 1)

p.write_text(text)
print('[OK] Patched Workspaces validation UI')
PY

# Keep dist synced when it exists; Vite dev may serve public, static may serve dist.
mkdir -p AgentXWeb/dist
cp -a AgentXWeb/public/workspaces.html AgentXWeb/dist/workspaces.html

PYTHONPATH="$PWD/AgentX:$PWD/apps/api" ./.venv/bin/python - <<'PY'
from agentx_api.app import create_app
app = create_app()
print('[OK] API app imports')
PY

# Build web if possible, but do not fail install if npm is unavailable.
if [ -f AgentXWeb/package.json ]; then
  echo "[INFO] Building AgentXWeb..."
  (cd AgentXWeb && npm run build) || echo "[WARN] npm build failed; dev server will still use patched public/workspaces.html"
  cp -a AgentXWeb/public/workspaces.html AgentXWeb/dist/workspaces.html 2>/dev/null || true
fi

sudo systemctl restart agentx-api || true
sudo systemctl restart agentx-web || true

echo "[OK] Installed workspace validation patch. Hard refresh with Ctrl+Shift+R."
