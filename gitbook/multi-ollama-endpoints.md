# Multi-Ollama Endpoints

AgentX can route different jobs to different Ollama endpoints. This lets a fast/smaller GPU handle lightweight draft work while a larger GPU handles heavy review and repair work.

## Example topology

| Role | URL | GPU label | Suggested model |
| --- | --- | --- | --- |
| Fast | `http://192.168.68.50:11434` | `CUDA_VISIBLE_DEVICES=1` | `qwen2.5-coder:7b-4k-gpu` |
| Heavy | `http://192.168.68.50:11435` | `CUDA_VISIBLE_DEVICES=0` | `devstral-small-2:24b-4k-gpu` |

## Important limitation

AgentX routes requests by endpoint URL. It cannot force GPU assignment inside a remote Windows Ollama process. GPU pinning must be handled by the scripts or services that start Ollama.

## Recommended Draft + Review routing

- Draft endpoint: Fast
- Review endpoint: Heavy
- Repair endpoint: Heavy

## Windows Ollama host

Run separate Ollama servers with different ports and environment variables:

```powershell
$env:CUDA_VISIBLE_DEVICES='1'
$env:OLLAMA_HOST='0.0.0.0:11434'
ollama serve
```

```powershell
$env:CUDA_VISIBLE_DEVICES='0'
$env:OLLAMA_HOST='0.0.0.0:11435'
ollama serve
```

Use scheduled tasks or background startup scripts for persistent startup.
