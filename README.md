# NexAI

NexAI is a local-first, supervised AI assistant platform designed for inspectable, policy-aware operation on user-controlled infrastructure. It combines a CLI agent runtime, FastAPI backend, web UI, installable extension model, and an evolving autonomous job/plugin/skill architecture while keeping auditability and approval gates central to the design.

## Overview

NexAI is built to run as a practical local system rather than a cloud-only assistant. The project separates immutable app files from mutable runtime state, supports supervised tool execution, and is being refactored toward durable Linux/WSL installs with explicit lifecycle management.

## Key Features

- Local-first runtime with explicit `app_root`, `runtime_root`, and `working_dir` separation
- Supervised agent execution with audit logging, policy enforcement, and approval-gated risky actions
- CLI, API, and web UI surfaces
- Autonomous job runner with bounded retries, reflection, and learned hints
- Manifest-driven tool plugins and instruction-based skills
- Built-in versus user-installed extension separation
- Install/runtime tooling for product-style lifecycle management

## Repository Layout

- `SolVersion2/`: core agent runtime, CLI, install/runtime system, plugins, skills, tests
- `apps/api/`: FastAPI backend bridge and service surface
- `SolWeb/`: React/Vite web UI
- `apps/desktop/`: desktop client work

## Ubuntu 24 Install

Fresh Ubuntu 24 installs are intended to start with:

```bash
curl -fsSL https://raw.githubusercontent.com/VielNexus/NexAI/main/install.sh | bash
```

That root installer:

- installs required Ubuntu packages when they are missing
- clones NexAI into `~/.local/share/nexai/app`
- builds `SolWeb/dist`
- bootstraps the NexAI CLI into `~/.local/bin/nexai`
- provisions the managed runtime under `~/.local/share/sol`

The installer uses the existing product-style runtime model:

- app bundle: `~/.local/share/nexai/app`
- bootstrap launcher: `~/.local/bin/nexai`
- managed runtime: `~/.local/share/sol`

After install:

```bash
~/.local/bin/nexai start
~/.local/bin/nexai status
```

Lifecycle commands:

```bash
~/.local/bin/nexai start
~/.local/bin/nexai stop
~/.local/bin/nexai restart
~/.local/bin/nexai status
~/.local/bin/nexai uninstall
```

Then open:

```text
http://127.0.0.1:5173
```

Notes:

- Fresh local installs default to local-first mode with login disabled.
- The default model provider is Ollama at `http://127.0.0.1:11434`
- If `~/.local/bin` is not on your `PATH`, add:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Repo-local installs are still supported from a checked-out bundle:

```bash
./install-sol.sh
```

For repo-local installs, the same lifecycle commands are available through `nexai` after setup:

```bash
nexai start
nexai stop
nexai restart
nexai status
nexai uninstall
```

## Auth Mode

Fresh local/demo installs now default to no-login local mode.

- Persistent install/runtime flag: `auth.enabled`
- Managed installs store it in `~/.config/sol/install.json` and mirror it into `~/.local/share/sol/config/sol.toml`
- Direct API override: `SOL_AUTH_ENABLED=false|true`

When `auth.enabled` is `false`, the backend accepts the local app flow without login and SolWeb does not show the sign-in gate.

To enable auth later:

1. Set `auth.enabled` to `true` in `~/.config/sol/install.json`.
2. Restart NexAI so it rewrites runtime config and restarts the API with auth enabled.
3. Set credentials with `SOL_AUTH_USER` plus `SOL_AUTH_PASSWORD` or `SOL_AUTH_PASSWORD_SHA256`.

If you are running the API directly outside the managed installer flow, set `SOL_AUTH_ENABLED=true` before startup.

## Platform Support

- Current focus: Linux and WSL
- Product-style install/runtime support is being hardened for Linux/WSL first
- Windows-native support is planned later and is not the current target for install/service behavior

## Status

Sol is under active architecture work. The current direction is production-minded, but the platform is still evolving in areas such as install flow, extension lifecycle, autonomous job execution, and release packaging.

## Development

Python components live primarily under `SolVersion2/` and `apps/api/`. The web UI lives under `SolWeb/`. Local runtime data, dependency folders, caches, and logs are intentionally excluded from version control.

## License

Apache-2.0

curl -fsSL https://raw.githubusercontent.com/VielNexus/NexAI/main/install.sh | bash
