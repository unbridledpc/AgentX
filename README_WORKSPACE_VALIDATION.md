# AgentX Workspace Validation Patch

Adds proposal/current-file validation to the Workspaces file inspector.

## Install

```bash
cd ~/projects/AgentX
unzip -o AgentX_workspace_validation_patch.zip
bash scripts/install-workspace-validation.sh ~/projects/AgentX
```

Then hard refresh AgentX with `Ctrl+Shift+R`.

## Adds

Backend:

```text
POST /v1/workbench/thread/{thread_id}/validate
```

Request:

```json
{"path":"data/scripts/TFS/scripts/tools/rope.py","content":"optional proposed content"}
```

Checks:

- `.py`: `python -m py_compile`
- `.json`: Python JSON parse
- `.xml`: Python XML parse
- `.sh`/`.bash`: `bash -n`
- `.lua`: `luac -p` when installed, otherwise skipped with warning
- other text: skipped with message

Frontend:

- Adds **Validate proposal** button to the Workspaces Patch Preview tab.
- Shows pass/fail/skipped validation output.
- Automatically validates the saved sandbox file after **Apply to sandbox**.

## Safety

Validation and edits target the extracted sandbox workspace only:

```text
work/workbench/imports/<project-id>/extracted/
```
