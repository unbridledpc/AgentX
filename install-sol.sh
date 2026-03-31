#!/usr/bin/env bash
set -euo pipefail

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_HEAD=$'\033[1;36m'
  C_INFO=$'\033[0;36m'
  C_WARN=$'\033[1;33m'
  C_ERR=$'\033[1;31m'
  C_OK=$'\033[1;32m'
else
  C_RESET=""
  C_HEAD=""
  C_INFO=""
  C_WARN=""
  C_ERR=""
  C_OK=""
fi

header() {
  printf '%s\n' "${C_HEAD}NexAI${C_RESET}"
  printf '%s\n' "${C_INFO}Local-first AI assistant platform${C_RESET}"
  printf '\n'
}

info() {
  printf '%s\n' "${C_INFO}$1${C_RESET}"
}

warn() {
  printf '%s\n' "${C_WARN}$1${C_RESET}" >&2
}

die() {
  printf '%s\n' "${C_ERR}$1${C_RESET}" >&2
  exit 1
}

ok() {
  printf '%s\n' "${C_OK}$1${C_RESET}"
}

usage() {
  cat <<'EOF'
Usage: ./install-sol.sh [--skip-setup] [-- <sol setup args...>]

Bootstraps the NexAI CLI into a lightweight user-local environment and installs
an end-user launcher at ~/.local/bin/sol.

By default this script runs `sol setup` after bootstrap install.
Use --skip-setup to stop after installing the launcher.
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "error: required command not found: $1"
  fi
}

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$SCRIPT_DIR"
RUN_SETUP=1
SETUP_ARGS=()

while (($#)); do
  case "$1" in
    --skip-setup|--no-setup)
      RUN_SETUP=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      SETUP_ARGS=("$@")
      break
      ;;
    *)
      SETUP_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ! -f "$APP_ROOT/SolVersion2/pyproject.toml" ]]; then
  warn "expected: $APP_ROOT/SolVersion2/pyproject.toml"
  die "error: install-sol.sh must be run from the NexAI app bundle root."
fi

OS_KIND="linux"
if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
  OS_KIND="wsl"
fi

if [[ "$OSTYPE" != linux* ]] && [[ "$OS_KIND" != "wsl" ]]; then
  die "error: install-sol.sh currently supports Linux and WSL only."
fi

require_cmd python3
require_cmd curl

if ! python3 -c "import venv" >/dev/null 2>&1; then
  warn "install the python3-venv package and run this script again."
  die "error: python3 can run, but the stdlib venv module is missing."
fi

if [[ -n "${XDG_DATA_HOME:-}" ]]; then
  BOOTSTRAP_ROOT="${XDG_DATA_HOME}/sol/bootstrap"
else
  BOOTSTRAP_ROOT="${HOME}/.local/share/sol/bootstrap"
fi

if [[ -n "${XDG_BIN_HOME:-}" ]]; then
  USER_BIN_DIR="${XDG_BIN_HOME}"
else
  USER_BIN_DIR="${HOME}/.local/bin"
fi

BOOTSTRAP_VENV="${BOOTSTRAP_ROOT}/venv"
BOOTSTRAP_PYTHON="${BOOTSTRAP_VENV}/bin/python"
LAUNCHER_PATH="${USER_BIN_DIR}/nexai"
COMPAT_LAUNCHER_PATH="${USER_BIN_DIR}/sol"
INSTALL_LOG="${BOOTSTRAP_ROOT}/install.log"
BOOTSTRAP_FALLBACK="${BOOTSTRAP_PYTHON} -m sol"

mkdir -p "$BOOTSTRAP_ROOT" "$USER_BIN_DIR"
: >"$INSTALL_LOG"

{
  echo "[bootstrap] platform=${OS_KIND}"
  echo "[bootstrap] app_root=${APP_ROOT}"
  echo "[bootstrap] bootstrap_root=${BOOTSTRAP_ROOT}"
  echo "[bootstrap] bootstrap_python=${BOOTSTRAP_PYTHON}"
  echo "[bootstrap] user_bin_dir=${USER_BIN_DIR}"
} >>"$INSTALL_LOG"

