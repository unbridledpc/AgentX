# AgentX

**AgentX** is a local-first AI assistant, coding workbench, validation system, and homelab automation platform.

It is built for private VM/LAN deployment and is designed around a practical goal:

> Give a local AI assistant real project awareness, workspace tools, validation checks, model routing, and safe patch workflows — without depending on cloud infrastructure.

AgentX combines a FastAPI backend, React/Vite frontend, Ollama-powered local models, workspace/archive analysis, validation tooling, project memory, GitHub tracking, and a growing workbench for coding and repair workflows.

---

## Current Release

**Latest release:** `v0.2.8-v10`

**Release name:** AgentX V10 — Health Dashboard and Smoke-Test Release

V10 adds a full runtime health system, frontend Health dashboard, V10 release metadata sync, local runtime memory ignore rules, and an end-to-end smoke-test script.

Previous stable baseline:

```text
v0.2.7-v9 — Workbench stabilization and validation baseline
What AgentX Does

AgentX is being built as a local AI control center for:

Chat with local or configured AI models
Code generation and review
Project-aware workspace analysis
ZIP/archive import and inspection
Validation runs against workspaces
Patch preview and repair workflows
Local project memory
Model and Ollama endpoint management
Runtime/system health visibility
GitHub-tracked patch/release workflows
Homelab-friendly AI automation
Project Structure
AgentX/
├── AgentX/                         # Core Python AgentX package/project files
│   └── agentx/                     # Main lowercase Python package
│       ├── cli/                    # CLI entrypoints
│       ├── core/                   # Core assistant/runtime logic
│       ├── install/                # Install/bootstrap helpers
│       ├── jobs/                   # Job planning/running helpers
│       ├── learning/               # Learning/hint helpers
│       ├── plugins/                # Plugin system
│       ├── runtime/                # Runtime bootstrap/services
│       ├── skills/                 # Skill support
│       ├── tools/                  # Tool support
│       └── workbench/              # Archive/workspace analysis tools
│
├── AgentXWeb/                      # React/Vite frontend
│   ├── public/                     # Static runtime config and workspace page
│   └── src/
│       ├── api/                    # API client
│       ├── config.ts               # Frontend config/runtime metadata
│       └── ui/                     # Main UI
│
├── apps/
│   └── api/
│       ├── agentx_api/             # FastAPI backend
│       │   ├── routes/             # API routes
│       │   ├── data/               # Runtime API data
│       │   ├── runtime_guard.py    # Runtime guardrails
│       │   └── validation_runner.py
│       └── tests/                  # Backend tests
│
├── scripts/                        # Install, repair, smoke-test scripts
├── readme/                         # Supplemental/patch-specific README archive
├── CHANGELOG.md                    # Release notes
└── README.md                       # Main project overview
Main Components
AgentX API

The backend is a FastAPI service located at:

apps/api/agentx_api/

Important route groups include:

/v1/status
/v1/health/full
/v1/chat
/v1/runtime
/v1/model-ops
/v1/workbench
/v1/validation
/v1/qol
/v1/settings
/v1/threads
/v1/projects
/v1/scripts
/v1/rag
/v1/github

The backend owns:

Chat routing
Runtime diagnostics
Model/Ollama status
Workbench/archive analysis
Validation runner
Project/thread/script storage
RAG and memory-related data
Safety/runtime guardrails
API status and health reporting
AgentXWeb

The frontend is a React/Vite app located at:

AgentXWeb/

Main UI areas include:

Command — chat and assistant command surface
Drafts — draft/code workspace actions
Memory — project memory and knowledge
Scripts — saved/generated code artifacts
Models — Ollama/model status and selection
Health — V10 system health dashboard
Validate — validation presets and patch candidate checks
Workspaces — uploaded archives and sandbox workspaces
GitHub — repository/update controls
Settings — assistant and UI configuration
AgentX Core Package

The active Python package is:

AgentX/agentx/

Important note:

AgentX/AgentX/

was an old/stale uppercase duplicate tree and should not be recreated. The canonical package is lowercase:

agentx
Local VM Deployment

Current homelab deployment defaults:

VM IP:    192.168.68.210
Web UI:   http://192.168.68.210:5173
API docs: http://192.168.68.210:8000/docs
Health:   http://192.168.68.210:8000/v1/health/full

Systemd services:

agentx-api.service
agentx-web.service

Check services:

sudo systemctl status agentx-api.service --no-pager
sudo systemctl status agentx-web.service --no-pager

Restart services:

sudo systemctl restart agentx-api.service agentx-web.service

View logs:

journalctl -u agentx-api.service -n 100 --no-pager
journalctl -u agentx-web.service -n 100 --no-pager
Ollama Model Routing

AgentX is designed to work with local Ollama endpoints.

Current homelab model routing convention:

Default/Fast endpoint: http://192.168.68.50:11434
Heavy endpoint:        http://192.168.68.50:11435

The V10 Health dashboard reports:

Default Ollama reachability
Fast Ollama reachability
Heavy Ollama configuration/reachability
Host
Port
Latency
Endpoint errors
V10 Health Dashboard

V10 adds a full system health endpoint:

GET /v1/health/full

Example:

curl -s http://127.0.0.1:8000/v1/health/full | python3 -m json.tool

The Health dashboard displays:

AgentX version
API service status
API host/port
Auth status
Rate-limit status
Git branch
Git commit
Python version
Ollama endpoint status
Workspace path status
Thread/project/script directory status
Validation availability
Warnings
Errors

The frontend Health page is available from the AgentXWeb mode rail.

Validation and Smoke Testing

V10 includes a full smoke-test script:

./scripts/smoke-test-v10.sh

The smoke test checks:

API root
/v1/status
/v1/health/full
Web UI response
Python compileall
Frontend typecheck
Frontend tests
Frontend production build

Expected successful ending:

AgentX V10 smoke test passed.
Frontend Development

Install dependencies:

cd AgentXWeb
npm install

Typecheck:

npm run typecheck

Run tests:

npm test

Build production bundle:

npm run build

Run development server:

npm run dev -- --host 0.0.0.0 --port 5173

Current frontend package version:

agentx-web@0.2.8-v10
Backend Development

Syntax validation:

python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests

Run API manually when needed:

cd ~/projects/AgentX
source .venv/bin/activate
uvicorn agentx_api.app:create_app --factory --host 0.0.0.0 --port 8000

Backend tests require pytest. If missing:

python3 -m pip install pytest

Then:

python3 -m pytest apps/api/tests -q

Future work should add a proper backend dev dependency file.

Workbench and Archive Analysis

AgentX includes a workbench analyzer under:

AgentX/agentx/workbench/

Key files:

analyzer.py
archive_workspace.py
playground.py

The analyzer can:

Import ZIP/archive projects
Safely extract files
Build file inventories
Detect file types
Skip noisy folders such as .git, node_modules, venv, dist, and build
Scan Python/JSON/XML syntax
Detect possible risky code patterns
Detect stubs, TODOs, and converted-code markers
Generate JSON reports
Generate Markdown analysis reports

This is the foundation for AgentX’s project repair and validation workflows.

Validation System

AgentX V9/V10 includes validation tooling for workspaces and patch candidates.

Backend pieces:

apps/api/agentx_api/routes/validation.py
apps/api/agentx_api/validation_runner.py
apps/api/agentx_api/runtime_guard.py

Frontend page:

AgentXWeb/src/ui/pages/ValidationPage.tsx

The validation system supports:

Workspace selection
Validation presets
Validation run history
Patch candidate validation
Repair packet generation
Result summaries
Copyable validation output
Runtime Guardrails

AgentX includes runtime guardrail infrastructure to reduce unsafe operations.

Guardrail-related files include:

apps/api/agentx_api/runtime_guard.py
apps/api/tests/test_runtime_guardrails.py

The runtime guardrail direction is:

Keep powerful operations explicit
Track request context
Add rate-limiting support
Avoid silent destructive actions
Make patch/validation workflows auditable
Documentation Layout

The root README.md is reserved for the main AgentX project overview.

Patch-specific and feature-specific README files belong in:

readme/

Examples:

readme/README-V9.md
readme/README_AGENTX_QOL_WORKSPACES.md
readme/README_AUTO_PATCH_PREVIEW_BRIDGE.md
readme/README_FRONTEND_ARCHIVE_WORKBENCH.md
readme/README_WORKSPACE_VALIDATION.md
readme/README_OLLAMA_FIX.md
Git Workflow

AgentX uses GitHub as the source of truth for patches and releases.

Current repository:

https://github.com/unbridledpc/AgentX

Recommended workflow:

git checkout main
git pull origin main
git checkout -b feature/my-feature

After changes:

git status --short
./scripts/smoke-test-v10.sh
git add <files>
git commit -m "Describe the change"
git push -u origin feature/my-feature

Merge back to main when validated:

git checkout main
git pull origin main
git merge --no-ff feature/my-feature -m "Merge my feature"
git push origin main
Release Tags

Current important tags:

v0.2.7-v9
v0.2.8-v10

Create a release tag:

git tag -a v0.2.8-v10 -m "AgentX V10 health dashboard and smoke-test release"
git push origin v0.2.8-v10
Release History
v0.2.8-v10 — Health Dashboard and Smoke-Test Release

Added:

/v1/health/full
Frontend Health dashboard
Runtime health display
Ollama endpoint checks
Workspace writability checks
Validation availability display
V10 release metadata sync
.env.example
Runtime memory ignore rules
scripts/smoke-test-v10.sh

Validated:

API root
API status
Full health endpoint
Web UI
Python compileall
Frontend typecheck
Frontend tests
Frontend production build
v0.2.7-v9 — Workbench Stabilization and Validation Baseline

Added/stabilized:

AgentXWeb typecheck/build gate
Workbench/archive analyzer backend
Runtime/model/QoL/validation/workbench API routes
Runtime guardrails
Validation runner
Frontend workspace/validation UI
Docs and installer scripts
.gitignore cleanup
Clean GitHub-tracked V9 baseline
Known Non-Blocking Warning

Frontend production builds may show:

Some chunks are larger than 500 kB after minification.

This is currently non-blocking. A future release should add code-splitting or route-level dynamic imports.

Security Notes

AgentX is designed for private/local use.

Current common homelab warnings:

Authentication may be disabled.
Web access may be enabled broadly.
Local filesystem/workspace tools can be powerful.
AgentX should be kept behind a trusted LAN/firewall unless hardened.

Before exposing outside the LAN:

Enable authentication
Restrict CORS
Restrict web access allowlists
Restrict filesystem roots
Enable rate limiting
Review environment variables and service configs
Roadmap

Recommended next priorities:

V11 — CI and Backend Test Cleanup
Add GitHub Actions for frontend typecheck/tests/build
Add backend compile/test job
Add backend dev dependency file
Make pytest runnable out of the box
Add health endpoint tests
Add validation route tests
V12 — Workbench UX Polish
Better upload progress
Better validation result views
Better patch candidate summaries
Downloadable reports
Cleaner workspace file tree
Safer patch apply UX
V13 — Model Routing and Runtime Intelligence
Heavy/fast model route selection UI
Endpoint profiles
Model benchmark/status cache
GPU-aware routing
Better Ollama model refresh controls
V14 — Assistant Coding Workbench
Browser-based coding playground improvements
Code canvas persistence
Patch preview improvements
Repo-aware repair flows
GitHub PR/branch helpers
Quick Commands

Check repo:

git status --short
git branch --show-current
git log --oneline -5

Run full smoke test:

./scripts/smoke-test-v10.sh

Restart services:

sudo systemctl restart agentx-api.service agentx-web.service

Check services:

sudo systemctl status agentx-api.service agentx-web.service --no-pager

Open app:

http://192.168.68.210:5173

Open API docs:

http://192.168.68.210:8000/docs

Open health endpoint:

http://192.168.68.210:8000/v1/health/full
Project Status

AgentX is actively evolving.

V9 turned the project into a clean, tracked baseline.

V10 added live system visibility and a full smoke-test gate.
