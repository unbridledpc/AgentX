# AgentX / NexAI

AgentX is a local-first, supervised AI assistant platform for user-controlled infrastructure. It combines a Python agent runtime, FastAPI backend, React/Vite web UI, Ollama model support, RAG/long-term memory, scripts/projects libraries, collaborative coding workflows, and policy-aware tool execution.

> You are responsible for how you install, configure, and run AgentX. It executes on your hardware and may use local or third-party models/tools that are outside the author’s control. Keep risky actions supervised, review generated code, and use Git history for every change.

## What AgentX is built for

- Running local models through Ollama.
- Organizing chats, projects, saved scripts, and code artifacts.
- Using short-term and long-term memory with local RAG retrieval.
- Ingesting URLs and local project folders into searchable knowledge.
- Drafting and reviewing code with multi-model coding pipelines.
- Applying deterministic quality gates to catch common coding failures.
- Keeping filesystem, web, memory, and unsafe actions explicit and auditable.
- Building a supervised local agent that can learn project context without silently rewriting itself.

## Major features

### Chat and model control

- Local-first chat UI.
- Ollama model discovery and model selection.
- Per-thread model selection.
- Streaming chat responses.
- Stop/continue/retry controls.
- Response timing metrics, including total response time and first-token time.

### Projects and scripts

- Project records for grouping chats and work.
- Scripts library for saved generated code.
- Copy/export/insert saved scripts back into chat.
- Code canvas for editing and working with generated scripts.

### Model Behavior Contract

Settings include global model behavior controls:

- Global model instructions.
- Coding output contract.
- Collaborative reviewer contract.
- Fenced-code preference.
- Standard-library preference.
- Windows-aware examples.
- Quality gate auto-repair.
- Visible quality gate reports.

### Collaborative coding pipeline

AgentX can run coding requests through a two-model flow:

```text
Draft model -> Reviewer model -> Quality Gate -> Repair pass if needed
```

Typical local routing:

```text
qwen2.5-coder:7b-4k-gpu -> devstral-small-2:24b-4k-gpu
```

The reviewer/finalizer is guided by the Collaborative Reviewer Contract, and the quality gate checks recurring issues such as:

- fake dependencies
- missing `argparse` / `param()`
- missing `--dry-run` for file-moving scripts
- monitor requests downgraded to one-time scans
- unsafe destination behavior
- bad PowerShell hash/report patterns
- bad Python `os.scandir()` / `Path` API usage
- unrequested third-party watcher dependencies
- overclaiming “production-ready”

### Knowledge Ingest Manager

The Knowledge page adds a UI for local RAG ingestion and search.

Use it for:

- Wikipedia/docs URLs, such as Lua documentation.
- AgentX source code.
- game server files.
- OTClient files.
- Lua/XML/JSON/YAML/TOML configs.
- Markdown notes and project docs.

Supported actions:

- Ingest URL into RAG.
- Ingest local folder into RAG.
- Add collection and tags.
- List indexed sources.
- Delete indexed sources.
- Search the RAG store directly.

Important: this does **not** retrain the model. It indexes text into a local searchable store so chat can retrieve relevant chunks as context.

### Memory and RAG

AgentX includes local retrieval support:

- SQLite/FTS-backed RAG store.
- Thread retrieval context.
- Manual document upsert.
- Folder gather/ingest.
- URL ingest with web policy controls.
- Source metadata with collection/tags.

### Web and filesystem controls

AgentX has explicit runtime flags for web and filesystem access. Keep these locked down unless you need them.

Common flags:

```env
AGENTX_RAG_ENABLED=true
AGENTX_RAG_ALLOWED_ROOTS=F:\Sol Folder;F:\YourGameFolder
AGENTX_WEB_ENABLED=true
AGENTX_WEB_ALLOWED_HOSTS=wikipedia.org
AGENTX_FS_ENABLED=false
AGENTX_FS_WRITE_ENABLED=false
AGENTX_FS_DELETE_ENABLED=false
```

On Linux/WSL:

```env
AGENTX_RAG_ALLOWED_ROOTS=/home/user/NexAI;/home/user/game-server
```

## Repository layout

```text
AgentX/                    Core Python runtime, CLI, tests, config, agent logic
apps/api/                  FastAPI backend used by AgentXWeb
apps/api/agentx_api/rag/    SQLite/FTS RAG store and chunking code
apps/api/agentx_api/routes/ API routes for chat, settings, RAG, projects, scripts, etc.
AgentXWeb/                 React/Vite web UI
AgentXWeb/src/api/          Frontend API client/types
AgentXWeb/src/ui/           Main web UI shell and components
AgentXWeb/src/ui/pages/     Settings, customization, and Knowledge pages
apps/desktop/               Desktop/Tauri client work
gitbook/                   Longer documentation
scripts/                   Release and maintenance scripts
install.sh                 Linux/WSL installer
install-agentx.sh           Repo-local installer
start-agentx.ps1            PowerShell launcher helper
CHANGELOG.md                Human-readable change history
```

