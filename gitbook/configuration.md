# Configuration

NexAI has two major config layers:

- API config from environment variables in `apps/api/sol_api/config.py`.
- Runtime config from TOML in `SolVersion2/config/sol.toml` or the generated install runtime config.

## Runtime TOML

Default repo config:

```text
SolVersion2/config/sol.toml
```

Generated installs write a runtime config under the managed runtime root and point the launcher/API at it.

Major sections:

| Section | Purpose |
| --- | --- |
| `[agent]` | Agent mode, max steps, auto-tool behavior |
| `[audit]` | JSONL audit log path |
| `[memory]` | SQLite FTS memory backend and event log |
| `[paths]` | Data, logs, UI project roots |
| `[fs]` | Filesystem allowed roots, denied drives, denied substrings, size limits |
| `[exec]` | Command execution allowlist and timeout |
| `[web]` | Web access defaults |
| `[web.policy]` | Managed fetch/crawl allowlist/denylist |
| `[web.search]` | Search providers and result limits |
| `[rag]` | Retrieval settings |
| `[voice]` | Voice stub settings |
| `[vision]` | Vision stub settings |
| `[llm]` | Provider selection |
| `[llm.openai]` | OpenAI-compatible settings |
| `[llm.ollama]` | Ollama settings |

## Important Runtime Defaults

| Setting | Default Meaning |
| --- | --- |
| `agent.mode = "supervised"` | Human-supervised tool execution |
| `agent.refuse_unattended = true` | Fail closed for unattended mode |
| `fs.allowed_roots = ["D:/", "E:/", "F:/"]` | Repo default allows non-C Windows drives |
| `fs.deny_drive_letters = ["C"]` | Blocks C drive |
| `exec.allowed_commands = ["python", "git", "npm", "node"]` | Command allowlist |
| `web.policy.allow_all_hosts = false` | Fetch/crawl is allowlist-based |
| `llm.provider = "ollama"` | Runtime CLI provider default |
| `llm.ollama.model = "llama3.2"` | Default Ollama model |

## API Environment Variables

Core API:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_API_HOST` | `127.0.0.1` | API bind host |
| `SOL_API_PORT` | `8420` | API port |
| `SOL_API_DATA_DIR` | API package `data` dir | Settings, threads, RAG DB |

Auth:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_AUTH_ENABLED` | `false` | Enable bearer auth |
| `SOL_AUTH_SESSION_TTL_S` | `604800` | Session lifetime, min 300 seconds |
| `SOL_AUTH_USERS_JSON` | unset | JSON map of username to SHA256 digest |
| `SOL_AUTH_USER` | `nexus` | Single default auth user |
| `SOL_AUTH_PASSWORD` | unset | Plain password converted to SHA256 at startup |
| `SOL_AUTH_PASSWORD_SHA256` | legacy digest | Password digest |

OpenAI:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_OPENAI_API_KEY` | unset | Enables OpenAI provider |
| `SOL_OPENAI_MODEL` | `gpt-4o-mini` | Default OpenAI model |
| `SOL_OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI-compatible base URL |
| `SOL_OPENAI_TIMEOUT_S` | `20` | HTTP timeout |
| `SOL_OPENAI_TOOL_MAX_ITERS` | `4` | Tool loop limit |

Ollama:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `SOL_OLLAMA_TIMEOUT_S` | `5` | Model discovery timeout |
| `SOL_OLLAMA_REQUEST_TIMEOUT_S` | `60` | Generation timeout |
| `SOL_OLLAMA_TOOLS_ENABLED` | `false` | Best-effort text-protocol tool use |
| `SOL_OLLAMA_TOOL_MAX_ITERS` | `4` | Ollama tool loop limit |

RAG:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_RAG_ENABLED` | `true` | Enable API RAG |
| `SOL_RAG_TOP_K` | `5` | Query hits |
| `SOL_RAG_CHUNK_CHARS` | `1200` | Chunk size |
| `SOL_RAG_CHUNK_OVERLAP` | `200` | Chunk overlap |
| `SOL_RAG_ALLOWED_ROOTS` | API data dir | Semicolon-separated gather roots |
| `SOL_RAG_INGEST_THREADS` | `true` | Ingest thread context |
| `SOL_RAG_TOOL_MAX_CHARS` | `8000` | Model-driven RAG write limit |

Filesystem API:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_FS_ENABLED` | `false` | Enable `/v1/fs/*` |
| `SOL_FS_ALLOW_ALL` | `false` | Allow all paths |
| `SOL_FS_ALLOWED_ROOTS` | API data dir | Semicolon-separated roots |
| `SOL_FS_WRITE_ENABLED` | `false` | Enable writes |
| `SOL_FS_DELETE_ENABLED` | `false` | Enable deletes |
| `SOL_FS_WRITE_DENY_DRIVES` | `C` | Deny writes on drives |
| `SOL_FS_MAX_READ_BYTES` | `200000` | Read size limit |
| `SOL_FS_MAX_WRITE_BYTES` | `200000` | Write size limit |

Web API:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOL_WEB_ENABLED` | `false` | Enable web tools in API fallback paths |
| `SOL_WEB_ALLOW_ALL` | `false` | Allow all hosts |
| `SOL_WEB_ALLOWED_HOSTS` | `duckduckgo.com;wikipedia.org` equivalent defaults | Host allowlist |
| `SOL_WEB_BLOCK_PRIVATE` | `true` | Block private networks |
| `SOL_WEB_TIMEOUT_S` | `10` | Fetch timeout |
| `SOL_WEB_MAX_BYTES` | `400000` | Fetch size limit |
| `SOL_WEB_USER_AGENT` | `SolWebAccess/0.1` | User agent |
| `SOL_WEB_MAX_REDIRECTS` | `5` | Redirect limit |
| `SOL_WEB_MAX_SEARCH_RESULTS` | `5` | Search result limit |

## SolVersion2 Bridge Environment

| Variable | Purpose |
| --- | --- |
| `SOL_APP_ROOT` | Override app root used by API bridge |
| `SOL_CONFIG_PATH` | Override runtime TOML path used by API bridge |

## Web UI Config

Runtime UI config is served from:

```text
SolWeb/public/solweb.config.js
```

It controls `apiBase` and optional inspector visibility without rebuilding the site.
