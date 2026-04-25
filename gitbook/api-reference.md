# API Reference

The backend is a FastAPI application created by `apps/api/sol_api/app.py`.

Default base URL:

```text
http://127.0.0.1:8420
```

All application routes are mounted under `/v1`.

## Auth Behavior

Fresh local installs default to auth disabled.

When auth is disabled, protected endpoints receive a synthetic local identity:

```text
user_id=local
session_id=local
```

When auth is enabled, protected routes require:

```text
Authorization: Bearer <token>
```

## Status

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Root health hint |
| `GET` | `/v1/status` | API status, auth state, model status, provider readiness |
| `GET` | `/v1/status?refresh=1` | Force background model list refresh |

## Auth

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/auth/login` | Login with username/password when auth is enabled |
| `GET` | `/v1/auth/me` | Return current auth identity |
| `POST` | `/v1/auth/logout` | Revoke current bearer session |

Login body:

```json
{
  "username": "nexus",
  "password": "password"
}
```

## Chat

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/chat` | Send a chat message |

Request:

```json
{
  "message": "Summarize this project",
  "thread_id": "optional-thread-id",
  "response_mode": "chat",
  "unsafe_enabled": false,
  "active_artifact": {
    "source": "canvas",
    "type": "code",
    "language": "python",
    "content": "print('hello')",
    "dirty": true
  }
}
```

Response includes assistant content plus optional retrieved chunks, audit tail, sources, verification metadata, and web-search metadata.

## Settings

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/settings` | Read UI/provider settings |
| `POST` | `/v1/settings` | Save UI/provider settings |

Settings include provider, model, Ollama URL, request timeout, display names, theme, appearance preset, density, and layout.

## Threads

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/threads` | List current user's threads |
| `POST` | `/v1/threads` | Create a thread |
| `GET` | `/v1/threads/{thread_id}` | Read a thread |
| `POST` | `/v1/threads/{thread_id}/messages` | Append a message |
| `POST` | `/v1/threads/{thread_id}/title` | Rename a thread |
| `DELETE` | `/v1/threads/{thread_id}` | Delete a thread |

Threads are owner-isolated by hashing the authenticated user ID into a per-user thread directory.

## RAG

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/rag/status` | RAG enabled state and counts |
| `POST` | `/v1/rag/doc` | Upsert a text document |
| `POST` | `/v1/rag/gather` | Gather text files under an allowed root |
| `POST` | `/v1/rag/query` | Query indexed chunks |

`/v1/rag/gather` only accepts paths under `SOL_RAG_ALLOWED_ROOTS`, defaulting to the API data directory.

## Filesystem

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/fs/status` | File access policy status |
| `POST` | `/v1/fs/read_text` | Read a text file |
| `POST` | `/v1/fs/write_text` | Write text, with overwrite blocked unless unsafe mode is enabled |
| `POST` | `/v1/fs/list_dir` | List a directory |
| `POST` | `/v1/fs/apply_patch` | Apply a unified diff, unsafe-mode gated |
| `POST` | `/v1/fs/mkdir` | Create a directory |
| `POST` | `/v1/fs/delete` | Delete a path, unsafe-mode gated |
| `POST` | `/v1/fs/move` | Move a path, unsafe-mode gated when destructive |

Filesystem access is disabled by default at the API layer.

## SolVersion2 Bridge

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/capabilities` | Runtime policy and memory capability summary |
| `GET` | `/v1/audit?limit=50` | Tail audit log |
| `GET` | `/v1/memory/stats?reason=...` | Audited memory stats |
| `POST` | `/v1/memory/prune` | Audited memory prune |
| `GET` | `/v1/memory/ingest/manifests` | List ingest manifests |
| `GET` | `/v1/memory/ingest/manifests/{manifest_id}` | Read an ingest manifest |
| `GET` | `/v1/tools/schema` | List tool schemas |
| `POST` | `/v1/tool` | Run a tool through the agent loop |
| `GET` | `/v1/runtime/state` | Current runtime/working-memory snapshot |

## Web Policy

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/web/policy` | Read global and session web policy |
| `POST` | `/v1/web/policy/update` | Update managed web policy |
| `POST` | `/v1/web/policy` | Alias for policy update |
| `POST` | `/v1/web/policy/session_allow` | Allow one domain for one thread/session |
| `POST` | `/v1/web/policy/session` | Allow multiple domains for one thread/session |
| `POST` | `/v1/web/policy/session_clear` | Clear session web allowlist |

Policy updates require a reason and append audit events.

## Unsafe Mode

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/agent/unsafe/{thread_id}` | Read unsafe state |
| `POST` | `/v1/agent/unsafe/{thread_id}/enable` | Enable unsafe mode with a reason |
| `POST` | `/v1/agent/unsafe/{thread_id}/disable` | Disable unsafe mode |

Unsafe mode is thread-scoped and intended for explicit user-authorized destructive operations.
