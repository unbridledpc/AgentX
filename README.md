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

## Install Note

Linux/WSL bootstrap installs are now intended to start with:

```bash
./install-sol.sh
```

That bootstrap step creates a lightweight user-local CLI environment and installs `~/.local/bin/nexai` plus a legacy compatibility alias at `~/.local/bin/sol`. After bootstrap install, NexAI keeps its managed runtime model:

- bootstrap environment: CLI + installer entrypoint
- managed runtime: created later by `nexai setup` under the chosen `runtime_root/venv`

The future release flow is intended to use the same bootstrap model via a hosted installer script:

```bash
curl -fsSL <install-url> | bash
```

Built frontend assets are still expected to ship with release bundles rather than being rebuilt on end-user machines for normal standard installs.

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
