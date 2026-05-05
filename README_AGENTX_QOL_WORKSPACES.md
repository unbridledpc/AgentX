# AgentX QoL Workspaces Patch

Adds three requested quality-of-life features:

1. Clear all chats at once
   - `DELETE /v1/threads?delete_workspaces=false`
   - Clears thread JSON files and thread-workspace mappings.
   - Keeps uploaded workspace folders unless `delete_workspaces=true`.

2. View uploaded archive workspaces
   - `GET /v1/workbench/uploads`
   - `GET /v1/workbench/uploads/{project_id}`
   - `GET /v1/workbench/uploads/{project_id}/tree`
   - `GET /v1/workbench/uploads/{project_id}/report`
   - `DELETE /v1/workbench/uploads/{project_id}`
   - Adds a static management page at `/workspaces.html`.

3. Better upload / drag and drop
   - Adds a standalone drag/drop page at `/workspaces.html`.
   - Adds a global archive drag/drop handler to the React chat UI when the expected App.tsx insertion point is found.

## Install

From the AgentX repo root:

```bash
cd ~/projects/AgentX
unzip -o AgentX_qol_workspaces_patch.zip
bash scripts/install-agentx-qol-workspaces.sh ~/projects/AgentX
```

Then hard refresh the browser with Ctrl+Shift+R.

Open:

```text
http://192.168.68.210:5173/workspaces.html
```

## Safety

Clearing chats does not delete uploaded archive workspaces unless explicitly requested. Workspace deletes remove only the extracted/uploaded sandbox folder under `work/workbench/imports/<project_id>`.
