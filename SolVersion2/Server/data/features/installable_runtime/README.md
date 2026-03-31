# NexAI Installable Runtime

This refactor makes NexAI behave like an installable Linux/WSL product instead of assuming a repo checkout is both the app root and the mutable runtime root.

## Profiles

- `cli`: interactive CLI only, no long-running API or web process
- `standard`: CLI + API + static web UI
- `server`: CLI + API, web disabled by default
- `developer`: CLI + API + web, plus slightly broader local tool roots for development

## Commands

- `./install-sol.sh`
- `nexai setup`
- `nexai start`
- `nexai stop`
- `nexai restart`
- `nexai status`
- `nexai doctor`
- `nexai paths`
- `nexai config show`

## Path Model

Immutable app files:

- `app_root/SolVersion2`
- `app_root/apps/api`
- `app_root/SolWeb`

Mutable runtime files:

- `runtime_root/config/sol.toml`
- `runtime_root/extensions/plugins`
- `runtime_root/extensions/skills`
- `runtime_root/data/`
- `runtime_root/memory/`
- `runtime_root/logs/`
- `runtime_root/audit/`
- `runtime_root/cache/`
- `runtime_root/tmp/`
- `runtime_root/run/`
- `runtime_root/state/plugins/`
- `runtime_root/state/skills/`
- `runtime_root/state/web/solweb.config.js`

Separate working directory:

- `working_dir/`

Bootstrap CLI files:

- `~/.local/share/sol/bootstrap/venv`
- `~/.local/bin/nexai`
- `~/.local/bin/sol` (compatibility alias)

The bootstrap environment is only the installer/CLI entrypoint. NexAI still provisions a separate managed runtime under the selected `runtime_root/venv` for profiles that run the API or web UI.

Built-in extensions stay in the immutable app bundle:

- `app_root/SolVersion2/plugins`
- `app_root/SolVersion2/skills`

Runtime extensions live under the mutable runtime root:

- `runtime_root/extensions/plugins`
- `runtime_root/extensions/skills`

## Runtime Resolution Rules

1. `SOL_APP_ROOT` wins when set.
2. `SOL_RUNTIME_ROOT` wins for mutable state when set.
3. `SOL_CONFIG_PATH` wins for the generated runtime config when set.
4. If Sol loads a config from `.../config/sol.toml`, it infers that directory's parent as the runtime root.
5. If `SOL_APP_ROOT` is not set and Sol loads `.../config/sol.toml`, it also infers that parent as the local app root for relative immutable paths. This keeps dev/test installs relocatable.

## Standard Install Behavior

The standard profile serves prebuilt SolWeb assets from `SolWeb/dist`.

- End users do not need Node/Vite if the bundle already contains `dist/`
- `nexai start` writes runtime web config to `runtime_root/state/web/solweb.config.js`
- the web server injects that config dynamically while serving immutable frontend assets from the app bundle

## Bootstrap Flow

Repo/dev flow:

```bash
./install-sol.sh
```

Expected future release flow:

```bash
curl -fsSL <install-url> | bash
```

Both flows are intended to bootstrap the CLI first and then hand off to `nexai setup` for managed runtime provisioning.

## Product Bundle Hygiene

The repo now includes [`.productignore`](/F:/Sol%20Folder/.productignore) to document which dev-only artifacts should stay out of product bundles, including `.git`, local virtual environments, `node_modules`, caches, tests, and local workspace notes.

## Service Setup

Current support is Linux/WSL-first:

- `systemd-user` unit file generation is implemented
- native Windows service installation is intentionally deferred

Generated user units:

- `~/.config/systemd/user/sol-api.service`
- `~/.config/systemd/user/sol-web.service`

## WSL Guidance

- Prefer storing runtime data under the Linux filesystem, not the mounted Windows filesystem, for better permissions and I/O behavior
- Example runtime root: `~/.local/share/sol`
- Example working directory: `~/sol-work`
- If `systemd --user` is unavailable in your WSL image, use `nexai start` / `nexai stop` directly instead of service mode

## Example Generated Layout

```text
~/.local/share/sol/
  audit/
  cache/
  config/
    sol.toml
  data/
    api/
  extensions/
    plugins/
    skills/
  logs/
  memory/
  run/
  state/
    plugins/
    skills/
    web/
      solweb.config.js
  tmp/
```

## Example Generated Config Notes

- runtime paths stay under `runtime_root`
- immutable app paths are stored as absolute paths pointing at the installed app bundle
- the API and web lifecycle commands populate `SOL_APP_ROOT`, `SOL_RUNTIME_ROOT`, `SOL_CONFIG_PATH`, and `SOL_API_DATA_DIR` so subprocesses do not depend on the caller's current working directory
