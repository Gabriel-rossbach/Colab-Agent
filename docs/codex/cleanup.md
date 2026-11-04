# Cleanup & Maintenance

## Automatic Cleanup

### Stop All Sessions
```bash
python3 stop_all.py
# Detects active sessions via `colab sessions` regex
# Stops all in parallel
```

### What Gets Cleaned
- Colab sessions (cpu1-cpu6)
- No local artifacts (JSONL, reports persist in `/tmp` or `--out`)

## Manual Cleanup

### Colab CLI
```bash
# List
colab sessions

# Stop specific
colab stop -s cpu1

# Remove session (permanent)
colab rm -s cpu1
```

### Local Artifacts
```bash
# Remove temp runs
rm -rf /tmp/fleet-*.json /tmp/run_*

# Remove plugin build cache
rm -rf /root/openclaw-plugins/web-search/node_modules
rm -rf /root/openclaw-plugins/web-search/dist

# Clear OpenClaw state (nuclear)
openclaw reset
```

## Dependency Updates

### Python
```bash
# Update skill deps
pip install -U textual colab-cli duckduckgo-search python-dotenv

# Check outdated
pip list --outdated
```

### Node (Plugin)
```bash
cd /root/openclaw-plugins/web-search
npm update
npm audit fix
```

### OpenClaw
```bash
# Update CLI
curl -fsSL https://openclaw.ai/install.sh | bash

# Check version
openclaw --version
```

## Log Rotation

```bash
# Gateway logs (per machine, in Colab)
# /tmp/gateway.log - overwritten each run

# Local orchestrator logs
# Only in TUI / stdout; no persistent files
```

## Disk Space

```bash
# Check Colab disk (in session)
df -h /content

# Check local
df -h ~
```

## Scheduled Maintenance (Cron)

```bash
# Weekly: stop orphaned sessions, update deps
0 3 * * 0 /home/apolo/ia/stop_all.py && pip install -U textual colab-cli
```

## Troubleshooting Cleanup Issues

| Issue | Fix |
|-------|-----|
| `colab stop` hangs | `colab stop -s name --force` (if supported) or wait |
| Session stuck "READY" but not SSH-able | `colab rm -s name` then `colab new -s name` |
| Local disk full | `docker system prune -a` if using Docker; `pip cache purge` |
| Plugin reinstall fails | `rm -rf /root/.openclaw/extensions/web-search` then reinstall |