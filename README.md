First thing before using this system. I am in no way, shape or form how you use NexAI! This system is being ran on your local hardware with/without models ran by other providers other than me. I have NO control over this system once installed on your system therefor you are the sole responsible person on how it is used, and how it reacts! I have no say of ANYTHING once you download/install NexAI!
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
nexai start
nexai status
```

Lifecycle commands:

```bash
nexai start
nexai stop
nexai restart
nexai status
nexai uninstall
```

Then open:

```text
http://127.0.0.1:5173
```

Notes:

- Fresh local installs default to local-first mode with login disabled.
- The default model provider is Ollama at `http://127.0.0.1:11434`
- The installer updates `PATH` for the current install session and persists `~/.local/bin` into `.bashrc` or `.zshrc` when needed.

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

Verified grounded demo flows are documented in `SolVersion2/docs/reliability-demos.md`.

## Clean Source Repository Guide

The repository should contain source code, manifests, lockfiles, installer scripts, tests, documentation, and checked-in examples only. Generated output and local runtime state should stay out of git.

Canonical source areas:

- `SolVersion2/`: Python runtime package, CLI, tests, default config, built-in plugins, built-in skills
- `apps/api/`: FastAPI backend service and tests
- `SolWeb/`: React/Vite web UI source and npm lockfile
- `apps/desktop/`: Tauri desktop client source, npm lockfile, Rust manifest, and Cargo lockfile
- `scripts/`: release and maintenance scripts
- `install.sh`, `install-sol.sh`, `start-sol.ps1`: installer and launcher helpers

Do not commit:

- `node_modules/`, `dist/`, `build/`, Rust `target/`
- Python caches, pytest caches, virtual environments, egg-info
- runtime `data/`, `threads/`, logs, audit logs, memory files, SQLite databases, uploaded files
- `.env` files, tokens, private keys, certificates, or credentials

If a folder is named `data` but contains source documentation, preserve it. For example, `SolVersion2/Server/data/features/` currently contains feature documentation and is intentionally tracked.

## Prerequisites

Recommended development tools:

- Python 3.11 or newer
- Node.js 20 or newer
- npm
- Git
- Rust and Cargo for desktop/Tauri checks
- Ollama if testing the local model provider

## Backend And Runtime Setup

Install the Python runtime in editable mode:

```bash
cd SolVersion2
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[developer]"
```

PowerShell:

```powershell
cd SolVersion2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[developer]"
```

Run Python tests from the repository root:

```bash
PYTHONPATH="$PWD/SolVersion2:$PWD/apps/api" python -m pytest SolVersion2/tests apps/api/tests
```

PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\SolVersion2;$PWD\apps\api"
python -m pytest SolVersion2\tests apps\api\tests
```

Run the API directly for development:

```bash
cd apps/api
python -m pip install -r requirements.txt
PYTHONPATH="../../SolVersion2:." python -m sol_api --host 127.0.0.1 --port 8420
```

## Web UI Setup

```bash
cd SolWeb
npm ci
npm run typecheck
npm run test
npm run build
```

The generated `SolWeb/dist/` folder is build output and should not be committed.

Runtime API configuration for the web UI is in:

```text
SolWeb/public/solweb.config.js
```

For local development it should point at:

```text
http://127.0.0.1:8420
```

## Desktop Setup

```bash
cd apps/desktop
npm ci
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

For Tauri dev mode:

```bash
npm run tauri:dev
```

Generated `apps/desktop/dist/`, `apps/desktop/node_modules/`, and `apps/desktop/src-tauri/target/` are not source files.

## Environment Variables

Use `.env.example` as a safe template for local settings. Do not commit `.env` or real secrets.

Common variables:

- `SOL_API_HOST`, `SOL_API_PORT`
- `SOL_AUTH_ENABLED`, `SOL_AUTH_USER`, `SOL_AUTH_PASSWORD`, `SOL_AUTH_PASSWORD_SHA256`
- `SOL_OPENAI_API_KEY`, `SOL_OPENAI_MODEL`, `SOL_OPENAI_BASE_URL`
- `SOL_OLLAMA_BASE_URL`, `SOL_OLLAMA_REQUEST_TIMEOUT_S`
- `SOL_RAG_ENABLED`, `SOL_RAG_ALLOWED_ROOTS`
- `SOL_FS_ENABLED`, `SOL_FS_ALLOWED_ROOTS`, `SOL_FS_WRITE_ENABLED`, `SOL_FS_DELETE_ENABLED`
- `SOL_WEB_ENABLED`, `SOL_WEB_ALLOWED_HOSTS`

## Runtime Data Locations

The source tree should remain rebuildable without local runtime state.

Recommended runtime locations:

- Linux config: `~/.config/sol/`
- Linux data: `~/.local/share/sol/`
- Linux logs: `~/.local/state/sol/logs/`
- Windows config/data/logs: user AppData locations
- macOS config/data/logs: user Library locations

The current installer already separates app files from managed runtime files for Linux/WSL installs:

- app bundle: `~/.local/share/nexai/app`
- launcher: `~/.local/bin/nexai`
- managed runtime: `~/.local/share/sol`

## Local Cleanup And Reset

To return a checkout to source-only form, remove generated files and reinstall dependencies from lockfiles:

```bash
git status --short
```

Safe generated folders to delete locally include:

- `**/node_modules/`
- `**/dist/`
- `**/build/`
- `**/__pycache__/`
- `**/.pytest_cache/`
- `**/.venv/`
- `SolVersion2/data/`
- `SolVersion2/logs/`
- `apps/api/sol_api/data/`

After cleanup, rebuild from source using the setup commands above.

## License

Apache-2.0

