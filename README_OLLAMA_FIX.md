# AgentX Ollama Endpoint Emergency Fix

Apply from the folder that contains your AgentX checkout, or copy the script onto the VM.

```bash
unzip -o AgentX_ollama_endpoint_fix.zip
bash scripts/fix-agentx-ollama-endpoint.sh ~/projects/AgentX http://192.168.68.50:11434 qwen3.5:9b
```

This backs up `AgentX/config/agentx.toml`, sets the Ollama endpoint/model, adds a systemd override for the API service, tests `/api/tags`, then restarts AgentX.

If the test fails, the problem is likely on the Windows Ollama host:

```powershell
$env:OLLAMA_HOST='0.0.0.0:11434'
ollama serve
```

Also allow inbound TCP 11434 through Windows Firewall.
