# Tools, Plugins, Skills, And Jobs

## Built-In Tool Registry

Tools are registered by `SolVersion2/sol/tools/registry.py`.

Built-in tool groups include:

| Group | Examples |
| --- | --- |
| Filesystem | `fs.list`, `fs.read_text`, `fs.write_text`, `fs.move`, `fs.delete`, `fs.grep` |
| Execution | `exec.run` |
| Web | `web.fetch`, `web.search`, `web.crawl`, `web.ingest_crawl`, `web.ingest_url` |
| Repository | `repo.tree`, `repo.fetch_file`, `repo.ingest` |
| RAG | `rag.upsert_text`, `rag.query`, `rag.ingest_path` |
| Selfcheck | `selfcheck.run` |
| Tibia helpers | `tibia.search_sources`, `tibia.ingest_thread`, `tibia.learn` |
| Voice/Vision | Stub tools |
| Monster | Monster XML generation/ingest helpers |
| Hermes compatibility | Compatibility tool names such as `fs_list`, `http_get`, `devtools` |

Tool aliases include:

| Alias | Canonical |
| --- | --- |
| `fs_list` | `fs.list` |
| `fs_read_text` | `fs.read_text` |
| `fs_write_text` | `fs.write_text` |
| `web_search` | `web.search` |
| `web_fetch` | `web.fetch` |

## Tool Execution Rules

Tool execution requires:

- A valid tool name.
- Validated arguments.
- A non-empty reason.
- Passing runtime policy.
- Audit log writability for audited operations.

CLI example:

```bash
nexai tool fs.list --reason "Inspect repo root" --json "{\"path\":\"F:/Sol Folder\"}"
```

API example:

```http
POST /v1/tool
```

```json
{
  "tool": "fs.list",
  "args": { "path": "F:/Sol Folder" },
  "reason": "Inspect repo root",
  "thread_id": "optional"
}
```

## Plugins

Plugins are discovered by `PluginManager` from:

- Built-in plugins directory.
- Runtime/user plugins directory.

A plugin directory must contain `manifest.json`.

Manifest requirements:

- `id` matching `[a-z0-9][a-z0-9._-]{1,63}`.
- At least one declared tool.
- Valid `risk_level`: `low`, `medium`, `high`, or `critical`.
- Non-empty `entrypoint`.
- Optional `permissions`.
- Optional `enabled_by_default`.

Example manifest shape:

```json
{
  "id": "echo_demo",
  "name": "Echo Demo",
  "version": "0.0.1",
  "description": "Example plugin",
  "entrypoint": "plugin.py:register",
  "permissions": [],
  "risk_level": "low",
  "enabled_by_default": false,
  "tools": [
    { "name": "echo.demo", "description": "Echo input" }
  ]
}
```

The entrypoint must return a `Tool` or iterable of `Tool` objects, and the actual returned tool names must exactly match the manifest declarations.

Manage plugins:

```bash
nexai plugins list
nexai plugins enable echo_demo
nexai plugins disable echo_demo
```

Plugin enable/disable state is stored in runtime plugin state.

## Skills

Skills are instruction packs based on `SKILL.md`.

Skill discovery reads:

- Built-in skills directory.
- Runtime/user skills directory.

Skill import:

```bash
nexai skills import-pack ./skills/repo_triage
```

Skill packs can include YAML-like frontmatter in `SKILL.md`, plus optional `metadata.json`.

Common metadata fields:

| Field | Purpose |
| --- | --- |
| `id` | Skill ID |
| `name` | Display name |
| `description` | Description |
| `required_plugins` | Plugin dependencies |
| `memory_namespace` | Memory namespace |
| `risk_level` | `low`, `medium`, `high`, or `critical` |
| `examples` | Example prompts or files |

The manager copies imported skill packs into the runtime skill imports directory and writes normalized metadata.

## Jobs

Jobs are supervised autonomous tasks managed by `JobRunner`.

Job features:

- Goal-driven execution.
- Optional skill ID.
- Step budget.
- Failure budget.
- Runtime budget.
- Failure reflection.
- Retry decisions.
- Learned hint promotion.
- Human approval for high-risk plans.

Create and run:

```bash
nexai job create --goal "Inspect project health" --max-steps 10 --max-failures 3
nexai job run <job_id>
```

If a plan includes destructive tools or high/critical-risk plugin tools, the job can become blocked with a pending approval:

```bash
nexai job approve <job_id>
nexai job approve <job_id> --deny --note "Too risky"
```

Job terminal states include completed, failed, blocked, and cancelled.
