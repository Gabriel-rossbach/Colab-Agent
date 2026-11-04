# Fleet Architecture Reference

## Overview

Colab Agent Fleet implements a **two-lane architecture** for distributed web research:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR (local)                         │
│  - Receives natural language request                                │
│  - Calls Planner (GPU lane) → validated fleet plan                  │
│  - Human confirmation via TUI                                       │
│  - Launches fleet in parallel via colab ssh                        │
│  - Aggregates results, applies promotion gates                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌────────────┐  ┌────────────┐  ┌────────────┐
             │   cpu1     │  │   cpu2     │  │   cpu3     │  ...
             │ OpenClaw   │  │ OpenClaw   │  │ OpenClaw   │
             │ + web_search│  │ + web_search│  │ + web_search│
             └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
                   │               │               │
                   └───────────────┼───────────────┘
                                   ▼
                          ┌──────────────────┐
                          │  Results JSONL   │
                          │  + Gates + MD    │
                          └──────────────────┘
```

## Lane Separation

| Lane | Machine | Model | Purpose |
|------|---------|-------|---------|
| **Planning** | cpu6 (GPU) | gpt-oss:20b (Ollama) | Freeze plan, validate structure, distribute tasks |
| **Execution** | cpu1-5 (CPU) | Nemotron 3.5 (NVIDIA NIMs) | Run web_search, return structured evidence |

**Why separate?**
- GPU lane runs local LLM (free, private, no API keys)
- CPU fleet uses NVIDIA NIMs (fast, structured output, web_search tool)
- Cost optimization: GPU only for planning (seconds), CPUs for parallel execution

## Failure Modes & Mitigations

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| SQLite lock (`offline maintenance`) | Logs show "state undergoing offline maintenance" | Pipeline stagger (60s between machine starts) |
| Gateway not ready | Health-check curl fails | 30-retries × 2s polling before agent launch |
| colab ssh 429 (session busy) | HTTP 429 on SSH connect | Sequential per-machine; retry with backoff |
| Plugin not loaded | `web_search is disabled` | Explicit plugin install + gateway restart per machine |
| Rate limit (DuckDuckGo) | Empty results / errors | 5 machines × different IPs = natural distribution |

## Data Flow

1. **Request** → Natural language string
2. **Plan** → Validated JSON: `{"request": "...", "tasks": [{"cpu": 1, "task": 1, "prompt": "..."}]}`
3. **Launch** → Per-machine bash script via `colab ssh -s cpuN` (stdin pipe)
4. **Execute** → Each machine: install OpenClaw → install plugin → start gateway → run agent
5. **Collect** → JSONL lines per task: `{maquina, task, prompt, sucesso, saida_bruta, timestamp}`
6. **Gate** → Apply promotion rules (success ratio, dedup, min sources)
7. **Report** → Markdown summary + gates JSON + raw JSONL

## Promotion Gates

Default gates (configurable via `--gates` JSON):

```json
{
  "min_unique_sources": 3,
  "max_dup_ratio": 0.15,
  "min_chars_per_result": 200,
  "min_success_ratio": 0.7
}
```

Gate logic runs post-execution on aggregated results. Only tasks with `sucesso=true` count.

## Scaling Limits

| Resource | Limit | Reason |
|----------|-------|--------|
| Max machines | 5 (cpu1-cpu5) | Colab free tier typical limit |
| Max tasks/machine | 2 (tarefa1, tarefa2) | SQLite contention, context window |
| Max total tasks | 10 | 5 machines × 2 tasks |
| Max plan chars/task | 40 min | Ensures actionable prompts |
| Planner retries | 2 | Balances quality vs time |

## Security Boundaries

- **No API keys in skill bundle** → Injected via env at runtime
- **No private URLs/paths** → Redacted by `fleet_public_safety.py`
- **Colab session IDs** → Redacted in logs
- **Gateway auth=none** → Only loopback bind; no external exposure
- **Human confirmation required** → No auto-launch without approval