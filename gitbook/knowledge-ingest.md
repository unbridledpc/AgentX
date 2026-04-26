# Knowledge Ingest Manager

The Knowledge Ingest Manager lets AgentX add URLs and local folders to the local RAG database so future chat responses can use that content as retrieved context.

This does **not** retrain a model. It indexes source material, chunks it, stores it in SQLite FTS, and retrieves relevant chunks when you ask questions.

## Open the page

In AgentXWeb, use:

```text
Menu -> Knowledge
```

The page shows:

- RAG status
- document and chunk counts
- URL ingest form
- local folder ingest form
- source list
- search panel

## Ingest a URL

Example:

```text
https://en.wikipedia.org/wiki/Lua
```

Recommended fields:

```text
Collection: Programming Languages
Tags: lua, scripting, gamedev
```

URL ingest uses AgentX web policy. If a URL is blocked, configure:

```env
AGENTX_WEB_ENABLED=true
AGENTX_WEB_ALLOWED_HOSTS=wikipedia.org
```

or allow a broader host list only on trusted local systems.

## Ingest a local folder

Use folder ingest for game files, AgentX source, Lua/XML scripts, docs, and configs.

Example folders:

```text
F:\Sol Folder
F:\YourGameFolder
/home/user/NexAI
/home/user/game-server
```

Folder ingest is restricted by:

```env
AGENTX_RAG_ALLOWED_ROOTS=F:\Sol Folder;F:\YourGameFolder
```

On Linux/WSL:

```env
AGENTX_RAG_ALLOWED_ROOTS=/home/user/NexAI;/home/user/game-server
```

Default extensions include common source/config/document formats such as:

```text
.py, .ps1, .lua, .xml, .json, .md, .txt, .ts, .tsx, .js, .yaml, .yml, .toml
```

## Search knowledge

Use the search box on the Knowledge page to query indexed sources directly. Chat also uses the same RAG store when retrieval is enabled.

## Collections and tags

Use collections to keep knowledge organized:

```text
AgentX Self Knowledge
Game Server
OTClient
Programming Languages
Lua Docs
```

Use tags for cross-cutting labels:

```text
lua, npc, monster, scripting, api, frontend, backend
```

## Recommended workflow for self-improvement

1. Ingest the current AgentX repo as `AgentX Self Knowledge`.
2. Ask AgentX where a feature lives.
3. Generate a patch with Draft + Review.
4. Run quality gates/tests.
5. Review the patch.
6. Commit and push to GitHub.

Do not allow silent self-modification. Keep changes supervised, reviewable, and tracked in GitHub.
