# AgentX Copy Button Fix

Fixes the response hover `Copy` button on LAN/HTTP deployments.

Why it broke:
- `navigator.clipboard.writeText()` only works reliably in secure contexts (`https://` or `localhost`).
- AgentX is commonly opened at `http://192.168.x.x:5173`, so the browser can silently reject clipboard writes.

What this patch does:
- Adds `src/ui/clipboard.ts`.
- Uses the modern Clipboard API when available.
- Falls back to a hidden textarea + `document.execCommand("copy")` for homelab HTTP access.
- Updates response copy, code block copy, and Code Canvas copy.

Install:

```bash
cd ~/projects/AgentX
unzip -o AgentX_copy_button_fix.zip
bash scripts/install-copy-button-fix.sh ~/projects/AgentX
```

Then hard refresh the browser with `Ctrl+F5`.
