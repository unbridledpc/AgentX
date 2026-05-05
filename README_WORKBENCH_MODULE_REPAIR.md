# AgentX Workbench module repair

This fixes the API crash:

`ModuleNotFoundError: No module named 'agentx.workbench'`

Run from `~/projects/AgentX` after unzipping:

```bash
unzip -o AgentX_workbench_module_repair.zip
bash scripts/repair-agentx-workbench-module.sh ~/projects/AgentX
```

Then verify:

```bash
journalctl -u agentx-api -n 80 --no-pager
curl http://127.0.0.1:8000/v1/status || true
```