header
info "Bootstrap install"
printf '  App bundle:      %s\n' "${APP_ROOT}"
printf '  Platform:        %s\n' "${OS_KIND}"
printf '  Bootstrap env:   %s\n' "${BOOTSTRAP_VENV}"
printf '  Launcher:        %s\n' "${LAUNCHER_PATH}"
printf '  Compatibility:   %s\n' "${COMPAT_LAUNCHER_PATH}"
printf '\n'

if [[ ! -x "$BOOTSTRAP_PYTHON" ]]; then
  info "Creating bootstrap virtual environment..."
  python3 -m venv "$BOOTSTRAP_VENV" >>"$INSTALL_LOG" 2>&1 || {
    warn "install log: ${INSTALL_LOG}"
    die "error: failed to create bootstrap virtual environment."
  }
fi

if [[ ! -x "$BOOTSTRAP_PYTHON" ]]; then
  warn "install log: ${INSTALL_LOG}"
  die "error: bootstrap interpreter missing after venv creation: ${BOOTSTRAP_PYTHON}"
fi

info "Installing NexAI CLI into bootstrap environment..."
"$BOOTSTRAP_PYTHON" -m pip install --upgrade pip setuptools wheel >>"$INSTALL_LOG" 2>&1 || {
  warn "install log: ${INSTALL_LOG}"
  die "error: failed to upgrade bootstrap packaging tools."
}
"$BOOTSTRAP_PYTHON" -m pip install --upgrade "${APP_ROOT}/SolVersion2[cli]" >>"$INSTALL_LOG" 2>&1 || {
  warn "install log: ${INSTALL_LOG}"
  die "error: failed to install NexAI into the bootstrap environment."
}

"$BOOTSTRAP_PYTHON" - <<PY >>"$INSTALL_LOG" 2>&1 || {
import sys
from pathlib import Path
from sol.install.bootstrap import (
    bootstrap_app_root_record_path,
    ensure_bootstrap_python,
    launcher_validation_error,
    launcher_targets_bootstrap_python,
    write_bootstrap_app_root_record,
    write_bootstrap_launcher,
)

expected_bootstrap_root = Path(r"${BOOTSTRAP_ROOT}").expanduser().absolute()
expected_bootstrap_python = ensure_bootstrap_python(
    bootstrap_python=Path(r"${BOOTSTRAP_PYTHON}"),
    bootstrap_root=expected_bootstrap_root,
    require_exists=True,
)
actual_python = Path(sys.executable).expanduser().absolute()
print(f"[bootstrap-helper] sys.executable={actual_python}")
print(f"[bootstrap-helper] expected_bootstrap_python={expected_bootstrap_python}")
print(f"[bootstrap-helper] app_root={Path(r'${APP_ROOT}').resolve()}")
if actual_python != expected_bootstrap_python:
    raise RuntimeError(
        "Bootstrap helper is running under the wrong interpreter: "
        f"{actual_python}. Expected: {expected_bootstrap_python}. "
        "install-sol.sh must invoke every bootstrap helper via BOOTSTRAP_PYTHON."
    )

launcher = write_bootstrap_launcher(
    launcher_path=Path(r"${LAUNCHER_PATH}"),
    bootstrap_python=expected_bootstrap_python,
    app_root=Path(r"${APP_ROOT}"),
)
compat_launcher = write_bootstrap_launcher(
    launcher_path=Path(r"${COMPAT_LAUNCHER_PATH}"),
    bootstrap_python=expected_bootstrap_python,
    app_root=Path(r"${APP_ROOT}"),
)
write_bootstrap_app_root_record(
    record_path=bootstrap_app_root_record_path(bootstrap_python=expected_bootstrap_python),
    app_root=Path(r"${APP_ROOT}"),
    bootstrap_python=expected_bootstrap_python,
)
text = launcher.read_text(encoding="utf-8")
if not launcher_targets_bootstrap_python(launcher_text=text, bootstrap_python=expected_bootstrap_python):
    raise RuntimeError(f"launcher does not target bootstrap interpreter: {launcher}")
validation_error = launcher_validation_error(
    launcher_text=text,
    bootstrap_python=expected_bootstrap_python,
    app_root=Path(r"${APP_ROOT}"),
)
if validation_error:
    raise RuntimeError(validation_error)
compat_text = compat_launcher.read_text(encoding="utf-8")
compat_error = launcher_validation_error(
    launcher_text=compat_text,
    bootstrap_python=expected_bootstrap_python,
    app_root=Path(r"${APP_ROOT}"),
)
if compat_error:
    raise RuntimeError(f"compatibility launcher invalid: {compat_error}")
PY
  warn "install log: ${INSTALL_LOG}"
  die "error: failed to write the NexAI launchers."
}

