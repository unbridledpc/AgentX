#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/projects/AgentX}"
FAST_URL="${2:-http://192.168.68.50:11434}"
MODEL="${3:-qwen3.5:9b}"
CONFIG="$ROOT/AgentX/config/agentx.toml"

if [[ ! -f "$CONFIG" ]]; then
  echo "[ERROR] Could not find config: $CONFIG" >&2
  echo "Usage: $0 /path/to/AgentX http://OLLAMA_HOST:PORT model-name" >&2
  exit 1
fi

BACKUP="$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"
cp -a "$CONFIG" "$BACKUP"
echo "[OK] Backup written: $BACKUP"

# Force the base provider and Ollama settings in agentx.toml.
perl -0pi -e 's/^\[llm\]\s*provider\s*=\s*"[^"]*"/[llm]\nprovider = "ollama"/ms' "$CONFIG"
perl -0pi -e 's#(^\[llm\.ollama\].*?^base_url\s*=\s*)"[^"]*"#$1"'"$FAST_URL"'"#ms' "$CONFIG"
perl -0pi -e 's#(^\[llm\.ollama\].*?^model\s*=\s*)"[^"]*"#$1"'"$MODEL"'"#ms' "$CONFIG"
perl -0pi -e 's#(^\[llm\.ollama\].*?^timeout_s\s*=\s*)\d+#$160#ms' "$CONFIG"

# Make sure systemd/runtime override exists for the API service if possible.
if command -v systemctl >/dev/null 2>&1; then
  sudo mkdir -p /etc/systemd/system/agentx-api.service.d
  sudo tee /etc/systemd/system/agentx-api.service.d/10-ollama-endpoint.conf >/dev/null <<EOF
[Service]
Environment=AGENTX_OLLAMA_BASE_URL=$FAST_URL
Environment=AGENTX_OLLAMA_MODEL=$MODEL
Environment=AGENTX_OLLAMA_TIMEOUT_S=60
EOF
  sudo systemctl daemon-reload
fi

echo "[OK] Set Ollama endpoint to: $FAST_URL"
echo "[OK] Set Ollama model to: $MODEL"

if command -v curl >/dev/null 2>&1; then
  echo "[CHECK] Testing Ollama from this machine..."
  if curl -fsS "$FAST_URL/api/tags" >/tmp/agentx-ollama-tags.json; then
    echo "[OK] Ollama is reachable at $FAST_URL"
  else
    echo "[WARN] Could not reach $FAST_URL/api/tags from this machine."
    echo "[WARN] On Windows, check OLLAMA_HOST=0.0.0.0:11434 and Windows Firewall."
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  echo "[RESTART] Restarting AgentX services..."
  sudo systemctl restart agentx-api || true
  sudo systemctl restart agentx-web || true
  sudo systemctl status agentx-api --no-pager -n 20 || true
fi