## Important new files

```text
AgentXWeb/src/ui/pages/KnowledgePage.tsx
```

Knowledge Manager UI for URL/folder ingestion, source listing, deletion, and RAG search.

```text
apps/api/agentx_api/routes/rag.py
```

RAG API routes for status, manual docs, folder ingest, URL ingest, source listing/deletion, and query.

```text
apps/api/agentx_api/rag/store.py
```

SQLite/FTS document and chunk store, including source listing and deletion helpers.

```text
gitbook/knowledge-ingest.md
```

Detailed usage guide for Knowledge Ingest.

```text
CHANGELOG.md
```

New feature/change history.

## Quick install on Ubuntu / WSL

Fresh Ubuntu 24 installs can start with:

```bash
curl -fsSL https://raw.githubusercontent.com/VielNexus/NexAI/main/install.sh | bash
```

After install:

```bash
agentx start
agentx status
```

Open:

```text
http://127.0.0.1:5173
```

Lifecycle commands:

```bash
agentx start
agentx stop
agentx restart
agentx status
agentx uninstall
```

Repo-local install from a checkout:

```bash
./install-agentx.sh
```

## Development setup

Recommended tools:

- Python 3.11+
- Node.js 20.19+ or Node.js 22.12+
- npm
- Git
- Ollama for local model testing
- Rust/Cargo if working on desktop/Tauri pieces

Python runtime:

```bash
cd AgentX
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[developer]"
```

PowerShell:

```powershell
cd AgentX
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[developer]"
```

Run tests:

```bash
python -m pytest AgentX/tests apps/api/tests
```

Run API directly:

```bash
cd apps/api
python -m pip install -r requirements.txt
PYTHONPATH="../../AgentX:." python -m agentx_api --host 127.0.0.1 --port 8420
```

Web UI:

```bash
cd AgentXWeb
npm ci
npm run typecheck
npm run test
npm run build
```

## Using Knowledge Ingest

### Ingest a URL

1. Open `Menu -> Knowledge`.
2. Paste a URL, for example:

```text
https://en.wikipedia.org/wiki/Lua
```

3. Pick a collection, for example:

```text
Programming Languages
```

4. Add tags:

```text
lua, scripting, gamedev
```

5. Click **Ingest URL**.

URL ingest requires web access to be enabled and the host to be allowed:

```env
AGENTX_WEB_ENABLED=true
AGENTX_WEB_ALLOWED_HOSTS=wikipedia.org
```

### Ingest game or project files

1. Set allowed roots:

```env
AGENTX_RAG_ALLOWED_ROOTS=F:\Sol Folder;F:\YourGameFolder
```

2. Open `Menu -> Knowledge`.
3. Enter the folder path.
4. Set collection, for example:

```text
Game Server
AgentX Self Knowledge
OTClient
```

5. Keep or edit extensions.
6. Click **Ingest Folder**.

### Search knowledge

Use the Knowledge page search box to test what AgentX can retrieve.

In chat, ask questions like:

```text
Using my ingested Lua docs, explain Lua tables.
```

```text
Using my Game Server knowledge, where is monster behavior configured?
```

```text
Using AgentX Self Knowledge, where is the quality gate implemented?
```

## Recommended self-learning workflow

AgentX should not silently mutate itself. Use supervised evolution:

```text
Ingest AgentX source
Ask questions / identify improvements
Generate patch with Draft + Review
Run quality gate and tests
Review files
Commit and push to GitHub
Pull on WSL/runtime host
```

This keeps the system smarter over time while preserving human approval and Git history.

## Clean source repository guide

Commit source and docs only:

- Python/TypeScript/Rust source
- tests
- manifests/lockfiles
- install scripts
- docs and examples

Do not commit:

- `node_modules/`, `dist/`, `build/`, Rust `target/`
- Python caches, virtual environments, egg-info
- runtime `data/`, `threads/`, logs, audit logs, SQLite databases, uploaded files
- `.env` files, tokens, private keys, certificates, credentials

## Platform support

- Current focus: Linux and WSL.
- Windows-native support is planned but not the primary service/install target yet.
- PowerShell helper scripts are included for Windows-side workflows.

## Status

AgentX is under active development. The current direction is production-minded and supervised, but the platform is still evolving in install flow, extension lifecycle, quality gates, RAG knowledge, and autonomous job execution.
