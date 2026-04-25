# Repository Map

## Root Files

| Path | Purpose |
| --- | --- |
| `README.md` | Main project overview, install instructions, lifecycle commands, auth notes |
| `install.sh` | Fresh Ubuntu installer that clones/builds/provisions NexAI |
| `install-sol.sh` | Bundle-local bootstrap installer for the `nexai` launcher |
| `start-sol.ps1` | Windows PowerShell helper |
| `RELEASE.md` | Release packaging instructions |
| `scripts/package_release.py` | Deterministic release archive builder |
| `LICENSE` | Apache-2.0 license |

## `SolVersion2`

`SolVersion2` is the Python package that contains the core runtime and CLI.

| Path | Purpose |
| --- | --- |
| `SolVersion2/pyproject.toml` | Python package metadata; exposes `nexai` and `sol` console scripts |
| `SolVersion2/config/sol.toml` | Default runtime configuration |
| `SolVersion2/sol/cli/` | CLI parser and command implementations |
| `SolVersion2/sol/core/` | Agent, LLM, policy, memory, audit, orchestration, context, unsafe-mode logic |
| `SolVersion2/sol/tools/` | Built-in tools such as filesystem, web, RAG, repo, exec, selfcheck |
| `SolVersion2/sol/install/` | Setup wizard, install model, runtime provisioning, service lifecycle helpers |
| `SolVersion2/sol/runtime/` | Runtime service construction and path management |
| `SolVersion2/sol/plugins/` | Plugin discovery, validation, enable/disable state, tool registration |
| `SolVersion2/sol/skills/` | `SKILL.md` import/discovery logic |
| `SolVersion2/sol/jobs/` | Supervised autonomous job runner and storage |
| `SolVersion2/tests/` | Python tests for install, CLI, runtime, jobs, health, plugins, LLM, and packaging |

## `apps/api`

`apps/api` is the FastAPI service used by the web UI and CLI runtime bridge.

| Path | Purpose |
| --- | --- |
| `apps/api/sol_api/app.py` | FastAPI app factory and router registration |
| `apps/api/sol_api/config.py` | Environment-driven API configuration |
| `apps/api/sol_api/auth.py` | Optional bearer-token auth session store |
| `apps/api/sol_api/solv2_bridge.py` | Bridge from API requests into `SolVersion2` runtime services |
| `apps/api/sol_api/routes/` | HTTP endpoint modules |
| `apps/api/sol_api/rag/` | API-side SQLite RAG store and chunking |
| `apps/api/sol_api/fs_access/` | API-side filesystem policy and operations |
| `apps/api/sol_api/web_access/` | API-side web policy, search, fetch, and errors |
| `apps/api/tests/` | API tests |

## `SolWeb`

`SolWeb` is the browser UI.

| Path | Purpose |
| --- | --- |
| `SolWeb/package.json` | Vite/React scripts and dependencies |
| `SolWeb/public/solweb.config.js` | Runtime API base URL without rebuilding |
| `SolWeb/src/api/client.ts` | Typed API client |
| `SolWeb/src/ui/App.tsx` | Main React application |
| `SolWeb/src/ui/pages/` | Settings and customization pages |
| `SolWeb/src/ui/components/` | Chat, inspector, panels, code canvas, message rendering |

## `apps/desktop`

`apps/desktop` is the Tauri desktop client.

| Path | Purpose |
| --- | --- |
| `apps/desktop/package.json` | Vite, React, and Tauri commands |
| `apps/desktop/src-tauri/tauri.conf.json` | Tauri app config |
| `apps/desktop/src-tauri/src/main.rs` | Rust desktop entry point |
| `apps/desktop/src/` | Desktop React UI and API client |
