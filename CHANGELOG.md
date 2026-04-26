# Changelog

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
