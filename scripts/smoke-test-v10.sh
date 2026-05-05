#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${AGENTX_API_BASE:-http://127.0.0.1:8000}"
WEB_BASE="${AGENTX_WEB_BASE:-http://127.0.0.1:5173}"

echo "[AgentX V10 smoke test]"
echo "Root: $ROOT"
echo "API:  $API_BASE"
echo "Web:  $WEB_BASE"
echo

echo "[1/7] API root"
curl -fsS "$API_BASE/" >/dev/null
echo "OK"

echo "[2/7] API status"
curl -fsS "$API_BASE/v1/status" >/dev/null
echo "OK"

echo "[3/7] API full health"
curl -fsS "$API_BASE/v1/health/full" | python3 -m json.tool >/dev/null
echo "OK"

echo "[4/7] Web UI"
curl -fsS "$WEB_BASE/" >/dev/null
echo "OK"

echo "[5/7] Python compileall"
cd "$ROOT"
python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests >/dev/null
echo "OK"

echo "[6/7] Frontend typecheck + tests"
cd "$ROOT/AgentXWeb"
npm run typecheck
npm test
echo "OK"

echo "[7/7] Frontend production build"
npm run build
echo "OK"

echo
echo "AgentX V10 smoke test passed."
