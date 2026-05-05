#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

V12_VERSION="0.3.0-v12"
V12_NAME="AgentX V12 — Workbench UX and Patch Workflow Polish"

echo "[AgentX V12 finalizer]"
echo "Root: $ROOT"
echo "Version: $V12_VERSION"
echo

echo "[1/6] Bump AgentXWeb package metadata"
python3 - <<'PY'
import json
from pathlib import Path

version = "0.3.0-v12"
for file_name in ["AgentXWeb/package.json", "AgentXWeb/package-lock.json"]:
    path = Path(file_name)
    if not path.exists():
        continue
    data = json.loads(path.read_text())
    data["version"] = version
    if file_name.endswith("package-lock.json") and "packages" in data and "" in data["packages"]:
        data["packages"][""]["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
PY

echo "[2/6] Update public-safe frontend config examples"
python3 - <<'PY'
from pathlib import Path

version = "0.3.0-v12"

env_example = Path("AgentXWeb/.env.example")
if env_example.exists():
    text = env_example.read_text()
else:
    text = ""
lines = []
seen_version = False
seen_sha = False
for line in text.splitlines():
    if line.startswith("VITE_AGENTX_APP_VERSION="):
        lines.append(f"VITE_AGENTX_APP_VERSION={version}")
        seen_version = True
    elif line.startswith("VITE_AGENTX_BUILD_SHA="):
        lines.append("VITE_AGENTX_BUILD_SHA=")
        seen_sha = True
    else:
        lines.append(line)
if not seen_version:
    lines.append(f"VITE_AGENTX_APP_VERSION={version}")
if not seen_sha:
    lines.append("VITE_AGENTX_BUILD_SHA=")
env_example.write_text("\n".join(lines).strip() + "\n")

example = Path("AgentXWeb/public/agentxweb.config.example.js")
example.write_text(f"""// Public-safe AgentXWeb runtime config example.
// Copy to agentxweb.local.config.js or agentxweb.config.js for a deployment-specific override.
// Do not commit private LAN IPs here.
window.AGENTX_WEB_CONFIG = {{
  apiBase: window.location.origin.replace(":5173", ":8000").replace(":5174", ":8000"),
  updateFeed: {{
    enabled: true,
    repo: "unbridledpc/AgentX",
    branch: "main",
    currentSha: "",
    currentVersion: "{version}"
  }}
}};
""")
PY

echo "[3/6] Add V12 release notes"
python3 - <<'PY'
from pathlib import Path

section = """## 0.3.0-v12

### Added
- V12 workbench artifact endpoints for inventory, analysis files, report download, and inventory download.
- Standalone Workbench Report Viewer page for browsing imported archive workspace reports.
- V12 workbench UX documentation.

### Changed
- Bumped AgentXWeb release metadata to `0.3.0-v12`.
- Added public-safe V12 runtime config examples.

### Validation
- Python compileall should pass.
- AgentX V10 smoke test should pass.
- Frontend typecheck, tests, and production build should pass.

### Notes
- V12 focuses on workbench usability without rewriting the existing large `workspaces.html` page.

"""

path = Path("CHANGELOG.md")
old = path.read_text() if path.exists() else ""
if "## 0.3.0-v12" not in old:
    path.write_text(section + old)
PY

echo "[4/6] Update root README release references where present"
python3 - <<'PY'
from pathlib import Path

path = Path("README.md")
if path.exists():
    text = path.read_text()
    text = text.replace("v0.2.8-v10", "v0.3.0-v12")
    text = text.replace("AgentX V10 — Health Dashboard and Smoke-Test Release", "AgentX V12 — Workbench UX and Patch Workflow Polish")
    if "v0.3.0-v12" in text and "Workbench Report Viewer" not in text:
        text += """

## V12 Workbench Report Viewer

AgentX V12 adds a standalone workbench report viewer:

```text
/workbench-report-viewer.html
```

The viewer displays imported archive workspaces, final reports, inventory artifacts, and download/copy actions for workbench analysis output.
"""
    path.write_text(text)
PY

echo "[5/6] Ensure supplemental V12 README has complete release checklist"
python3 - <<'PY'
from pathlib import Path

path = Path("readme/README_V12_WORKBENCH_UX.md")
path.parent.mkdir(parents=True, exist_ok=True)
text = path.read_text() if path.exists() else "# AgentX V12 — Workbench UX and Patch Workflow Polish\n"
extra = """

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
"""
if "## Release Checklist" not in text:
    text = text.rstrip() + "\n" + extra
path.write_text(text)
PY

echo "[6/6] Check for hard-coded private homelab IPs in public docs/source"
if grep -R "192\\.168\\.68\\." -n README.md readme AgentXWeb AgentX apps scripts \
  --exclude-dir=node_modules \
  --exclude-dir=dist \
  --exclude-dir=.git \
  --exclude-dir=work \
  --exclude-dir=data \
  2>/dev/null; then
  echo
  echo "WARNING: Private 192.168.68.x references were found above."
  echo "Review before committing public files."
else
  echo "OK: no public 192.168.68.x references found outside excluded runtime data."
fi

echo
echo "V12 finalizer complete."
echo "Next:"
echo "  python3 -m compileall AgentX/agentx apps/api/agentx_api apps/api/tests"
echo "  ./scripts/smoke-test-v10.sh"
echo "  git status --short"
