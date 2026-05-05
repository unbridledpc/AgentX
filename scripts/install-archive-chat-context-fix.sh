#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$HOME/projects/AgentX}"
cd "$ROOT"
echo "[INFO] Installing AgentX archive chat context fix in $ROOT"
mkdir -p AgentX/agentx/workbench apps/api/agentx_api/routes
cp -a payload/AgentX/agentx/workbench/archive_workspace.py AgentX/agentx/workbench/archive_workspace.py
cp -a payload/apps/api/agentx_api/routes/workbench.py apps/api/agentx_api/routes/workbench.py
# Ensure playground exposes both zip and generic archive functions.
if ! grep -q "def import_and_analyze_archive" AgentX/agentx/workbench/playground.py 2>/dev/null; then
  cat >> AgentX/agentx/workbench/playground.py <<'PY'

# Compatibility wrapper for archive upload routes.
def import_and_analyze_archive(archive_path, workspace_root, *, name=None, **kwargs):
    return import_and_analyze_zip(archive_path, workspace_root, name=name)
PY
fi
# Patch chat.py so active uploaded archive context is injected before model calls.
python3 - <<'PY'
from pathlib import Path
p = Path('apps/api/agentx_api/routes/chat.py')
s = p.read_text(encoding='utf-8')
if 'from agentx.workbench.archive_workspace import build_thread_workspace_context' not in s:
    anchor = 'from agentx_api.agentx_bridge import AgentXUnavailable, get_agent_for_thread, get_handle\n'
    s = s.replace(anchor, anchor + 'from agentx.workbench.archive_workspace import build_thread_workspace_context\n')
helper = r'''

def _augment_with_workspace_context(retrieved: str, thread_id: str | None, user_message: str, owner_id: str | None = None) -> str:
    if not thread_id:
        return retrieved
    try:
        ctx = build_thread_workspace_context(thread_id, user_message, owner_id=owner_id, max_chars=24000)
    except Exception:
        return retrieved
    if not ctx:
        return retrieved
    return (retrieved + "\n\n" if retrieved else "") + ctx
'''
if 'def _augment_with_workspace_context(' not in s:
    s = s.replace('def _rag_store() -> RagStore:\n', helper + '\ndef _rag_store() -> RagStore:\n')
# Add augmentation after each RAG retrieval in legacy/streaming branches.
needle = 'retrieved, rag_sources, rag_hit_count = _retrieve_rag(request.message)\n'
replacement = needle + '                retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n'
# Replace only lines with 16 spaces indentation.
s = s.replace('                ' + needle.strip() + '\n', '                ' + needle.strip() + '\n                retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n')
# Replace lines with 8 spaces indentation.
s = s.replace('        ' + needle.strip() + '\n', '        ' + needle.strip() + '\n        retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n')
# De-duplicate if script ran twice.
s = s.replace('retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n                retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)', 'retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)')
s = s.replace('retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)\n        retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)', 'retrieved = _augment_with_workspace_context(retrieved, thread_id, request.message, owner_id=user_id)')
# Patch preferred AgentX agent path: append workspace context to the message passed to agent.chat.
if 'agent_user_message = request.message' not in s:
    target = '        try:\n            res = agent.chat(\n                user_message=request.message,\n'
    repl = '        agent_user_message = request.message\n        workspace_ctx = build_thread_workspace_context(effective_thread_id, request.message, owner_id=effective_user, max_chars=24000) if effective_thread_id else ""\n        if workspace_ctx:\n            agent_user_message = request.message + "\\n\\n" + workspace_ctx\n        try:\n            res = agent.chat(\n                user_message=agent_user_message,\n'
    if target in s:
        s = s.replace(target, repl)
    else:
        print('[WARN] Could not patch preferred AgentX agent path automatically; legacy paths still patched.')
p.write_text(s, encoding='utf-8')
PY
# Patch frontend source if present so archive uploads include current thread_id.
python3 - <<'PY'
from pathlib import Path
client = Path('AgentXWeb/src/api/client.ts')
if client.exists():
    s = client.read_text(encoding='utf-8')
    s = s.replace('export async function importWorkbenchArchive(file: File, projectName?: string): Promise<WorkbenchImportResponse> {', 'export async function importWorkbenchArchive(file: File, projectName?: string, threadId?: string): Promise<WorkbenchImportResponse> {')
    if 'if (threadId?.trim()) form.append("thread_id", threadId.trim());' not in s:
        s = s.replace('  if (projectName?.trim()) form.append("project_name", projectName.trim());\n', '  if (projectName?.trim()) form.append("project_name", projectName.trim());\n  if (threadId?.trim()) form.append("thread_id", threadId.trim());\n')
    client.write_text(s, encoding='utf-8')
app = Path('AgentXWeb/src/ui/App.tsx')
if app.exists():
    s = app.read_text(encoding='utf-8')
    s = s.replace('const result = await importWorkbenchArchive(file, name);', 'const result = await importWorkbenchArchive(file, name, activeThread?.id);')
    # Keep hooks roughly correct where this callback existed in the patched UI.
    s = s.replace('  }, [setSystemMessage]);\n\n  const insertFileSearchPrompt', '  }, [setSystemMessage, activeThread?.id]);\n\n  const insertFileSearchPrompt')
    app.write_text(s, encoding='utf-8')
PY
# Build frontend if source changed and npm is available; otherwise the user can run npm build later.
if [ -f AgentXWeb/package.json ] && command -v npm >/dev/null 2>&1; then
  echo "[INFO] Building AgentXWeb..."
  (cd AgentXWeb && npm run build) || echo "[WARN] npm build failed; source was patched but dist may need manual rebuild."
fi
PYTHONPATH="$ROOT/AgentX:$ROOT/apps/api" python3 - <<'PY'
from agentx.workbench.playground import import_and_analyze_archive, import_and_analyze_zip
from agentx.workbench.archive_workspace import build_thread_workspace_context
print('[OK] workbench archive imports and chat context module are available')
PY
sudo systemctl restart agentx-api
sudo systemctl restart agentx-web
sleep 1
systemctl status agentx-api --no-pager || true
echo "[OK] Installed archive chat context fix. Hard refresh AgentX WebUI with Ctrl+F5."
