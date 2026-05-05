#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"

echo "[INFO] Installing Ask AgentX to Fix This File patch in $ROOT"

APP="AgentXWeb/src/ui/App.tsx"
WS_PUBLIC="AgentXWeb/public/workspaces.html"
WS_DIST="AgentXWeb/dist/workspaces.html"

if [[ ! -f "$APP" ]]; then
  echo "[ERR] Missing $APP" >&2
  exit 1
fi
if [[ ! -f "$WS_PUBLIC" ]]; then
  echo "[ERR] Missing $WS_PUBLIC" >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
cp -a "$APP" "$APP.bak-ask-fix-$TS"
cp -a "$WS_PUBLIC" "$WS_PUBLIC.bak-ask-fix-$TS"
[[ -f "$WS_DIST" ]] && cp -a "$WS_DIST" "$WS_DIST.bak-ask-fix-$TS" || true

python3 - <<'PY'
from pathlib import Path

app = Path("AgentXWeb/src/ui/App.tsx")
text = app.read_text()

marker = "agentx:ask-fix-file"
if marker not in text:
    block = r'''
  useEffect(() => {
    const handleWorkspaceAskFix = (event: MessageEvent) => {
      const data = event.data as { type?: string; prompt?: string; path?: string } | null;
      if (!data || data.type !== "agentx:ask-fix-file") return;
      const prompt = String(data.prompt || "").trim();
      if (!prompt) return;
      setDraft((prev) => prev.trim() ? `${prev.trim()}\n\n${prompt}` : prompt);
      setActiveView("chat");
      setSystemMessage(`Workspace fix request loaded${data.path ? ` for ${data.path}` : ""}. Review it, then press Send.`);
      requestAnimationFrame(() => textareaRef.current?.focus());
    };
    window.addEventListener("message", handleWorkspaceAskFix);
    return () => window.removeEventListener("message", handleWorkspaceAskFix);
  }, [setSystemMessage]);

'''
    # Put it near other UI callbacks, before removeComposerAttachment if possible.
    target = "  const removeComposerAttachment = useCallback((id: string) => {"
    if target in text:
        text = text.replace(target, block + target, 1)
    else:
        # Fallback: insert before importWorkbenchArchives.
        target = "  const importWorkbenchArchives = useCallback(async (files: FileList | null) => {"
        if target not in text:
            raise SystemExit("[ERR] Could not find insertion point for workspace ask-fix listener")
        text = text.replace(target, block + target, 1)
    app.write_text(text)
    print("[OK] Added postMessage listener to App.tsx")
else:
    print("[OK] App.tsx already has ask-fix listener")
PY

python3 - <<'PY'
from pathlib import Path

p = Path("AgentXWeb/public/workspaces.html")
text = p.read_text()

# 1. Add the button near Report / Export ZIP.
if 'id="askFixBtn"' not in text:
    old = '<button id="reportBtn" disabled>Report</button>\n            <button id="exportBtn" disabled>Export ZIP</button>'
    new = '<button id="askFixBtn" disabled>Ask AgentX to fix</button>\n            <button id="reportBtn" disabled>Report</button>\n            <button id="exportBtn" disabled>Export ZIP</button>'
    if old not in text:
        raise SystemExit('[ERR] Could not find Report/Export button block in workspaces.html')
    text = text.replace(old, new, 1)

