# AgentX Auto Patch Preview Bridge

Adds an `Import AgentX patch` bridge to Workspaces.

Flow:

1. Open a workspace file.
2. Ask AgentX to fix it.
3. When AgentX replies with `### Replacement Content` or a structured `agentx-workspace-patch` block, return to Workspaces.
4. Workspaces imports the replacement into Patch Preview, runs diff preview, and validates the proposal.
5. User still manually clicks `Apply to sandbox`.

Install:

```bash
cd ~/projects/AgentX
unzip -o AgentX_auto_patch_preview_bridge.zip
bash scripts/install-auto-patch-preview-bridge.sh ~/projects/AgentX
```

Hard refresh the browser with Ctrl+Shift+R.
