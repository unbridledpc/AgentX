#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"

echo "[INFO] Installing AgentX latest patch bridge in $ROOT"

APP="AgentXWeb/src/ui/App.tsx"
WS="AgentXWeb/public/workspaces.html"
DIST_WS="AgentXWeb/dist/workspaces.html"

if [ ! -f "$APP" ]; then echo "[ERR] Missing $APP" >&2; exit 1; fi
if [ ! -f "$WS" ]; then echo "[ERR] Missing $WS" >&2; exit 1; fi

STAMP="$(date +%Y%m%d-%H%M%S)"
cp -a "$APP" "$APP.bak-latest-patch-bridge-$STAMP"
cp -a "$WS" "$WS.bak-latest-patch-bridge-$STAMP"
[ -f "$DIST_WS" ] && cp -a "$DIST_WS" "$DIST_WS.bak-latest-patch-bridge-$STAMP" || true

python3 - <<'PY'
from pathlib import Path
import re

app = Path("AgentXWeb/src/ui/App.tsx")
text = app.read_text()

helper = r'''
function rememberAgentXLatestPatchResponse(content: string) {
  const text = String(content || "");
  if (!text.trim()) return;

  const payload = JSON.stringify({
    ts: Date.now(),
    content: text,
  });

  try {
    // Always keep the latest assistant response so Workspaces can preload any patch text,
    // even plain text such as "Title: This is\nheader: Sample!".
    window.localStorage.setItem("agentx.latestAssistantResponse", payload);
    window.sessionStorage.setItem("agentx.latestAssistantResponse", payload);

    // Keep legacy names too, so existing Workspaces import buttons keep working.
    window.localStorage.setItem("agentx.lastAssistantPatch", text);
    window.localStorage.setItem("agentx.pendingPatchResponse", text);
    window.sessionStorage.setItem("agentx.lastAssistantPatch", text);
    window.sessionStorage.setItem("agentx.pendingPatchResponse", text);

    window.dispatchEvent(new CustomEvent("agentx-workspace-patch-response", { detail: { content: text, ts: Date.now() } }));
  } catch {
    // Storage can fail in private mode; Workspaces still has manual paste fallback.
  }
}

'''

if "function rememberAgentXLatestPatchResponse" not in text:
    # Prefer inserting inside the component before the workbench callbacks.
    marker = "  const importWorkbenchArchives = useCallback"
    idx = text.find(marker)
    if idx == -1:
        marker = "  const commandDeckStatusItems"
        idx = text.find(marker)
    if idx == -1:
        # Safe fallback near top-level imports. Function does not need component state.
        idx = 0
    text = text[:idx] + helper + "\n" + text[idx:]
    print("[OK] inserted latest response helper")
else:
    print("[OK] latest response helper already present")

changes = 0

# 1) Stream done event patterns: event/e payload has .content.
patterns = [
    (r'if \((\w+)\.event === ["\']done["\']\) \{', lambda m: f'if ({m.group(1)}.event === "done") {{\n            rememberAgentXLatestPatchResponse({m.group(1)}.content || "");'),
    (r'if \((\w+)\.event === `done`\) \{', lambda m: f'if ({m.group(1)}.event === `done`) {{\n            rememberAgentXLatestPatchResponse({m.group(1)}.content || "");'),
]
for pat, repl in patterns:
    def sub(m):
        # Avoid double insertion immediately after this match.
        following = text[m.end():m.end()+140]
        if "rememberAgentXLatestPatchResponse" in following:
            return m.group(0)
        return repl(m)
    new_text, n = re.subn(pat, sub, text, count=4)
    if n:
        text = new_text
        changes += n

# 2) Compact/minified-ish done handler pattern used in some builds: e.event === "done" && (...
for pat in [r'(\w+)\.event === ["\']done["\'] &&', r'(\w+)\.event===`done`&&', r'(\w+)\.event === `done` &&']:
    def sub_done(m):
        var = m.group(1)
        before = text[max(0, m.start()-120):m.start()]
        if "rememberAgentXLatestPatchResponse" in before:
            return m.group(0)
        return f'{var}.event === "done" && (rememberAgentXLatestPatchResponse({var}.content || ""), true) &&'
    new_text, n = re.subn(pat, sub_done, text, count=2)
    if n:
        text = new_text
        changes += n

