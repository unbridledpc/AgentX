# Development Guide

## Prerequisites

Useful local development tools:

- Python 3.11+
- Node.js 20+
- npm
- Git
- Rust toolchain for Tauri desktop work
- Ollama if testing local model generation

## Python Runtime Development

From the repo root:

```bash
cd SolVersion2
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[developer]"
pytest
```

On PowerShell:

```powershell
cd SolVersion2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[developer]"
pytest
```

## API Development

The API imports `sol` through the bridge, so make sure `SolVersion2` is importable or set `SOL_APP_ROOT`.

Example PowerShell session:

```powershell
$env:SOL_APP_ROOT = "F:\Sol Folder"
$env:SOL_AUTH_ENABLED = "false"
cd apps\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:PYTHONPATH = "F:\Sol Folder\SolVersion2;$PWD"
python -m sol_api --host 127.0.0.1 --port 8420
```

Example bash session:

```bash
export SOL_APP_ROOT="$PWD"
export SOL_AUTH_ENABLED=false
cd apps/api
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PYTHONPATH="$(pwd)/../../SolVersion2:$(pwd)"
python -m sol_api --host 127.0.0.1 --port 8420
```

## Web Development

```bash
cd SolWeb
npm install
npm run dev
```

Make sure `SolWeb/public/solweb.config.js` points to the API:

```js
window.__SOLWEB_CONFIG__ = {
  apiBase: "http://127.0.0.1:8420",
  showInspector: undefined
};
```

Tests and checks:

```bash
npm run test
npm run typecheck
npm run build
```

## Desktop Development

```bash
cd apps/desktop
npm install
npm run tauri:dev
```

For production build:

```bash
npm run tauri:build
```

## API Tests

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt pytest
export PYTHONPATH="$(pwd):$(pwd)/../../SolVersion2"
pytest
```

On PowerShell, set:

```powershell
$env:PYTHONPATH = "$PWD;F:\Sol Folder\SolVersion2"
```

## Repository Test Areas

The existing tests cover:

- Bootstrap install lifecycle.
- CLI run behavior.
- Doctor fixes.
- Runtime unification.
- Service management.
- Plugin manager.
- Skill import.
- Job runner.
- Health checks.
- Ollama endpoint behavior.
- API auth and auth isolation.
- Release packaging.
- Frontend chat send, layout persistence, code canvas, customization page.

## Grounded Demo Flows

`SolVersion2/docs/reliability-demos.md` documents practical flows:

- Create, read, edit, and delete a file.
- Inspect the repo to find implementation locations.
- Explain runtime behavior from inspected code.
- Fail safely when context is ambiguous.

These are useful smoke tests for real agent behavior.
