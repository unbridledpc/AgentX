# AgentX Chat Archive Workspace Patch

This patch turns uploaded server archives into persistent, thread-linked sandbox workspaces.

Goal:
- Upload archive from WebUI `+` menu.
- Archive extracts into a sandbox workspace.
- The current chat/thread can remember and reuse that workspace.
- AgentX can read/write files inside the uploaded extracted copy only.
- Live server files are not touched.

Install:

```bash
cd ~/projects/AgentX
unzip -o AgentX_chat_archive_workspace_patch.zip
bash scripts/install-chat-archive-workspace.sh ~/projects/AgentX
```

Then hard-refresh the browser: Ctrl+F5.

Notes:
- This patch is experimental/private.
- Writes are limited to the uploaded/extracted workspace path.
- It installs `python-multipart` if needed for FastAPI uploads.
- It creates a systemd PYTHONPATH override for the AgentX API service.
