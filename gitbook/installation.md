# Installation

## Supported Install Target

The product-style installer currently targets Linux and WSL, with Ubuntu 24.04 as the primary tested fresh-machine path. Windows-native install/service behavior is not the current target, although the repository can be inspected and developed from Windows.

## Fresh Ubuntu Install

Use the root installer:

```bash
curl -fsSL https://raw.githubusercontent.com/VielNexus/NexAI/main/install.sh | bash
```

What `install.sh` does:

- Checks for Linux and warns if the OS is not Ubuntu 24.04.
- Installs required packages unless `NEXAI_SKIP_APT=1`.
- Ensures Node.js 20+ for building SolWeb.
- Clones the repo to the app bundle path.
- Runs `npm install` and `npm run build` inside `SolWeb`.
- Runs `install-sol.sh` with non-interactive setup arguments.
- Creates the `nexai` launcher under `~/.local/bin`.

Default install paths:

| Item | Default |
| --- | --- |
| App bundle | `~/.local/share/nexai/app` |
| Managed runtime | `~/.local/share/sol` |
| Launcher | `~/.local/bin/nexai` |
| Compatibility alias | `~/.local/bin/sol` |
| API | `127.0.0.1:8420` |
| Web UI | `127.0.0.1:5173` |

## Installer Environment Overrides

`install.sh` supports these environment variables:

| Variable | Purpose |
| --- | --- |
| `NEXAI_REPO_URL` | Git clone URL |
| `NEXAI_REF` | Git ref to install |
| `NEXAI_APP_ROOT` | App bundle path |
| `NEXAI_RUNTIME_ROOT` | Mutable runtime root |
| `NEXAI_WORKDIR` | Working directory exposed to tools |
| `NEXAI_PROFILE` | Install profile: `cli`, `standard`, `server`, or `developer` |
| `NEXAI_MODEL_PROVIDER` | Model provider, usually `ollama` |
| `NEXAI_OLLAMA_BASE_URL` | Ollama endpoint |
| `NEXAI_SKIP_APT` | Skip package installation when set to `1` |
| `NEXAI_SKIP_WEB_BUILD` | Skip SolWeb build when set to `1` |
| `NEXAI_AUTOSTART` | Start services after setup when set to `1` |

Example:

```bash
NEXAI_PROFILE=developer NEXAI_AUTOSTART=1 ./install.sh
```

## Repo-Local Install

From an existing checkout:

```bash
./install-sol.sh
```

This script:

- Creates a lightweight bootstrap virtual environment.
- Installs the Python CLI package from `SolVersion2`.
- Writes `~/.local/bin/nexai`.
- Writes `~/.local/bin/sol` as a compatibility alias.
- Runs `nexai setup` unless `--skip-setup` is passed.

Run without setup:

```bash
./install-sol.sh --skip-setup
nexai setup
```

Pass setup options through:

```bash
./install-sol.sh -- --non-interactive --profile standard --service-mode none
```

## Install Profiles

The install model defines these profiles:

| Profile | Use |
| --- | --- |
| `cli` | CLI-focused install |
| `standard` | Normal local install with API and web UI |
| `server` | Server-style install |
| `developer` | Install with developer/test dependencies |

## Service Modes

The install model defines:

| Mode | Meaning |
| --- | --- |
| `none` | Process lifecycle is managed by `nexai start` and PID files |
| `systemd-user` | User-level systemd units |
| `systemd-system` | System-level systemd mode exists in the model, but user-level is the practical path documented by the CLI |

## After Installation

```bash
nexai doctor
nexai start
nexai status
```

Open:

```text
http://127.0.0.1:5173
```
