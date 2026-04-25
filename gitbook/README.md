# NexAI GitBook

NexAI is a local-first, supervised AI assistant platform. It combines a Python agent runtime, a FastAPI backend, a React web UI, and an early Tauri desktop client around a policy-aware execution model.

The system is designed to run on user-controlled hardware with local runtime state, explicit safety gates, auditable tool use, and optional model providers such as Ollama or OpenAI.

## What This Book Covers

This GitBook documents the repository as it exists in this workspace:

- The product installer and managed runtime lifecycle.
- The Python core under `SolVersion2`.
- The API service under `apps/api`.
- The web UI under `SolWeb`.
- The desktop client under `apps/desktop`.
- Configuration, auth, memory, RAG, tools, plugins, skills, jobs, release packaging, and troubleshooting.

## Main Components

| Component | Path | Purpose |
| --- | --- | --- |
| Core runtime | `SolVersion2/` | Agent, tools, memory, jobs, install/runtime logic, plugins, skills, CLI |
| API service | `apps/api/` | FastAPI service exposing chat, settings, threads, RAG, file, tool, and runtime endpoints |
| Web UI | `SolWeb/` | React/Vite browser UI for chat, settings, inspector, code canvas, and runtime controls |
| Desktop UI | `apps/desktop/` | Tauri 2 desktop shell using a React/Vite frontend |
| Installers | `install.sh`, `install-sol.sh` | Ubuntu/WSL product-style installation and CLI bootstrap |
| Release tooling | `scripts/package_release.py` | Deterministic release archive builder |

## Default Local Ports

| Service | Default URL |
| --- | --- |
| API | `http://127.0.0.1:8420` |
| Web UI | `http://127.0.0.1:5173` |
| SolWeb dev server | `http://127.0.0.1:5173` |
| Desktop Vite dev server | `http://127.0.0.1:1420` |
| Ollama | `http://127.0.0.1:11434` |

## Fast Start

On a fresh Ubuntu 24.04 or compatible WSL system:

```bash
curl -fsSL https://raw.githubusercontent.com/VielNexus/NexAI/main/install.sh | bash
nexai start
nexai status
```

Then open:

```text
http://127.0.0.1:5173
```

For repo-local setup from an existing checkout:

```bash
./install-sol.sh
nexai start
```

## Important Safety Note

NexAI can be configured to read files, write files, fetch web pages, run commands, and use local or remote model providers. You are responsible for how it is configured and used after installation. Keep the API bound to localhost unless you have added authentication, strict network controls, and a deployment plan.
