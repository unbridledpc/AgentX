#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$PWD}"
WEB_DIR="$ROOT/AgentXWeb"
if [ ! -d "$WEB_DIR/src/ui/components" ]; then
  echo "[ERROR] Could not find AgentXWeb source at: $WEB_DIR" >&2
  echo "Usage: bash scripts/install-copy-button-fix.sh ~/projects/AgentX" >&2
  exit 1
fi
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$WEB_DIR/.backups/copy-fix-$TS"
cp -a "$WEB_DIR/src/ui/components/MessageActions.tsx" "$WEB_DIR/.backups/copy-fix-$TS/MessageActions.tsx.bak" 2>/dev/null || true
cp -a "$WEB_DIR/src/ui/components/CodeBlock.tsx" "$WEB_DIR/.backups/copy-fix-$TS/CodeBlock.tsx.bak" 2>/dev/null || true
cp -a "$WEB_DIR/src/ui/components/CodeCanvas.tsx" "$WEB_DIR/.backups/copy-fix-$TS/CodeCanvas.tsx.bak" 2>/dev/null || true
mkdir -p "$WEB_DIR/src/ui/components"
cp -a "$ROOT/payload/src/ui/clipboard.ts" "$WEB_DIR/src/ui/clipboard.ts"
cp -a "$ROOT/payload/src/ui/components/MessageActions.tsx" "$WEB_DIR/src/ui/components/MessageActions.tsx"
cp -a "$ROOT/payload/src/ui/components/CodeBlock.tsx" "$WEB_DIR/src/ui/components/CodeBlock.tsx"
cp -a "$ROOT/payload/src/ui/components/CodeCanvas.tsx" "$WEB_DIR/src/ui/components/CodeCanvas.tsx"
cd "$WEB_DIR"
echo "[BUILD] Building AgentXWeb..."
npm run build
echo "[RESTART] Restarting AgentX web service..."
sudo systemctl restart agentx-web || true
echo "[OK] Copy button fallback installed. Hard refresh the browser with Ctrl+F5."
