# HOWTO: Work With the Unified AgentX Package Tree

## Validate

```bash
cd ~/projects/AgentX/AgentX
python3 scripts/check_package_tree.py
python3 -m compileall agentx
python3 -m agentx.cli memory search-project "project memory pipeline"
```

## Restart services

```bash
sudo systemctl restart agentx-api
sudo systemctl restart agentx-web
```
