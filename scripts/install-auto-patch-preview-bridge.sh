#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$(pwd)}"
cd "$ROOT"

if [ ! -f "AgentXWeb/public/workspaces.html" ]; then
  echo "[ERR] AgentXWeb/public/workspaces.html not found. Run from AgentX repo root or pass repo path." >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
cp -a AgentXWeb/public/workspaces.html "AgentXWeb/public/workspaces.html.bak-auto-patch-preview-${TS}"

python3 - <<'PY'
from pathlib import Path

p = Path("AgentXWeb/public/workspaces.html")
text = p.read_text()

# Add an Import AgentX patch button beside Validate/Apply if missing.
if 'id="importAgentPatchBtn"' not in text:
    text = text.replace(
        '<button id="applyPatchBtn" class="primary" disabled>Apply to sandbox</button>',
        '<button id="importAgentPatchBtn" disabled>Import AgentX patch</button>\n            <button id="applyPatchBtn" class="primary" disabled>Apply to sandbox</button>',
        1,
    )

# Add a small status style for auto-import messages if not present.
if 'agentx-auto-patch-bridge-css' not in text:
    css = '''\n<style id="agentx-auto-patch-bridge-css">\n  #importAgentPatchBtn {\n    border-color: rgba(56, 189, 248, 0.35) !important;\n  }\n</style>\n'''
    text = text.replace('</head>', css + '\n</head>', 1)

bridge = r'''

// --- AgentX auto patch preview bridge ---
// Pulls the latest AgentX fix response from the attached chat thread, extracts
// replacement content, fills Patch Preview, previews the diff, and validates.
function agentxExtractWorkspacePatch(text, expectedPath) {
  const raw = String(text || '');
  if (!raw.trim()) return null;

  // 1) Preferred structured block:
  // ```agentx-workspace-patch
  // {"path":"...","content":"..."}
  // ```
  const structured = raw.match(/```(?:agentx-workspace-patch|json)\s*\n([\s\S]*?)```/i);
  if (structured) {
    try {
      const obj = JSON.parse(structured[1]);
      const content = obj.content || obj.replacement || obj.replacement_content;
      const path = obj.path || obj.file || obj.file_path;
      if (content && (!expectedPath || !path || String(path).endsWith(expectedPath) || String(expectedPath).endsWith(path))) {
        return { content: String(content), source: 'structured patch block', path: path || expectedPath };
      }
    } catch (_) {}
  }

  // 2) Markdown heading used by current Ask AgentX flow.
  const replacementHeading = raw.match(/###\s*Replacement Content[\s\S]*?```(?:python|py|lua|json|xml|bash|sh|text)?\s*\n([\s\S]*?)```/i);
  if (replacementHeading) {
    return { content: replacementHeading[1].replace(/\n$/, ''), source: 'Replacement Content block', path: expectedPath };
  }

  // 3) Alternate labels.
  const altHeading = raw.match(/(?:Replacement Content|Proposed Content|Final Content|Full Replacement)\s*:?\s*\n```(?:python|py|lua|json|xml|bash|sh|text)?\s*\n([\s\S]*?)```/i);
  if (altHeading) {
    return { content: altHeading[1].replace(/\n$/, ''), source: 'replacement code block', path: expectedPath };
  }

  // 4) Fallback: if the answer has code blocks and this workspace file is pending,
  // use the last code block that is not a diff.
  const blocks = [...raw.matchAll(/```([^\n`]*)\n([\s\S]*?)```/g)];
  for (let i = blocks.length - 1; i >= 0; i--) {
    const lang = String(blocks[i][1] || '').trim().toLowerCase();
    const body = String(blocks[i][2] || '').replace(/\n$/, '');
    if (!body.trim()) continue;
    if (lang.includes('diff') || body.startsWith('--- ') || body.includes('\n+++ ')) continue;
    if (lang === 'cmd' || lang === 'powershell' || lang === 'bash') continue;
    return { content: body, source: 'last non-diff code block', path: expectedPath };
  }

  return null;
}

async function agentxFetchThreadMessages(threadId) {
  const data = await api(`/v1/threads/${encodeURIComponent(threadId)}`);
  return data.messages || data.thread?.messages || [];
}

async function agentxAutoImportPatchFromChat(force = false) {
  const u = state.selected;
  const f = state.file;
  if (!u?.thread_id || !f?.path) {
    status('Open a thread-linked workspace file before importing an AgentX patch.');
    return false;
  }

  try {
    const messages = await agentxFetchThreadMessages(u.thread_id);
    const assistants = messages.filter((m) => m.role === 'assistant' && String(m.content || '').trim()).reverse();
    for (const msg of assistants) {
      const key = `${u.thread_id}:${f.path}:${msg.id || msg.ts || String(msg.content || '').length}`;
      if (!force && localStorage.getItem('agentx.autoPatchPreview.lastKey') === key) continue;

      const patch = agentxExtractWorkspacePatch(msg.content, f.path);
      if (!patch?.content) continue;

      $('proposedContent').value = patch.content;
      localStorage.setItem('agentx.autoPatchPreview.lastKey', key);
      switchTab('patch');
      previewDiff();
      status(`Imported AgentX patch from chat (${patch.source}). Validating proposal...`);
      try {
        await validateProposal();
      } catch (e) {
        status(`Imported patch, but validation failed to run: ${e.message}`);
      }
      return true;
    }
    status('No usable AgentX replacement-content block found in this thread yet.');
    return false;
  } catch (e) {
    status(`Failed to import AgentX patch from chat: ${e.message}`);
    return false;
  }
}

function agentxScheduleAutoPatchImport() {
  // Small delay lets the file inspector UI finish updating first.
  setTimeout(() => void agentxAutoImportPatchFromChat(false), 700);
}
'''

