# Phase 3: Workbench + ZIP Analyzer

Private experimental feature, not public-release ready.

AgentX can now import a full project/server ZIP into a sandbox, safe-extract it, inventory files, scan supported source/config files, and write a read-only analysis report before any coder model proposes changes.

## Safety

Allowed: copy ZIP, extract to sandbox, inventory files, scan text/source/config files, write JSON reports and `final_report.md`.

Blocked in v0.1: editing files, touching live folders, running server code, executing binaries, installing dependencies, connecting to databases, applying patches, committing, or pushing.

## CLI

```bash
agentx workbench import-zip /path/to/Server.zip --workspace work/workbench --name server-private-test
```

JSON:

```bash
agentx workbench import-zip /path/to/Server.zip --workspace work/workbench --name server-private-test --json
```

## API

```text
POST /v1/workbench/import-zip
GET  /v1/workbench/report?path=<final_report.md>
```

## Web

```text
AgentXWeb/dist/playground.html
```

## Server/TFS conversion checks

The analyzer flags `Auto-generated from`, `TODO: Implement logic converted from TFS script`, `TODO: Map TFS API call`, `from devnexus import api as dn`, `NotImplementedError`, and stub/pass-only files.
