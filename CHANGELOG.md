# Changelog

## 0.2.1 - 2026-04-29

- Added a fixed bottom-right AgentX version badge so deployed UI builds are easy to verify.
- Updated bundled web config to show `v0.2.1-rag-ui`.

## Unreleased

- Added local RAG usage metadata to chat responses and persisted assistant messages.
- Added a visible RAG badge and expandable local source list on assistant messages that used local knowledge.
- Added a composer + menu for file attachments, picture attachments, file-search prompt insertion, and per-message RAG mode hints.

## Unreleased

### Added
- Knowledge Manager UI for local RAG ingestion and search.
- URL ingestion endpoint: `POST /v1/rag/url`.
- Local folder ingestion endpoint: `POST /v1/rag/folder`.
- Knowledge source listing endpoint: `GET /v1/rag/sources`.
- Knowledge source deletion endpoint: `DELETE /v1/rag/sources/{doc_id}`.
- RAG source metadata for `collection`, `tags`, source kind, source URL/path, content type, and ingest timestamps.
- Search UI that queries the same local RAG store used by chat retrieval.
- Documentation for using Knowledge Ingest with URLs, AgentX source, and game/project folders.

### Changed
- README reorganized around install, runtime surfaces, model workflow, memory/RAG, Knowledge Manager, and development.
- RAG folder ingestion supports more project/code extensions by default, including `.ps1`, `.lua`, `.xml`, `.ts`, `.tsx`, `.js`, and `.toml`.
- Manual RAG documents now receive a default `Manual` collection when no collection metadata is supplied.

### Notes
- URL ingestion uses AgentX web policy. Set `AGENTX_WEB_ENABLED=true` and allow the target host when ingesting web pages.
- Folder ingestion remains restricted by `AGENTX_RAG_ALLOWED_ROOTS`.
- This is RAG ingestion, not model retraining. It gives local models retrieved context from indexed sources.

### Added
- AgentX Nova UI refresh with softer panels, modern chat styling, improved composer polish, and a less Codex-like visual treatment.
- GitHub update ticker in the web UI that checks the configured GitHub repository and highlights when a newer commit is available.
- Runtime update feed config via `window.__AGENTXWEB_CONFIG__.updateFeed` and Vite env vars.

### Changed
- Web UI now supports a modern update/status strip below the top bar for release awareness.

## Multi-Ollama endpoint routing

- Added multi-Ollama endpoint settings for fast/heavy local model routing.
- Draft + Review can now route draft requests to a fast endpoint and review/repair requests to a heavy endpoint.
- Added endpoint metadata to status responses, including configured base URLs and GPU pin labels.
- Added Settings UI controls for fast/heavy endpoint URLs, preferred models, route selection, and GPU pin notes.
