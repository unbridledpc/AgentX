#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$HOME/projects/AgentX}"
PY="$ROOT/.venv/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$ROOT/.venv/bin/python"
fi
if [ ! -x "$PY" ]; then
  echo "[ERR] Could not find AgentX venv Python under $ROOT/.venv" >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_DIR="$(cd "$SCRIPT_DIR/../payload/workbench" && pwd)"
PKG_DIR="$($PY - <<'PY'
from pathlib import Path
import agentx
print(Path(agentx.__file__).resolve().parent)
PY
)"
if [ -z "$PKG_DIR" ] || [ ! -d "$PKG_DIR" ]; then
  echo "[ERR] Could not locate installed agentx package" >&2
  exit 1
fi
mkdir -p "$PKG_DIR/workbench"
cp -f "$PAYLOAD_DIR/__init__.py" "$PKG_DIR/workbench/__init__.py"
cp -f "$PAYLOAD_DIR/analyzer.py" "$PKG_DIR/workbench/analyzer.py"
cp -f "$PAYLOAD_DIR/playground.py" "$PKG_DIR/workbench/playground.py"
# Remove stale bytecode so Python does not reuse an old bad state.
find "$PKG_DIR/workbench" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
# Also mirror into common source locations if present, so future editable/dev runs see it.
for CANDIDATE in "$ROOT/AgentX/workbench" "$ROOT/AgentX/AgentX/workbench" "$ROOT/agentx/workbench"; do
  if [ -d "$(dirname "$CANDIDATE")" ]; then
    mkdir -p "$CANDIDATE"
    cp -f "$PAYLOAD_DIR/__init__.py" "$CANDIDATE/__init__.py"
    cp -f "$PAYLOAD_DIR/analyzer.py" "$CANDIDATE/analyzer.py"
    cp -f "$PAYLOAD_DIR/playground.py" "$CANDIDATE/playground.py"
  fi
done
$PY - <<'PY'
from agentx.workbench.playground import import_and_analyze_zip
print('[OK] agentx.workbench import works')
PY
sudo systemctl restart agentx-api
sleep 2
sudo systemctl status agentx-api --no-pager
