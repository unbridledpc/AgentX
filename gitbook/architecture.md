# Architecture

## High-Level Flow

```text
User
  -> SolWeb or CLI
  -> FastAPI /v1 routes
  -> SolVersion2 bridge
  -> Agent runtime
  -> Tool registry / LLM / memory / audit
  -> Response back to UI or CLI
```

The preferred runtime path is:

```text
UI -> API -> Agent -> Tools -> Audit -> Memory
```

The API keeps legacy fallback logic for OpenAI/Ollama chat when the SolVersion2 bridge is unavailable, but the main design favors the unified agent path.

## Core Runtime Construction

`SolVersion2/sol/runtime/bootstrap.py` builds a `RuntimeServices` object containing:

- Parsed config.
- `SolContext`.
- `ToolRegistry`.
- `Agent`.
- Runtime paths.
- Plugin manager.
- Skill manager.
- Hint store.
- Job store.

During startup it creates runtime directories for data, logs, config, run state, cache, temp files, audit, memory, working dir, plugins, skills, user plugins, user skills, and feature data.

## Agent Model

The agent in `SolVersion2/sol/core/agent.py` is supervised-only by default.

The core pattern is:

```text
plan -> validate -> execute -> audit -> remember
```

Important behaviors:

- `unattended` mode is refused unless `agent.refuse_unattended=false`, and the default config warns that unattended guardrails are unfinished.
- Tool calls require reasons.
- Audit log writability is checked before sensitive actions.
- Memory can be enabled or replaced by a stub.
- Retrieved untrusted context is explicitly labeled and guarded.
- Per-thread unsafe mode gates destructive actions.

## FastAPI Service

`apps/api/sol_api/app.py` creates the service and mounts routers:

- `status`
- `auth`
- `chat`
- `settings`
- `threads`
- `unsafe`
- `rag`
- `fs`
- `solv2`

The API includes CORS origins for localhost web dev, localhost static hosting, and Tauri origins.

## SolVersion2 Bridge

`apps/api/sol_api/solv2_bridge.py` imports `SolVersion2` dynamically from the app root, initializes runtime services, and exposes handles to routes.

Bridge behavior:

- Uses `SOL_APP_ROOT` if set; otherwise resolves the repo root.
- Uses `SOL_CONFIG_PATH` if set; otherwise uses `SolVersion2/config/sol.toml`.
- Caches one global runtime handle.
- Creates per-request agents for thread/user-specific context.
- Supports per-session web domain allowlists.
- Updates the managed `[web.policy]` block inside the TOML config and reloads the handle.

## State And Persistence

Important state locations:

| State | Location |
| --- | --- |
| API settings | `SOL_API_DATA_DIR/settings.json` or API package data dir |
| API threads | `SOL_API_DATA_DIR/threads` or API package data dir |
| API RAG DB | `SOL_API_DATA_DIR/rag.sqlite3` |
| Runtime audit log | Configured by `[audit].log_path` |
| Runtime memory DB | Configured by `[memory].db_path` |
| Runtime memory events | Configured by `[memory].events_path` |
| Jobs | Runtime `jobs/` directory |
| Plugin state | Runtime `plugins/state.json` |
| Learned hints | Runtime `learning/hints.jsonl` |

## Client Architecture

SolWeb is a thin client:

- It stores auth session data in browser `localStorage`.
- It calls the API through `SolWeb/src/api/client.ts`.
- It does not own providers, tools, or config policy.
- It sends active artifact context for code canvas/file/tool-output-aware chat.

Desktop follows the same broad client model, but through a Tauri app shell.
