#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$HOME/projects/AgentX}"
cd "$ROOT"
echo "[INFO] Installing AgentX frontend archive workbench patch into $ROOT"
mkdir -p AgentX/agentx/workbench apps/api/agentx_api/routes AgentXWeb/src/api AgentXWeb/src/ui AgentXWeb/dist/assets
cp -a payload/AgentX/agentx/workbench/* AgentX/agentx/workbench/
cp -a payload/apps/api/agentx_api/routes/workbench.py apps/api/agentx_api/routes/workbench.py
cp -a payload/AgentXWeb/src/api/client.ts AgentXWeb/src/api/client.ts
cp -a payload/AgentXWeb/src/ui/App.tsx AgentXWeb/src/ui/App.tsx
cp -a payload/AgentXWeb/dist/index.html AgentXWeb/dist/index.html
cp -a payload/AgentXWeb/dist/assets/* AgentXWeb/dist/assets/
find AgentX/agentx/workbench -type f -name '*.pyc' -delete 2>/dev/null || true
PYTHONPATH="$ROOT/AgentX:$ROOT/apps/api" python3 - <<'PY'
from agentx.workbench.playground import import_and_analyze_archive
print('[OK] backend workbench archive import module is available')
PY
sudo systemctl restart agentx-api
sudo systemctl restart agentx-web
echo "[OK] Installed. In the WebUI + menu, use: Upload server archive"