if 'function agentxExtractWorkspacePatch' not in text:
    idx = text.rfind('</script>')
    if idx == -1:
        raise SystemExit('[ERR] Could not find closing </script> in workspaces.html')
    text = text[:idx] + bridge + '\n' + text[idx:]

# Enable button when a file opens.
text = text.replace(
    "$('copyCurrentBtn').disabled = false; $('previewDiffBtn').disabled = false; $('applyPatchBtn').disabled = false; if ($('validatePatchBtn')) $('validatePatchBtn').disabled = false; $('findMatchesBtn').disabled = false;",
    "$('copyCurrentBtn').disabled = false; $('previewDiffBtn').disabled = false; $('applyPatchBtn').disabled = false; if ($('validatePatchBtn')) $('validatePatchBtn').disabled = false; if ($('importAgentPatchBtn')) $('importAgentPatchBtn').disabled = false; $('findMatchesBtn').disabled = false;",
    1,
)

# Trigger passive auto-import after opening a file if an AgentX response already exists.
text = text.replace(
    "status(`Opened ${path}.`);",
    "status(`Opened ${path}.`); if (typeof agentxScheduleAutoPatchImport === 'function') agentxScheduleAutoPatchImport();",
    1,
)

# Wire the manual import button.
if "importAgentPatchBtn" in text and "agentxAutoImportPatchFromChat(true)" not in text:
    marker = "if ($('validatePatchBtn')) $('validatePatchBtn').onclick = () => void validateProposal();"
    if marker in text:
        text = text.replace(marker, marker + "\nif ($('importAgentPatchBtn')) $('importAgentPatchBtn').onclick = () => void agentxAutoImportPatchFromChat(true);", 1)
    else:
        idx = text.rfind('</script>')
        text = text[:idx] + "\nif ($('importAgentPatchBtn')) $('importAgentPatchBtn').onclick = () => void agentxAutoImportPatchFromChat(true);\n" + text[idx:]

p.write_text(text)
print('[OK] Patched workspaces.html auto patch preview bridge')
PY

# Keep dist synced when present. Some installs serve public through Vite, some serve dist.
if [ -d AgentXWeb/dist ]; then
  cp -a AgentXWeb/public/workspaces.html AgentXWeb/dist/workspaces.html
fi

# Basic sanity check for expected additions.
grep -q "agentxExtractWorkspacePatch" AgentXWeb/public/workspaces.html
grep -q "importAgentPatchBtn" AgentXWeb/public/workspaces.html

echo "[OK] Auto patch preview bridge installed. Restarting services if available..."
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart agentx-api || true
  sudo systemctl restart agentx-web || true
fi

echo "[OK] Done. Hard refresh AgentX with Ctrl+Shift+R."
