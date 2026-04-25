# Running NexAI

## Normal Lifecycle

Use the installed launcher:

```bash
nexai start
nexai status
nexai stop
nexai restart
```

Useful diagnostics:

```bash
nexai doctor
nexai doctor --fix
nexai health
nexai paths
nexai runtime inspect
```

Read logs:

```bash
nexai logs api --tail 100
nexai logs web --tail 100
```

Uninstall:

```bash
nexai uninstall
```

Keep the checked-out app bundle during uninstall:

```bash
nexai uninstall --keep-app-root
```

## Opening The UI

After `nexai start`, open:

```text
http://127.0.0.1:5173
```

The web UI talks to the API at:

```text
http://127.0.0.1:8420
```

The API base is controlled by `SolWeb/public/solweb.config.js` for static web builds.

## Chat Providers

NexAI supports these provider paths:

| Provider | Behavior |
| --- | --- |
| `stub` | Local echo-style fallback, no real model |
| `ollama` | Local model generation through Ollama |
| `openai` | OpenAI-compatible chat completions using `SOL_OPENAI_API_KEY` |

Ollama is the intended default for local-first installs. Make sure the model exists:

```bash
ollama list
ollama pull llama3.2
```

Then select the model in SolWeb settings or use the generated runtime config.

## CLI Chat

Send a single task:

```bash
nexai run "Summarize what this system can do."
```

Read task content from a file:

```bash
nexai run --file prompt.txt
```

Pipe input:

```bash
cat prompt.txt | nexai run
```

Start interactive mode:

```bash
nexai run
```

In interactive mode:

```text
/quit
```

## Important Runtime Separation

NexAI separates immutable application files from mutable runtime state:

| Category | Meaning |
| --- | --- |
| App root | Checked-out or installed application bundle |
| Runtime root | Managed virtualenv, config, data, logs, cache, plugins, skills, jobs |
| Working directory | Directory exposed as the user's workspace for tool operations |

This separation is central to upgrades, uninstall behavior, auditability, and release packaging.
