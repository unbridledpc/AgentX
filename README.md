# AgentX Latest Patch Bridge

Makes Workspaces always preload the latest AgentX assistant response into Patch Preview.

Supports:
- `agentx-workspace-patch` JSON blocks
- `### Replacement Content` fenced code blocks
- `**Replacement Content**` fenced code blocks
- any fenced code block
- raw plain-text response fallback, for any file extension/content type

Safety: it fills proposal + diff + validation only. It does not apply changes automatically.
