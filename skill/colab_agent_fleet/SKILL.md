---
name: colab-agent-fleet
description: Colab Agent Fleet is a public ClawHub skill for distributed web research across Colab CPU runtimes. Use it when the user says "colab fleet", "distributed research", "parallel web search", or wants coordinated multi-machine agents with a planning lane (GPU) and execution lane (CPU fleet).
version: 0.1.0
homepage: https://github.com/seu-usuario/colab-agent-fleet
user-invocable: true
metadata: {"openclaw":{"homepage":"https://github.com/seu-usuario/colab-agent-fleet","skillKey":"colab-agent-fleet","requires":{"anyBins":["python3","colab"]}}}
---

# Colab Agent Fleet

Search intent: `colab fleet`, `distributed research`, `parallel web search`, `multi-machine agent orchestration`

## Goal

Turn a research question into a coordinated multi-machine campaign:

- **Planning lane (GPU)**: Local LLM (Ollama/gpt-oss) freezes the plan, validates structure, distributes tasks
- **Execution lane (CPU fleet)**: 5 Colab runtimes run OpenClaw agents with web_search tool in parallel
- **Evidence capture**: Each task returns structured results (URLs, titles, snippets) with dedup and quality gates
- **Human-in-the-loop**: Dashboard shows plan → user confirms → fleet launches → results aggregated

This skill is the **orchestration layer**. Pair with your own search/analysis skills for domain-specific work.

## Use This Skill When

- the user wants parallel web research across multiple IPs (Colab gives 5+ clean IPs)
- the task needs a planner that outputs structured, validated task distributions
- the workflow includes OpenClaw agents with web_search tool on Colab
- you need a TUI dashboard to monitor fleet status and approve launches
- the user wants reproducible research campaigns with promotion gates

If the primary goal is single-machine deep research, use a simpler agent loop instead.

## Quick Start

1. **Install the skill** (from ClawHub or local):
   ```bash
   mkdir -p "$CODEX_HOME/skills"
   rsync -a skill/colab-agent-fleet/ "$CODEX_HOME/skills/colab-agent-fleet/"
   ```

2. **Configure environment** (`.env` in project root):
   ```bash
   NVIDIA_API_KEY=nvapi-xxx          # for Nemotron on execution lane
   MAQUINAS=cpu1,cpu2,cpu3,cpu4,cpu5 # target Colab sessions
   MODELO_PLANEJADOR=gpt-oss:20b     # Ollama model on cpu6 (GPU)
   ```

3. **Launch the dashboard** (human-in-the-loop):
   ```bash
   python3 -m colab_agent_fleet.dashboard
   # or run the orchestrator directly:
   python3 -m colab_agent_fleet.orchestrator "pesquise 5 plugins de navegação para OpenClaw"
   ```

4. **Or use the scripts directly** for CI/automation:
   ```bash
   # Generate a validated plan
   python3 {baseDir}/scripts/init_fleet_plan.py \
     --out /tmp/fleet-plan.json \
     --request "pesquise 5 plugins de navegação para OpenClaw"

   # Execute the plan (requires Colab CLI authenticated)
   python3 {baseDir}/scripts/run_fleet.py \
     --plan /tmp/fleet-plan.json \
     --auto-confirm
   ```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR (local)                                       │
│  - Receives natural language request                        │
│  - Calls Planner (cpu6/GPU) → validated fleet plan          │
│  - Shows plan in TUI → user confirms                        │
│  - Launches fleet in parallel via colab ssh                 │
│  - Aggregates results, applies promotion gates              │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐         ┌─────────┐         ┌─────────┐
   │ cpu1    │         │ cpu2    │         │ cpu3    │  ...
   │ OpenClaw│         │ OpenClaw│         │ OpenClaw│
   │+web_search        │+web_search       │+web_search
   └────┬────┘         └────┬────┘         └────┬────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  Results JSONL  │
                   │  + Promotion    │
                   └─────────────────┘
```

## Operating Rules

### Planning Rules

- One request → one **fleet plan** (validated JSON)
- Planner (GPU lane) outputs ONLY tasks in format: `[cpuN] [tarefaK] prompt`
- Each machine max 2 tasks (tarefa1, tarefa2); machines used in order (cpu1, cpu2...)
- Simple requests (2-4 tasks): 2 machines, split tasks. 5+ tasks: minimum machines, 2 per machine
- No invented names, no extra angles (security, navigation, etc.) unless user asked
- Plan must pass `validar_plano()` before any machine starts

### Execution Rules

- Each CPU machine runs identical setup: OpenClaw + NVIDIA NIMs + web_search plugin
- Agents run via `openclaw agent exec` with `--local-model-lean` for speed
- Gateway started with `--auth none --bind loopback` for local tool access
- Results captured as JSONL; each task returns structured evidence
- SQLite lock issues mitigated by spacing launches (pipeline: 60s stagger)

### Evidence & Promotion Rules

- Every task must return: query, results[title, url, snippet], timestamp, machine
- Dedup across fleet: URL + title similarity > 0.9 = duplicate
- Promotion gates (configurable):
  - `min_unique_sources`: minimum distinct domains (default 3)
  - `max_dup_ratio`: max fraction of duplicates (default 0.15)
  - `min_chars_per_result`: minimum content per result (default 200)
- Results only promoted if gates pass; otherwise flagged for review

### Public Distribution Rules

- Use `{baseDir}` when pointing at bundled scripts/references
- Keep secrets, tokens, private URLs, Colab session IDs out of skill bundle
- Private specializations (custom prompts, internal targets) → local override skill
- All scripts must pass `python3 -m py_compile` and `pytest -q`

## References

Read only the reference that matches the task:

- `references/fleet-architecture.md`
  - Full architecture, lane separation, failure modes
- `references/plan-spec.md`
  - Fleet plan JSON schema, validation rules, distribution algorithm
- `references/colab-operations.md`
  - Colab CLI patterns, session management, GPU/CPU shapes, SSH quirks
- `references/openclaw-integration.md`
  - OpenClaw plugin setup, gateway config, agent exec modes, tool registration
- `references/promotion-gates.md`
  - Evidence quality gates, dedup logic, promotion bundle format
- `references/dashboard-tui.md`
  - Textual TUI patterns, log streaming, confirmation flows, maximizable logs
- `references/public-safety.md`
  - Publication checklist for OpenClaw/ClawHub, leak prevention

## Bundled Scripts

- `scripts/init_fleet_plan.py`
  - Generate a validated fleet plan JSON from natural language request
  - Uses local Ollama (gpt-oss) or OpenAI-compatible endpoint for planning
  - Outputs plan with tasks distributed per rules; exits non-zero if invalid
- `scripts/run_fleet.py`
  - Execute a validated fleet plan across Colab machines
  - Handles pipeline stagger, gateway health-check, result aggregation
  - Applies promotion gates; writes results JSONL + markdown summary
- `scripts/validate_fleet_plan.py`
  - Standalone validator for fleet plan JSON (used in CI)
  - Checks structure, distribution rules, prompt quality, no invented names
- `scripts/render_fleet_summary.py`
  - Render markdown summary from results JSONL with public redaction
  - Shows per-machine stats, gate pass/fail, top sources
- `scripts/capture_fleet_context.py`
  - Capture git state, env (redacted), Colab session status, OpenClaw version
  - Run before launch for reproducibility record
- `scripts/fleet_public_safety.py`
  - Pure local helpers for path, URL, env, command redaction
  - No network I/O; used by other scripts for safe public output

## Agents

- `agents/openai.yaml` — OpenClaw agent config for execution lane (Nemotron + web_search)