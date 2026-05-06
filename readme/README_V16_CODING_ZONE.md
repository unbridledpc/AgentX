# AgentX V16 - Coding Zone

V16 introduces a dedicated Coding Zone separate from Workspaces.

Workspaces are for uploaded archives and existing sandbox projects. Coding Zone is for scratch coding sessions where the user can create files, edit code, run it in a controlled session directory, inspect stdout/stderr, and ask AgentX for help.

## V16.1 Backend

Adds Coding Zone language, session, file, run, and run-history endpoints under `/v1/coding-zone`.

Session data lives under `apps/api/agentx_api/data/coding_zone/sessions/`.

The first runner supports Python, JavaScript, TypeScript, Shell, Lua, C, C++, Go, Rust, and Java when their local runtimes are installed. HTML and text are preview-only for now.

## Safety Notes

- Files are scoped under a Coding Zone session directory.
- Absolute paths and path traversal are rejected.
- Runner environment is minimal.
- Runtime timeout is limited to 1-30 seconds.
- stdout/stderr are truncated to keep responses bounded.
- This is not a VM-level sandbox yet. Treat it as a controlled local runner, not a hostile-code jail.

## Validation

```bash
python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests
./scripts/smoke-test-v10.sh
curl -s http://127.0.0.1:8000/v1/coding-zone/languages | python3 -m json.tool
```

## V16.2 Coding Zone UI

Adds a dedicated Coding Zone page to AgentXWeb.

Features:

- Coding mode in the command deck rail
- create/open/delete coding sessions
- create/open/delete files inside a session
- language selector
- scratch code editor
- stdin field
- run current file through the V16 backend
- stdout/stderr output panel
- run history
- Ask AgentX actions for explain, fix, and review

The UI uses the `/v1/coding-zone/*` backend added in V16.1.
