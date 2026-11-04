# Colab Agent Fleet

**Distributed web research fleet: GPU planner + CPU execution lane on Google Colab.**

## Overview

Colab Agent Fleet orchestrates a **two-lane architecture** for parallel web research:

```
┌─────────────────────────────────────────────────────────────┐
│  PLANNER (cpu6, GPU)                                        │
│  - Local Ollama (gpt-oss:20b)                               │
│  - Freezes plan, validates structure, distributes tasks     │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │  cpu1   │         │  cpu2   │         │  cpu3   │  ...
   │ OpenClaw│         │ OpenClaw│         │ OpenClaw│
   │+web_search        │+web_search       │+web_search
   └────┬────┘         └────┬────┘         └────┬────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  Results JSONL  │
                   │  + Gates + MD   │
                   └─────────────────┘
```

## Features

- **Planning lane** (GPU): Local LLM via Ollama — free, private, no API keys
- **Execution lane** (CPU fleet): 5 Colab runtimes with OpenClaw + web_search plugin
- **Human-in-the-loop**: TUI dashboard shows plan → user confirms → fleet launches
- **Promotion gates**: Success ratio, unique sources, dedup, content depth
- **Reproducible**: Fleet plan JSON, context capture, redacted outputs
- **OpenClaw skill**: Installable via `openclaw skills install`

## Quick Start

### 1. Install as OpenClaw Skill

```bash
mkdir -p "$CODEX_HOME/skills"
git clone https://github.com/seu-usuario/colab-agent-fleet.git
rsync -a colab-agent-fleet/skill/colab-agent-fleet/ "$CODEX_HOME/skills/colab-agent-fleet/"
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your keys:
# NVIDIA_API_KEY=nvapi-xxx
# MODELO_PLANEJADOR=gpt-oss:20b
# MAQUINAS=cpu1,cpu2,cpu3,cpu4,cpu5
```

### 3. Create Colab Sessions

```bash
# CPU fleet (5 sessions)
for m in cpu1 cpu2 cpu3 cpu4 cpu5; do colab new -s $m; done

# GPU planner (1 session)
colab new -s cpu6 --gpu t4
```

### 4. Run Research

**Interactive (TUI Dashboard):**
```bash
python3 -m colab_agent_fleet.dashboard
# Enter request → review plan → type "continuar" → watch fleet run
```

**Headless (CI/Automation):**
```bash
# Generate plan
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "pesquise 5 plugins de navegação para OpenClaw"

# Validate plan
python3 -m colab_agent_fleet.scripts.validate_fleet_plan.py \
  --plan /tmp/plan.json \
  --request "pesquise 5 plugins de navegação para OpenClaw"

# Execute fleet
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm

# Render report
python3 -m colab_agent_fleet.scripts.render_fleet_summary.py \
  --results /tmp/run.jsonl \
  --gates /tmp/run_gates.json \
  --request "pesquise 5 plugins de navegação para OpenClaw" \
  --out /tmp/report.md
```

## Requirements

- Python 3.11+
- `colab` CLI authenticated (`pip install colab-cli && colab login`)
- NVIDIA API key for Nemotron (get at https://integrate.api.nvidia.com)
- Ollama with `gpt-oss:20b` on cpu6 (or change `MODELO_PLANEJADOR`)

## Project Structure

```
.
├── skill/colab-agent-fleet/          # OpenClaw skill
│   ├── SKILL.md                      # Skill manifest
│   ├── agents/openai.yaml            # Agent config (Nemotron + web_search)
│   ├── scripts/                      # Executable scripts
│   │   ├── init_fleet_plan.py        # NL → validated fleet plan
│   │   ├── run_fleet.py              # Execute plan on Colab fleet
│   │   ├── validate_fleet_plan.py    # Standalone validator
│   │   ├── render_fleet_summary.py   # JSONL → markdown report
│   │   ├── capture_fleet_context.py  # Reproducibility context
│   │   └── fleet_public_safety.py    # Redaction helpers
│   └── references/                   # Deep-dive docs
│       ├── fleet-architecture.md
│       ├── plan-spec.md
│       ├── colab-operations.md
│       ├── openclaw-integration.md
│       ├── promotion-gates.md
│       ├── dashboard-tui.md
│       └── public-safety.md
├── docs/codex/                       # Codex agent guidance
├── tests/                            # Unit + integration tests
├── dashboard.py                      # TUI orchestrator (root)
├── stop_all.py                       # Cleanup all Colab sessions
├── pyproject.toml                    # Package config
└── .env.example                      # Environment template
```

## Documentation

| Doc | Description |
|-----|-------------|
| `skill/colab-agent-fleet/references/fleet-architecture.md` | Architecture, failure modes, data flow |
| `skill/colab-agent-fleet/references/plan-spec.md` | Fleet plan JSON schema, distribution rules |
| `skill/colab-agent-fleet/references/promotion-gates.md` | Gate logic, customization, CI |
| `skill/colab-agent-fleet/references/public-safety.md` | Redaction, leak prevention |
| `docs/codex/overview.md` | Codex quick start, key files |
| `docs/codex/architecture.md` | Design decisions, trade-offs |
| `docs/codex/workflow.md` | Standard workflow, commands, troubleshooting |

## License

Apache-2.0 — see `LICENSE` for details.

## Security

See `SECURITY.md` for vulnerability reporting and security practices.