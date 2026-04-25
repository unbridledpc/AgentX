# Security And Safety

## Local-First Assumption

NexAI is designed for local, user-controlled operation. The default API host is `127.0.0.1`, and fresh local installs default to auth disabled. Do not expose the API to a network unless you intentionally enable auth and review every filesystem, web, and execution setting.

## Auth

Auth is controlled by `SOL_AUTH_ENABLED` and install metadata `auth.enabled`.

When disabled:

- Login is not shown by SolWeb.
- Protected endpoints accept a local synthetic identity.
- This is suitable only for local-only operation.

When enabled:

- `/v1/auth/login` issues a bearer token.
- Protected routes require `Authorization: Bearer <token>`.
- Tokens are stored in memory server-side and in browser local storage client-side.
- Sessions expire after `SOL_AUTH_SESSION_TTL_S`.

## Supervised Mode

The runtime default is supervised mode. Unattended mode is refused by default:

```toml
[agent]
mode = "supervised"
refuse_unattended = true
```

This is intentional. The code explicitly treats unattended guardrails as incomplete.

## Audit Logging

Tool calls and sensitive runtime transitions are audited as JSONL events. Many operations check audit log writability before proceeding. If the audit log cannot be written, the agent can fail closed.

Audited actions include:

- Tool start/end.
- LLM calls.
- Memory stats and pruning.
- Job transitions.
- Unsafe-mode blocked and successful destructive actions.
- Web policy updates.

## Filesystem Policy

There are two filesystem layers:

- Runtime tool policy from `SolVersion2/config/sol.toml`.
- API file policy from `SOL_FS_*` environment variables.

The API filesystem endpoints are disabled by default. Writes and deletes need additional flags even after file access is enabled.

Destructive API operations are thread unsafe-mode gated:

- Overwriting an existing file.
- Applying patches.
- Deleting.
- Moving paths destructively.

## Unsafe Mode

Unsafe mode is per-thread. It exists to make destructive operations explicit and auditable.

Enable:

```http
POST /v1/agent/unsafe/{thread_id}/enable
```

Disable:

```http
POST /v1/agent/unsafe/{thread_id}/disable
```

Unsafe mode should be enabled only for a concrete task and disabled afterward.

## Web Policy

Runtime web policy is allowlist-based by default:

```toml
[web.policy]
allow_all_hosts = false
allowed_suffixes = ["edu", "gov", "wikipedia.org"]
allowed_domains = ["api.github.com", "github.com", "google.com", "otland.net", "raw.githubusercontent.com", "usa.gov", "whitehouse.gov"]
denied_domains = []
```

The API exposes endpoints to update policy and to allow domains only for one thread/session. Policy updates require a reason and are audited.

## Private Network Protection

API web fetching defaults to:

```text
SOL_WEB_BLOCK_PRIVATE=true
```

Keep this enabled unless you explicitly need internal-network access and understand the SSRF risk.

## Command Execution

Runtime command execution is controlled by `[exec]`:

- `enabled = true`
- `allow_shell = false`
- commands are allowlisted by basename
- risky script/binary extensions are denied in unattended mode
- timeout defaults to 30 seconds

Treat command execution as high-risk. Keep command allowlists narrow.

## Practical Hardening Checklist

- Keep API binding on `127.0.0.1` for local installs.
- Enable auth before exposing beyond localhost.
- Keep filesystem API disabled unless needed.
- Restrict `SOL_FS_ALLOWED_ROOTS`.
- Keep writes and deletes disabled unless needed.
- Keep C drive or system directories denied.
- Keep web private-network blocking enabled.
- Prefer web allowlists over `allow_all_hosts`.
- Review audit logs after risky sessions.
- Disable unsafe mode after completing destructive work.
