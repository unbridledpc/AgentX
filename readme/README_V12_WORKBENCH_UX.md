# AgentX V12 - Workbench UX and Patch Workflow Polish

V12 focuses on making the AgentX workbench easier to use after V9/V10 established the backend and health foundations.

## Goals

- Improve workspace report access.
- Add download endpoints for analysis artifacts.
- Add a standalone Workbench Report Viewer page.
- Make workspace analysis summaries easier to copy and share.

## New Backend Endpoints

```text
GET /v1/workbench/uploads/{project_id}/inventory
GET /v1/workbench/uploads/{project_id}/analysis-files
GET /v1/workbench/uploads/{project_id}/download/report
GET /v1/workbench/uploads/{project_id}/download/inventory
```

## Validation

```bash
python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests
./scripts/smoke-test-v10.sh
```

## Notes

V12 starts with backend artifact access and documentation. The standalone viewer can be added as the next V12 commit after the endpoints are verified.


## Release Checklist

```bash
git status --short
python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests
./scripts/smoke-test-v10.sh
cd AgentXWeb
npm run typecheck
npm test
npm run build
```

After validation:

```bash
git tag -a v0.3.0-v12 -m "AgentX V12 workbench UX and patch workflow polish"
git push origin v0.3.0-v12
```
