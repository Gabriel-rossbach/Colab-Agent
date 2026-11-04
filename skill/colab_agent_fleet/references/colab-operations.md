# Colab Operations Reference

## Colab CLI Patterns

### Session Management
```bash
# List active sessions
colab sessions

# Create new CPU session
colab new -s cpu1

# Create GPU session (T4, L4, etc.)
colab new -s cpu6 --gpu t4

# Stop session
colab stop -s cpu1

# SSH into session (run command via stdin)
colab ssh -s cpu1 << 'EOF'
command1
command2
exit
EOF

# SSH with command as argument (limited - use stdin pipe for complex scripts)
colab ssh -s cpu1 -- command arg1 arg2
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `HTTP 429: another colab ssh is connected` | Concurrent SSH to same session | Serialize access; wait for previous to finish |
| `session not found` | Session stopped or wrong name | `colab sessions` to verify; `colab new -s name` to recreate |
| `GPU not available` | Quota exhausted or region limit | Try different GPU type (`--gpu l4`, `--gpu a100`) or wait |
| Slow startup | Cold VM boot | First run ~2-3 min; subsequent ~30s |

### Session Lifecycle in Fleet

```
1. Orchestrator checks `colab sessions` → verifies cpu1-cpu5 exist
2. If missing → `colab new -s cpuN` (15s wait for boot)
3. Deploy script runs via `colab ssh -s cpuN` (stdin pipe)
4. Script installs OpenClaw, plugin, configures NVIDIA, starts gateway
5. Agent runs → returns results
6. Orchestrator aggregates → human sees summary
7. Optional: `colab stop -s cpuN` to save compute
```

## GPU vs CPU Shapes

| Shape | Accelerator | Use Case | Cost (compute units/hr) |
|-------|-------------|----------|------------------------|
| CPU | None | Web search, lightweight | ~1 |
| T4 | 1× T4 16GB | Planner (Ollama), light inference | ~4 |
| L4 | 1× L4 24GB | Heavy local inference | ~8 |
| A100 | 1× A100 40/80GB | Training, large models | ~30+ |

**Fleet default**: cpu1-cpu5 = CPU, cpu6 = T4 (planner only)

## SSH Quirks

### Stdin Pipe (Recommended for Scripts)
```python
proc = await asyncio.create_subprocess_shell(
    f"colab ssh -s {maquina}",
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
)
proc.stdin.write(script.encode())
proc.stdin.close()
```

### Command Argument (Limited)
```bash
# Only works for simple commands without pipes/redirections
colab ssh -s cpu1 -- openclaw agent exec "prompt"
```

### Exit Handling
Always end script with `exit` to close SSH cleanly:
```bash
echo 'commands...'
exit
```

## Environment Variables in Colab

Colab sessions inherit some env vars but not all. Best practice: **pass via stdin script**:

```bash
# In script sent via stdin:
export NVIDIA_API_KEY="nvapi-xxx"
export MODELO_PLANEJADOR="gpt-oss:20b"
```

Or use `openclaw config set` for persistent config:
```bash
openclaw config set models.providers.nvidia.apiKey "$NVIDIA_API_KEY"
```

## Disk & Persistence

- `/content` = ephemeral (reset on session restart)
- `/root` = persists across restarts (but not across `colab stop/start`)
- Google Drive mount: `colab drivemount` → `/content/drive`
- For fleet: use `/root` for plugin installs, `/tmp` for transient logs

## Network

- Each Colab session = **unique public IP** (Google Cloud egress)
- 5 sessions = 5 different IPs = natural rate-limit distribution
- No VPC peering between sessions
- Outbound only; no inbound ports (use `colab ssh` for access)