# 3) Before saving assistant message, capture common result variables.
save_patterns = [
    (r'(const\s+\w+\s*=\s*await\s+appendMessage\([^\n]+content:\s*result\.content,)', 'result.content'),
    (r'(const\s+\w+\s*=\s*await\s+appendMessage\([^\n]+content:\s*p\.content,)', 'p.content'),
    (r'(let\s+\w+\s*=\s*await\s+\w+\([^\n]+content:\s*p\.content,)', 'p.content'),
    (r'(let\s+\w+\s*=\s*await\s+\w+\([^\n]+content:\s*result\.content,)', 'result.content'),
]
for pat, expr in save_patterns:
    if f"rememberAgentXLatestPatchResponse({expr}" in text:
        continue
    new_text, n = re.subn(pat, f'rememberAgentXLatestPatchResponse({expr} || "");\n      \\1', text, count=1)
    if n:
        text = new_text
        changes += n

# 4) Very broad fallback: whenever the stream final variable p.content is assigned to local storage area.
# Insert before known "let m = await" minified-style from previous builds if present.
needle = 'let m=await ve(e.id,{role:`assistant`,content:p.content'
if needle in text and 'rememberAgentXLatestPatchResponse(p.content' not in text:
    text = text.replace(needle, 'rememberAgentXLatestPatchResponse(p.content || "");\nlet m=await ve(e.id,{role:`assistant`,content:p.content', 1)
    changes += 1

app.write_text(text)
print(f"[OK] App.tsx latest-response capture patches applied: {changes}")
PY

python3 - <<'PY'
from pathlib import Path

ws = Path("AgentXWeb/public/workspaces.html")
text = ws.read_text()

