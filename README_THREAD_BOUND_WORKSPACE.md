# AgentX Thread-Bound Archive Workspace Patch

This implements the long-term Option A flow:

1. WebUI uploads archive with the current chat `thread_id`.
2. Backend extracts/analyzes the archive in `work/workbench/imports/...`.
3. Backend writes `work/workbench/thread_workspaces.json` mapping `thread_id -> workspace/report/inventory`.
4. Chat route injects the mapped workspace report/file tree into model context.
5. AgentX should answer from the uploaded archive instead of saying it cannot access files.

Install:

```bash
cd ~/projects/AgentX
unzip -o AgentX_thread_bound_workspace_patch.zip
bash scripts/install-thread-bound-workspace.sh ~/projects/AgentX
```

Test:

```bash
curl http://127.0.0.1:8000/v1/status
find work/workbench -maxdepth 2 -type f -name thread_workspaces.json -print -exec cat {} \;
```

Then in the WebUI:

1. Hard refresh with Ctrl+F5.
2. Open a chat.
3. Use `+ -> Upload server archive`.
4. Ask: `Find the most important files in the uploaded archive.`

Safety: edits apply only to the extracted sandbox workspace, not live server files.