if ! echo ":$PATH:" | grep -Fq ":${USER_BIN_DIR}:"; then
  warn "warning: ${USER_BIN_DIR} is not currently on PATH."
  warn "add this to your shell profile:"
  warn "  export PATH=\"${USER_BIN_DIR}:\$PATH\""
  warn "launcher path: ${LAUNCHER_PATH}"
  warn "compatibility alias: ${COMPAT_LAUNCHER_PATH}"
  warn "bootstrap fallback: ${BOOTSTRAP_FALLBACK}"
fi

CURRENT_NEXAI="$(command -v nexai 2>/dev/null || true)"
if [[ -n "$CURRENT_NEXAI" ]] && [[ "$CURRENT_NEXAI" != "$LAUNCHER_PATH" ]]; then
  warn "warning: another nexai command is currently ahead on PATH: ${CURRENT_NEXAI}"
  warn "intended launcher: ${LAUNCHER_PATH}"
fi
CURRENT_SOL="$(command -v sol 2>/dev/null || true)"
if [[ -n "$CURRENT_SOL" ]] && [[ "$CURRENT_SOL" != "$COMPAT_LAUNCHER_PATH" ]]; then
  warn "warning: 'sol' may resolve to a different command or a system game: ${CURRENT_SOL}"
  warn "use nexai as the supported NexAI command"
fi

printf '\n'
ok "Bootstrap install complete."
  printf '  Bootstrap env:      %s\n' "${BOOTSTRAP_VENV}"
printf '  User launcher:      %s\n' "${LAUNCHER_PATH}"
printf '  Compatibility alias:%s\n' " ${COMPAT_LAUNCHER_PATH}"
printf '  CLI fallback:       %s\n' "${BOOTSTRAP_FALLBACK}"
printf '  Default runtime:    %s\n' "${HOME}/.local/share/sol"
printf '  Install log:        %s\n' "${INSTALL_LOG}"
printf '\n'

if (( RUN_SETUP )); then
  SETUP_CMD=("${BOOTSTRAP_PYTHON}" -m sol setup "${SETUP_ARGS[@]}")
  printf -v SETUP_CMD_TEXT '%q ' "${SETUP_CMD[@]}"
  info "Launching NexAI setup with the bootstrap environment..."
  printf '  Command: %s\n' "${SETUP_CMD_TEXT% }"
  export SOL_BOOTSTRAP_APP_ROOT="${APP_ROOT}"
  if ! "${SETUP_CMD[@]}"; then
    warn "command: ${SETUP_CMD_TEXT% }"
    warn "install log: ${INSTALL_LOG}"
    die "error: failed to launch NexAI setup through the bootstrap environment."
  fi
  exit 0
fi

info "Next steps:"
printf '  %s setup\n' "${LAUNCHER_PATH}"
printf '  %s start\n' "${LAUNCHER_PATH}"
printf '  %s status\n' "${LAUNCHER_PATH}"
printf '  %s doctor\n' "${BOOTSTRAP_FALLBACK}"
printf '  Legacy alias: %s\n' "${COMPAT_LAUNCHER_PATH}"
printf '  Web UI: http://127.0.0.1:5173\n'