bridge = r'''
<script id="agentx-always-latest-patch-bridge-v4">
(function () {
  let lastImportedStamp = "";
  let userEditedProposal = false;

  function getEl(id) { return document.getElementById(id); }
  function setStatus(msg) { if (typeof status === "function") status(msg); }

  function parseStored(raw) {
    if (!raw) return null;
    const text = String(raw);
    try {
      const obj = JSON.parse(text);
      if (obj && typeof obj.content === "string") {
        return { content: obj.content, ts: Number(obj.ts || 0) };
      }
    } catch {}
    return { content: text, ts: 0 };
  }

  function stripFence(s) {
    return String(s || "").replace(/^\s+|\s+$/g, "");
  }

  function extractJsonPatch(src) {
    const jsonFence = src.match(/```(?:json|agentx-workspace-patch)?\s*([\s\S]*?"(?:content|replacement|replacement_content)"[\s\S]*?)```/i);
    if (!jsonFence) return "";
    try {
      const obj = JSON.parse(jsonFence[1]);
      return String(obj.content || obj.replacement || obj.replacement_content || "").trimEnd() + "\n";
    } catch { return ""; }
  }

  function extractReplacementSection(src) {
    const patterns = [
      /###\s*Replacement Content\s*```[\w.+-]*\s*([\s\S]*?)```/i,
      /##\s*Replacement Content\s*```[\w.+-]*\s*([\s\S]*?)```/i,
      /\*\*Replacement Content\*\*\s*```[\w.+-]*\s*([\s\S]*?)```/i,
      /Replacement Content\s*```[\w.+-]*\s*([\s\S]*?)```/i,
    ];
    for (const re of patterns) {
      const m = src.match(re);
      if (m && m[1] && m[1].trim()) return m[1].trimEnd() + "\n";
    }

    // Replacement Content without a fenced block: capture until next markdown heading.
    const plain = src.match(/(?:###|##|\*\*)?\s*Replacement Content\*{0,2}\s*\n+([\s\S]*?)(?:\n#{2,3}\s|\n\*\*[^\n]+\*\*|$)/i);
    if (plain && plain[1] && plain[1].trim()) return plain[1].trimEnd() + "\n";

    return "";
  }

  function extractFirstCodeFence(src) {
    const m = src.match(/```[\w.+-]*\s*([\s\S]*?)```/);
    if (m && m[1] && m[1].trim()) return m[1].trimEnd() + "\n";
    return "";
  }

  function extractBestProposal(raw) {
    const src = String(raw || "").trim();
    if (!src) return "";

    // 1. Explicit AgentX patch JSON wins.
    const json = extractJsonPatch(src);
    if (json) return json;

    // 2. Replacement Content section wins over diff/explanation.
    const replacement = extractReplacementSection(src);
    if (replacement) return replacement;

    // 3. If the answer only contains a code block, use it.
    const code = extractFirstCodeFence(src);
    if (code) return code;

    // 4. Final fallback: use the entire latest AgentX response as the proposed replacement.
    // This supports plain text files, Lua, config files, markdown, and examples like:
    // "Title: This is\nheader: Sample!".
    return src.trimEnd() + "\n";
  }

  function latestStoredResponse() {
    const keys = [
      "agentx.latestAssistantResponse",
      "agentx.pendingPatchResponse",
      "agentx.lastAssistantPatch",
      "agentx.lastFixResponse",
      "agentx.workspacePatchResponse"
    ];

    let best = null;
    for (const key of keys) {
      for (const storage of [window.localStorage, window.sessionStorage]) {
        try {
          const parsed = parseStored(storage.getItem(key));
          if (!parsed || !parsed.content) continue;
          if (!best || parsed.ts >= best.ts) best = { ...parsed, key };
        } catch {}
      }
    }
    return best;
  }

  async function preloadLatestAgentXPatch(options = {}) {
    const force = Boolean(options.force);
    const proposed = getEl("proposedContent");
    if (!proposed) return false;
    if (!state || !state.file || !state.file.path) return false;
    if (userEditedProposal && !force) return false;

    const latest = latestStoredResponse();
    if (!latest || !latest.content) return false;

    const stamp = `${latest.ts}:${latest.content.length}:${state.file.path}`;
    if (!force && stamp === lastImportedStamp) return false;

    const proposal = extractBestProposal(latest.content);
    if (!proposal.trim()) return false;

    proposed.value = proposal;
    lastImportedStamp = stamp;
    userEditedProposal = false;

    if (typeof switchTab === "function") switchTab("patch");
    if (typeof previewDiff === "function") previewDiff();
    if (typeof validateProposal === "function") {
      try { await validateProposal(); } catch (err) { setStatus(`Auto-validation failed: ${err.message || err}`); }
    }

    setStatus(`Loaded latest AgentX response into Patch Preview.`);
    return true;
  }

  // Expose for buttons and debugging.
  window.agentxExtractBestProposal = extractBestProposal;
  window.agentxPreloadLatestAgentXPatch = preloadLatestAgentXPatch;

  function wireProposalTracking() {
    const proposed = getEl("proposedContent");
    if (proposed && proposed.dataset.agentxTrackEdit !== "1") {
      proposed.dataset.agentxTrackEdit = "1";
      proposed.addEventListener("input", () => { userEditedProposal = true; });
    }
  }

  function wireImportButton() {
    const btn = getEl("importAgentXPatchBtn");
    if (btn && btn.dataset.agentxAlwaysLatest !== "1") {
      btn.dataset.agentxAlwaysLatest = "1";
      btn.textContent = "Load latest AgentX patch";
      btn.addEventListener("click", async () => {
        const ok = await preloadLatestAgentXPatch({ force: true });
        if (!ok) {
          const pasted = window.prompt("No latest AgentX response found. Paste AgentX response or replacement text here:");
          if (!pasted) return;
          const proposed = getEl("proposedContent");
          proposed.value = extractBestProposal(pasted);
          userEditedProposal = false;
          if (typeof switchTab === "function") switchTab("patch");
          if (typeof previewDiff === "function") previewDiff();
          if (typeof validateProposal === "function") await validateProposal();
        }
      });
    }
  }

  function wrapOpenFile() {
    if (window.__agentxOpenFileLatestPatchWrapped) return;
    if (typeof window.openFile !== "function") return;
    const original = window.openFile;
    window.openFile = async function (...args) {
      const result = await original.apply(this, args);
      userEditedProposal = false;
      setTimeout(() => preloadLatestAgentXPatch({ force: false }), 350);
      return result;
    };
    window.__agentxOpenFileLatestPatchWrapped = true;
  }

  window.addEventListener("storage", () => preloadLatestAgentXPatch({ force: false }));
  window.addEventListener("agentx-workspace-patch-response", () => preloadLatestAgentXPatch({ force: true }));

  function boot() {
    wireProposalTracking();
    wireImportButton();
    wrapOpenFile();
    preloadLatestAgentXPatch({ force: false });
  }

  boot();
  setInterval(boot, 1000);
})();
</script>
'''

if "agentx-always-latest-patch-bridge-v4" not in text:
    text = text.replace("</body>", bridge + "\n</body>")
else:
    print("[OK] Workspaces latest patch bridge already present")

ws.write_text(text)
print("[OK] Workspaces always-latest patch bridge installed")
PY

if [ -f "$DIST_WS" ]; then
  cp -a "$WS" "$DIST_WS"
  echo "[OK] Synced workspaces.html to dist"
fi

# Build to catch TypeScript errors. AgentX currently runs Vite dev, but build still validates syntax.
if [ -d AgentXWeb ]; then
  echo "[INFO] Building AgentXWeb..."
  (cd AgentXWeb && npm run build)
fi

sudo systemctl restart agentx-web || true
sudo systemctl restart agentx-api || true

echo "[OK] Installed latest AgentX patch bridge. Hard refresh with Ctrl+Shift+R."
