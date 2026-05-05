# AgentX Archive Chat Context Fix

This patch fixes the behavior where AgentX says it cannot read/extract an uploaded archive.

It does three things:

1. Attaches uploaded archives to the current chat thread when the WebUI sends `thread_id`.
2. Stores workspace metadata under the API data directory.
3. Injects the extracted archive summary/report/file tree into chat context before calling Ollama/AgentX.

After installation, upload a ZIP/RAR/7z from the `+` menu, then ask in the same chat:

- Find the important files.
- Find TODOs and unfinished conversions.
- Summarize the architecture.

AgentX should answer from the uploaded sandbox workspace instead of giving you a generic script.

Install:

```bash
cd ~/projects/AgentX
unzip -o AgentX_archive_chat_context_fix.zip
bash scripts/install-archive-chat-context-fix.sh ~/projects/AgentX
```

Then hard-refresh the browser with Ctrl+F5.
