# Troubleshooting

## `nexai` Command Not Found

Cause: `~/.local/bin` is not on `PATH`.

Fix:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then add the same line to `~/.bashrc` or `~/.zshrc` if the installer did not already do it.

## API Is Not Running

Symptoms:

- CLI says `NexAI API is not running. Try: nexai status or nexai start`.
- Web UI cannot load status.

Fix:

```bash
nexai status
nexai start
nexai logs api --tail 100
nexai doctor
```

## Web UI Does Not Connect

Check `SolWeb/public/solweb.config.js`:

```js
window.__SOLWEB_CONFIG__ = {
  apiBase: "http://127.0.0.1:8420"
};
```

Then verify API status:

```bash
curl http://127.0.0.1:8420/v1/status
```

## Ollama Is Unreachable

Symptoms:

- Provider endpoint status is `unreachable`.
- Chat status says the configured Ollama endpoint could not be reached.

Fix:

```bash
ollama serve
ollama list
ollama pull llama3.2
```

Confirm the configured URL:

```text
http://127.0.0.1:11434
```

## Selected Ollama Model Is Missing

Symptoms:

- Provider model status is `missing`.
- Status says the selected model is not available.

Fix:

```bash
ollama pull <model-name>
```

Then refresh SolWeb status or call:

```bash
curl "http://127.0.0.1:8420/v1/status?refresh=1"
```

## OpenAI Provider Fails

If OpenAI is selected, `SOL_OPENAI_API_KEY` must be set:

```bash
export SOL_OPENAI_API_KEY="..."
```

Optional:

```bash
export SOL_OPENAI_MODEL="gpt-4o-mini"
export SOL_OPENAI_BASE_URL="https://api.openai.com"
```

Restart the API after changing environment variables.

## Auth Login Is Not Available

If `/v1/auth/login` returns HTTP 409, auth is disabled. This is the default local install behavior.

Enable auth:

```bash
export SOL_AUTH_ENABLED=true
export SOL_AUTH_USER=nexus
export SOL_AUTH_PASSWORD="choose-a-password"
```

For managed installs, update `auth.enabled` in install metadata and restart NexAI.

## File Access Is Disabled

API filesystem endpoints are disabled by default.

Enable read access:

```bash
export SOL_FS_ENABLED=true
export SOL_FS_ALLOWED_ROOTS="/safe/path"
```

Enable writes only when needed:

```bash
export SOL_FS_WRITE_ENABLED=true
```

Enable deletes only when needed:

```bash
export SOL_FS_DELETE_ENABLED=true
```

Destructive operations still require unsafe mode for the relevant thread.

## Destructive Action Blocked

Symptoms:

```text
Destructive action blocked. Enable UNSAFE mode for this thread.
```

Fix:

- Confirm the target path and operation.
- Enable unsafe mode for that thread with a reason.
- Run the operation.
- Disable unsafe mode afterward.

## RAG Gather Path Rejected

Symptoms:

```text
Path is outside SOL_RAG_ALLOWED_ROOTS.
```

Fix:

```bash
export SOL_RAG_ALLOWED_ROOTS="/path/one;/path/two"
```

Restart the API.

## SolVersion2 Bridge Fails

Symptoms:

- `/v1/capabilities` returns 503.
- Chat returns `SolVersion2 agent error`.

Checks:

```bash
nexai runtime inspect
nexai doctor
```

For direct API development, set:

```bash
export SOL_APP_ROOT="/path/to/repo"
export SOL_CONFIG_PATH="/path/to/repo/SolVersion2/config/sol.toml"
```

Also ensure `SolVersion2` is importable through `PYTHONPATH` or an editable install.

## Release Packaging Fails

Most common cause: `SolWeb/dist/index.html` does not exist.

Fix:

```bash
cd SolWeb
npm install
npm run build
cd ..
python scripts/package_release.py
```
