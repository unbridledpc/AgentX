# CLI Reference

The Python package exposes two console scripts:

```text
nexai
sol
```

`nexai` is the supported command. `sol` exists as a compatibility alias during migration.

## Global Options

```bash
nexai --config config/sol.toml <command>
nexai --install-config ~/.config/sol/install.json <command>
```

| Option | Meaning |
| --- | --- |
| `--config` | Runtime TOML config path for direct runtime commands |
| `--install-config` | Product install metadata JSON path |

## Lifecycle Commands

```bash
nexai setup
nexai start
nexai stop
nexai restart
nexai status
nexai uninstall
nexai doctor
nexai health
nexai paths
```

## Service Commands

```bash
nexai service install
nexai service uninstall
nexai service enable
nexai service disable
nexai service status
```

These manage systemd-user service files when the install uses systemd user services.

## Runtime And Config Inspection

```bash
nexai runtime inspect
nexai config show
nexai logs api --tail 100
nexai logs web --tail 100
```

## Chat And Task Execution

```bash
nexai run "your task"
nexai run --file task.txt
cat task.txt | nexai run
nexai run
```

`nexai run` sends the prompt to `/v1/chat` on the local API when an installed runtime is present.

## Tool Execution

Run a tool through the audited agent loop:

```bash
nexai tool fs.list --reason "Inspect workspace" --json "{\"path\":\"F:/Sol Folder\"}"
```

The CLI requires a non-empty `--reason` for tool calls. This is intentional because tool activity is audited.

## RAG Ingest

```bash
nexai ingest --path ./docs --reason "Index project docs" --recursive --max_files 200
```

The ingest command goes through the agent loop and stores content in the memory/RAG backend according to policy.

## Memory Commands

```bash
nexai memory stats --reason "Check memory size"
nexai memory prune --older-than-days 30 --dry-run --reason "Review old memory cleanup"
nexai memory prune --older-than-days 30 --reason "Clean old memory"
```

Non-dry-run pruning is destructive and is blocked by unsafe-mode policy unless explicitly enabled for the active thread/context.

## Selfcheck

```bash
nexai selfcheck --mode quick
nexai selfcheck --mode full --json
nexai selfcheck --mode full --fix
```

## Jobs

```bash
nexai job create --goal "Inspect repository health" --max-steps 10
nexai job run <job_id>
nexai job show <job_id>
nexai job cancel <job_id> --reason "No longer needed"
nexai job approve <job_id>
nexai job approve <job_id> --deny --note "Plan was too risky"
```

Jobs are supervised. High-risk or destructive plans can block and require approval before continuing.

## Plugins

```bash
nexai plugins list
nexai plugins enable <plugin_id>
nexai plugins disable <plugin_id>
```

## Skills

```bash
nexai skills list
nexai skills import-pack ./path/to/skill-pack
nexai skills import-pack ./path/to/skill-pack --skill-id custom_id
```

Skill packs must contain `SKILL.md`.