# 2. Add helper JS before event bindings at bottom.
helper = r'''
function compactForPrompt(value, maxChars = 14000) {
  const text = String(value || '');
  if (text.length <= maxChars) return text;
  return text.slice(0, maxChars) + `\n\n[TRUNCATED: ${text.length - maxChars} more characters omitted by Workspaces UI]`;
}

function likelySourceCandidatesForCurrentFile(limit = 20) {
  const f = state.file;
  if (!f?.path) return [];
  const base = basenameNoExt(f.path);
  return state.tree
    .filter(x => (x.type === 'file' || !x.type) && basenameNoExt(x.path) === base && x.path !== f.path)
    .sort((a, b) => String(a.path).localeCompare(String(b.path)))
    .slice(0, limit)
    .map(x => x.path);
}

function buildAskAgentXFixPrompt() {
  const u = state.selected;
  const f = state.file;
  if (!u || !f?.path) return '';
  const validation = $('validationBox') ? $('validationBox').textContent : '';
  const candidates = likelySourceCandidatesForCurrentFile(20);
  const proposed = $('proposedContent') ? $('proposedContent').value : '';
  const current = f.content || '';
  const projectId = u.project_id || u.id || 'unknown-workspace';
  const threadId = u.thread_id || 'unlinked';

  return [
    'Use the uploaded archive workspace attached to this thread.',
    'Task: fix the selected file using a sandbox-only patch proposal.',
    '',
    `Workspace project: ${projectId}`,
    `Workspace thread: ${threadId}`,
    `Target file: ${f.path}`,
    '',
    'Rules:',
    '- Do not claim you cannot access the uploaded archive.',
    '- Do not edit live server files.',
    '- Use the extracted sandbox workspace only.',
    '- Base file-specific claims on the exact file content below.',
    '- Prefer a minimal, reviewable patch.',
    '- Explain why the validation failed or passed.',
    '- Return the proposed replacement content or a unified diff.',
    '',
    'Current file content:',
    '```',
    compactForPrompt(current),
    '```',
    '',
    proposed && proposed !== current ? 'Current proposal text from Patch Preview:' : '',
    proposed && proposed !== current ? '```' : '',
    proposed && proposed !== current ? compactForPrompt(proposed) : '',
    proposed && proposed !== current ? '```' : '',
    proposed && proposed !== current ? '' : '',
    validation ? 'Latest validation output:' : '',
    validation ? '```text' : '',
    validation ? compactForPrompt(validation, 6000) : '',
    validation ? '```' : '',
    validation ? '' : '',
    candidates.length ? 'Likely matching source candidates from the same workspace:' : '',
    ...candidates.map(path => `- ${path}`),
    candidates.length ? '' : '',
    'Please inspect the candidate source if needed, then propose the safest sandbox patch and validation command.'
  ].filter((line) => line !== '').join('\n');
}

async function askAgentXToFixFile() {
  const f = state.file;
  if (!f?.path) { status('Open a file first.'); return; }
  const prompt = buildAskAgentXFixPrompt();
  if (!prompt.trim()) { status('Could not build fix prompt.'); return; }

  try {
    window.parent?.postMessage({ type: 'agentx:ask-fix-file', path: f.path, prompt }, window.location.origin);
    status(`Loaded fix request into AgentX chat composer for ${f.path}.`);
  } catch (err) {
    try {
      await navigator.clipboard.writeText(prompt);
      status('Could not message parent shell, so the fix prompt was copied to clipboard. Paste it into chat.');
    } catch (copyErr) {
      status(`Failed to send/copy fix prompt: ${copyErr instanceof Error ? copyErr.message : String(copyErr)}`);
    }
  }
}
'''

if 'function buildAskAgentXFixPrompt' not in text:
    bind_marker = "if ($('validatePatchBtn')) $('validatePatchBtn').onclick = () => void validateProposal();"
    if bind_marker not in text:
        raise SystemExit('[ERR] Could not find validation button binding marker')
    text = text.replace(bind_marker, helper + "\n" + bind_marker, 1)

# 3. Enable the button when file opens.
old = "if ($('validationBox')) { $('validationBox').className = 'skip'; $('validationBox').textContent = 'No validation run yet.'; }"
new = "if ($('validationBox')) { $('validationBox').className = 'skip'; $('validationBox').textContent = 'No validation run yet.'; } if ($('askFixBtn')) $('askFixBtn').disabled = false;"
if old in text and "askFixBtn')) $('askFixBtn').disabled = false" not in text:
    text = text.replace(old, new, 1)

# 4. Disable it when switching workspace/selecting upload.
old = "$('reportBtn').disabled = false; $('exportBtn').disabled = !u.thread_id;"
new = "$('reportBtn').disabled = false; $('exportBtn').disabled = !u.thread_id; if ($('askFixBtn')) $('askFixBtn').disabled = true;"
if old in text and "askFixBtn')) $('askFixBtn').disabled = true" not in text:
    text = text.replace(old, new, 1)

# 5. Bind button.
bind = "if ($('askFixBtn')) $('askFixBtn').onclick = () => void askAgentXToFixFile();"
if bind not in text:
    marker = "if ($('validatePatchBtn')) $('validatePatchBtn').onclick = () => void validateProposal();"
    if marker not in text:
        raise SystemExit('[ERR] Could not find button binding section')
    text = text.replace(marker, marker + "\n" + bind, 1)

# 6. Add a little button styling if needed.
css = '''
<style id="agentx-ask-fix-css">
  #askFixBtn {
    border-color: rgba(34,211,238,.35) !important;
    background: rgba(8,145,178,.16) !important;
    color: #dffbff !important;
    font-weight: 700 !important;
  }
  #askFixBtn:disabled {
    opacity: .45 !important;
    background: rgba(15,23,42,.55) !important;
    color: #7f91aa !important;
  }
</style>
'''
if 'agentx-ask-fix-css' not in text:
    text = text.replace('</head>', css + '\n</head>', 1)

p.write_text(text)
print('[OK] Added Ask AgentX to fix button and prompt bridge to workspaces.html')
PY

# Keep dist synced too, because this project has both public and dist copies.
mkdir -p AgentXWeb/dist
cp -a AgentXWeb/public/workspaces.html AgentXWeb/dist/workspaces.html

# Build if package is available. In dev-service mode this is not strictly required, but useful.
if [[ -f AgentXWeb/package.json ]]; then
  echo "[INFO] Building AgentXWeb..."
  (cd AgentXWeb && npm run build)
fi

echo "[INFO] Restarting services..."
sudo systemctl restart agentx-web || true
sudo systemctl restart agentx-api || true

echo "[OK] Installed Ask AgentX to Fix This File patch. Hard refresh with Ctrl+Shift+R."
