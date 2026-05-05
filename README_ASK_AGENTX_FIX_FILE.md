# AgentX Ask AgentX to Fix This File Patch

Adds an **Ask AgentX to fix** button to the Workspaces file inspector.

## What it does

- Adds a button beside Report / Export ZIP in Workspaces.
- Builds a fix prompt from:
  - selected workspace/project/thread
  - selected file path
  - exact current file contents
  - current Patch Preview proposal if changed
  - latest validation output
  - likely matching source candidates by basename
- Sends that prompt to the parent AgentX shell with `postMessage`.
- Parent AgentX shell switches to Chat and places the prompt into the composer for review/send.

## Safety

The prompt instructs AgentX to propose sandbox-only changes. It does not modify files by itself.

## Install

```bash
cd ~/projects/AgentX
unzip -o AgentX_ask_agentx_fix_file_patch.zip
bash scripts/install-ask-agentx-fix-file.sh ~/projects/AgentX
```

Then hard refresh AgentX with Ctrl+Shift+R.
