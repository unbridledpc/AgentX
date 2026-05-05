# AgentX

Supervised local agent runtime for AgentX.

Key capabilities:

- audited tool execution
- local memory and retrieval
- supervised autonomous jobs
- manifest-driven tool plugins
- instruction-only skills
- local `SKILL.md` skill-pack import
- installable runtime with `agentx setup`, `agentx start`, `agentx stop`, `agentx status`, and product-style runtime/data separation

## Bootstrap Install

For a fresh Ubuntu 24 machine, use the repo-root installer:

```bash
curl -fsSL https://raw.githubusercontent.com/VielNexus/NexAI/main/install.sh | bash
```

That wrapper installs system prerequisites, clones the repo, builds `AgentXWeb/dist`, and then hands off to the bundle-local bootstrap script:

```bash
./install-agentx.sh
```

The bundle-local bootstrap step:

- creates a lightweight bootstrap virtual environment automatically
- installs the AgentX CLI into that bootstrap environment
- writes a stable user launcher at `~/.local/bin/agentx`
- keeps `~/.local/bin/agentx` as a compatibility alias during migration
- then starts `agentx setup` so AgentX can provision its managed runtime separately

The bootstrap environment is not the main runtime. For `standard`, `server`, and `developer` profiles, `agentx setup` still provisions the real managed runtime under `runtime_root/venv`.

## Developer note: canonical Python package

AgentX backend source now lives in the lowercase `agentx/` package. Do not patch old duplicate folders such as `AgentX/`, `core/`, `cli/`, `tools/`, `jobs/`, or `install/` at the source root. Run `python scripts/check_package_tree.py` before packaging or pushing.

## Private Phase 3 Workbench / ZIP Analyzer

This patched bundle includes an experimental read-only Workbench ZIP Analyzer. It imports a project/server ZIP into a sandbox, inventories source/config files, scans for syntax issues, risky patterns, and converted TFS placeholder work, then writes `final_report.md`.

CLI:

```bash
agentx workbench import-zip /path/to/Server.zip --workspace work/workbench --name server-private-test
```

Web playground prototype:

```text
AgentXWeb/dist/playground.html
```

Docs: `docs/phase-3-workbench-zip-analyzer.md`

Safety: v0.1 does not edit files, run project code, install dependencies, touch live folders, commit, or push.
