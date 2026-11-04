# Workflow Guide

## Standard Research Workflow

```
1. REQUEST
   User: "pesquise 5 plugins de navegação para OpenClaw"

2. PLAN (cpu6/GPU)
   → init_fleet_plan.py → fleet-plan.json (validated)
   → Shows: 5 tasks across cpu1-cpu3

3. CONFIRM (Human)
   → Dashboard shows plan
   → User types "continuar"

4. EXECUTE (cpu1-5/CPU, parallel with stagger)
   → Each machine: install → gateway → agent exec → results
   → Logs stream to TUI panels

5. GATES (Post-processing)
   → run_fleet.py applies promotion gates
   → Pass/fail with metrics

6. REPORT
   → render_fleet_summary.py → markdown + JSONL
   → Ready for use / sharing
```

## Commands Reference

### Generate Plan
```bash
# Interactive (with dashboard)
python3 -m colab_agent_fleet.dashboard

# Headless (CI/automation)
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "sua pesquisa aqui" \
  --model gpt-oss:20b
```

### Validate Plan
```bash
python3 -m colab_agent_fleet.scripts.validate_fleet_plan.py \
  --plan /tmp/plan.json \
  --request "sua pesquisa aqui"
```

### Execute Fleet
```bash
# With confirmation
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run

# Auto-confirm (CI)
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm \
  --gates '{"min_success_ratio": 0.8}'
```

### Render Summary
```bash
python3 -m colab_agent_fleet.scripts.render_fleet_summary.py \
  --results /tmp/run.jsonl \
  --gates /tmp/run_gates.json \
  --request "original request" \
  --out /tmp/report.md
```

### Capture Context (Before Run)
```bash
python3 -m colab_agent_fleet.scripts.capture_fleet_context.py \
  --out /tmp/context.json \
  --repo-root .
```

## Environment Variables

| Var | Required | Default | Description |
|-----|----------|---------|-------------|
| `NVIDIA_API_KEY` | Yes | - | NVIDIA NIMs API key |
| `MODELO_PLANEJADOR` | No | `gpt-oss:20b` | Ollama model for planner |
| `MAQUINAS` | No | `cpu1,cpu2,cpu3,cpu4,cpu5` | Target Colab sessions |
| `FLAGS_GPU` | No | `--gpu t4` | GPU flags for cpu6 |

## Colab Session Management

```bash
# Check active sessions
colab sessions

# Create missing sessions
for m in cpu1 cpu2 cpu3 cpu4 cpu5; do colab new -s $m; done

# Create GPU session for planner
colab new -s cpu6 --gpu t4

# Stop all
python3 stop_all.py
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `web_search is disabled` | Check plugin installed + gateway running |
| `SQLite offline maintenance` | Wait 30s; retry; ensure pipeline stagger |
| `colab ssh 429` | Wait for previous SSH to close; serialize |
| `Gateway health-check timeout` | Increase wait; check `/tmp/gateway.log` |
| `Plugin not found` | Reinstall: `openclaw plugins install /root/openclaw-plugins/web-search --force --accept-capabilities` |
| `Rate limited` | DuckDuckGo HTML scraping has limits; add delay or reduce `max_results` |

## CI/CD Example

```yaml
# .github/workflows/fleet-research.yml
name: Fleet Research
on:
  workflow_dispatch:
    inputs:
      request:
        description: 'Research request'
        required: true
      auto_confirm:
        type: boolean
        default: true

jobs:
  research:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Install deps
        run: pip install -e . pytest textual colab-cli
      - name: Generate plan
        env:
          MODELO_PLANEJADOR: gpt-oss:20b
        run: |
          python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
            --out /tmp/plan.json \
            --request "${{ github.event.inputs.request }}"
      - name: Validate plan
        run: |
          python3 -m colab_agent_fleet.scripts.validate_fleet_plan.py \
            --plan /tmp/plan.json \
            --request "${{ github.event.inputs.request }}"
      - name: Run fleet
        env:
          NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}
        run: |
          python3 -m colab_agent_fleet.scripts.run_fleet.py \
            --plan /tmp/plan.json \
            --out /tmp/run \
            --auto-confirm
      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: fleet-report
          path: /tmp/run_summary.md
```