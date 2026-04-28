# Installation

## Supported Install Target

The product-style installer currently targets Linux and WSL, with Ubuntu 24.04 as the primary tested fresh-machine path. Windows-native install/service behavior is not the current target, although the repository can be inspected and developed from Windows.

## Fresh Ubuntu Install

Use the root installer:

```bash
curl -fsSL https://raw.githubusercontent.com/unbridledpc/AgentX/main/install.sh | bash
```

What `install.sh` does:

- Checks for Linux and warns if the OS is not Ubuntu 24.04.
- Installs required packages unless `AGENTX_SKIP_APT=1`.
- Ensures Node.js 20.19+ on Node 20, or Node.js 22.12+ or newer for building AgentXWeb with Vite 8.
- Clones the repo to the app bundle path.
- Runs `npm install` and `npm run build` inside `AgentXWeb`.
- Runs `install-agentx.sh` with non-interactive setup arguments.
- Creates the `agentx` launcher under `~/.local/bin`.

Default install paths:

| Item | Default |
| --- | --- |
| App bundle | `~/.local/share/agentx/app` |
| Managed runtime | `~/.local/share/agentx` |
| Launcher | `~/.local/bin/agentx` |
| Compatibility aliases | `~/.local/bin/nexai`, `~/.local/bin/sol` |
| API | `127.0.0.1:8420` |
| Web UI | `127.0.0.1:5173` |

## Installer Environment Overrides

`install.sh` supports these environment variables:

| Variable | Purpose |
| --- | --- |
| `AGENTX_REPO_URL` | Git clone URL |
| `AGENTX_REF` | Git ref to install |
| `AGENTX_APP_ROOT` | App bundle path |
| `AGENTX_RUNTIME_ROOT` | Mutable runtime root |
| `AGENTX_WORKDIR` | Working directory exposed to tools |
| `AGENTX_PROFILE` | Install profile: `cli`, `standard`, `server`, or `developer` |
| `AGENTX_MODEL_PROVIDER` | Model provider, usually `ollama` |
| `AGENTX_OLLAMA_BASE_URL` | Ollama endpoint |
| `AGENTX_SKIP_APT` | Skip package installation when set to `1` |
| `AGENTX_SKIP_WEB_BUILD` | Skip AgentXWeb build when set to `1` |
| `AGENTX_AUTOSTART` | Start services after setup when set to `1` |

Legacy `NEXAI_*` installer variables are accepted as deprecated fallbacks when the matching `AGENTX_*` variable is unset.

Example:

```bash
AGENTX_PROFILE=developer AGENTX_AUTOSTART=1 ./install.sh
```

## Repo-Local Install

From an existing checkout:

```bash
./install-agentx.sh
```

This script:

- Creates a lightweight bootstrap virtual environment.
- Installs the Python CLI package from `AgentX`.
- Writes `~/.local/bin/agentx`.
- Writes deprecated compatibility aliases at `~/.local/bin/nexai` and `~/.local/bin/sol`.
- Runs `agentx setup` unless `--skip-setup` is passed.

Run without setup:

```bash
./install-agentx.sh --skip-setup
agentx setup
```

Pass setup options through:

```bash
./install-agentx.sh -- --non-interactive --profile standard --service-mode none
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
| `none` | Process lifecycle is managed by `agentx start` and PID files |
| `systemd-user` | User-level systemd units |
| `systemd-system` | System-level systemd mode exists in the model, but user-level is the practical path documented by the CLI |

## After Installation

```bash
agentx doctor
agentx start
agentx status
```

Open:

```text
http://127.0.0.1:5173
```

### WSL browser access

WSL fresh installs bind the API and web UI to `0.0.0.0` by default so Windows can reach AgentX through the WSL IP. Find it with:

```bash
hostname -I | awk '{print $1}'
```

Then open `http://<wsl-ip>:5173` from Windows. Native Linux installs still default to localhost unless overridden with `AGENTX_API_HOST` or `AGENTX_WEB_HOST`.
