# NexAI

Supervised local agent runtime for NexAI.

Key capabilities:

- audited tool execution
- local memory and retrieval
- supervised autonomous jobs
- manifest-driven tool plugins
- instruction-only skills
- local `SKILL.md` skill-pack import
- installable runtime with `nexai setup`, `nexai start`, `nexai stop`, `nexai status`, and product-style runtime/data separation

## Bootstrap Install

Linux/WSL repo installs are intended to start with:

```bash
./install-sol.sh
```

That script:

- creates a lightweight bootstrap virtual environment automatically
- installs the NexAI CLI into that bootstrap environment
- writes a stable user launcher at `~/.local/bin/nexai`
- keeps `~/.local/bin/sol` as a compatibility alias during migration
- then starts `nexai setup` so NexAI can provision its managed runtime separately

The bootstrap environment is not the main runtime. For `standard`, `server`, and `developer` profiles, `nexai setup` still provisions the real managed runtime under `runtime_root/venv`.
