# Package Tree Unification

AgentX now uses one canonical Python source package:

```text
agentx/
```

Older duplicate source trees such as `AgentX/`, `core/`, `cli/`, `tools/`, `jobs`, and `install/` were moved out of the active source layout because they allowed patches to land in folders the runtime did not import.

## Rule

`agentx.*` is source of truth.

Put all new backend Python source under `agentx/` and run:

```bash
python3 scripts/check_package_tree.py
```
