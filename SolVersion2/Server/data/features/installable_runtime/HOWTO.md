# Installable Runtime

This feature moves NexAI toward a product-style Linux/WSL install instead of a repo-bound dev checkout.

## Goals

- installable under any app directory
- mutable runtime data stored under a chosen runtime root
- no runtime dependence on repo-relative `config/sol.toml`
- CLI lifecycle management
- standard profile can serve built SolWeb assets without Node on the target machine

## CLI

- `./install-sol.sh`
- `nexai setup`
- `nexai start`
- `nexai stop`
- `nexai restart`
- `nexai status`
- `nexai doctor`
- `nexai paths`
- `nexai config show`

## Runtime Layout

Generated under the chosen runtime root:

- `config/sol.toml`
- `extensions/plugins/`
- `extensions/skills/`
- `data/`
- `memory/`
- `logs/`
- `audit/`
- `cache/`
- `tmp/`
- `run/`
- `state/plugins/`
- `state/skills/`
- `state/web/solweb.config.js`

## Service Mode

Linux/WSL support is currently scoped to user services.

- `systemd --user` units are generated when `service_mode=systemd-user`
- native Windows services are intentionally not implemented yet

## Standard Install

Standard installs expect built web assets in `SolWeb/dist`. If those assets ship with the product bundle, the target machine does not need Node or Vite just to run NexAI.

## One-Command Bootstrap

From a repo or release bundle root:

```bash
./install-sol.sh
```

The bootstrap installer:

- checks for `python3`, `python3-venv`, and `curl`
- creates a lightweight bootstrap virtual environment automatically
- installs the NexAI CLI into that bootstrap environment
- writes a stable launcher to `~/.local/bin/nexai`
- keeps `~/.local/bin/sol` as a compatibility alias
- runs `nexai setup` so the real managed runtime can be provisioned under the selected runtime root

This keeps the design split intact:

- bootstrap environment: installer + CLI entrypoint
- managed runtime: created by `nexai setup` under `runtime_root/venv`

Example transcript:

```text
$ ./install-sol.sh
NexAI
Local-first AI assistant platform

Bootstrap install
  App bundle:      /home/nexus/src/sol
  Platform:        wsl
  Bootstrap env:   /home/nexus/.local/share/sol/bootstrap/venv
  Launcher:        /home/nexus/.local/bin/nexai

Creating bootstrap virtual environment...
Installing NexAI CLI into bootstrap environment...

Bootstrap install complete.
  Bootstrap env:      /home/nexus/.local/share/sol/bootstrap/venv
  User launcher:      /home/nexus/.local/bin/nexai
  Compatibility alias: /home/nexus/.local/bin/sol
  CLI fallback:       /home/nexus/.local/share/sol/bootstrap/venv/bin/python -m sol
  Default runtime:    /home/nexus/.local/share/sol
  Install log:        /home/nexus/.local/share/sol/bootstrap/install.log

Launching NexAI setup with the bootstrap environment...
  Command: /home/nexus/.local/share/sol/bootstrap/venv/bin/python -m sol setup
```

After bootstrap setup:

- `nexai start`
- `nexai status`
- open the web UI at `http://127.0.0.1:5173`
