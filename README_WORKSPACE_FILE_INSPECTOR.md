# AgentX Workspace File Inspector Patch

Adds a stronger Workspaces UI for uploaded archive sandboxes.

## Features

- List uploaded archive workspaces.
- View workspace file tree.
- Open/read files inside the extracted sandbox.
- Find matching source candidates by basename.
- Preview replacement-content diffs.
- Apply approved edits only to the sandbox copy using the existing thread file endpoint.
- Export edited workspace ZIP through the existing thread export endpoint.
- Ensures `/v1/workbench/uploads` endpoints exist for the Workspaces page.

## Install

```bash
cd ~/projects/AgentX
unzip -o AgentX_workspace_file_inspector_patch.zip
bash scripts/install-workspace-file-inspector.sh ~/projects/AgentX
```

Then hard refresh the WebUI with Ctrl+Shift+R.

## Notes

This patch does not edit live server files. It only edits files under:

```text
work/workbench/imports/<project-id>/extracted/
```

When applying a sandbox edit, the backend file writer creates a timestamped backup if the target exists.
