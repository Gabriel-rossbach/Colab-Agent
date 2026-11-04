# Colab Agent Fleet - Codex Overview

## What This Repo Does

**Colab Agent Fleet** orchestrates a **planning lane (GPU)** + **execution lane (CPU fleet)** for distributed web research:

1. **Planner** (cpu6, GPU): Local Ollama (gpt-oss:20b) takes natural language → outputs validated fleet plan
2. **Fleet** (cpu1-5, CPU): Each runs OpenClaw with web_search plugin → parallel web searches
3. **Gates** → Promotion criteria (success ratio, unique sources, dedup, content depth)
4. **Dashboard** → Human-in-the-loop TUI for plan approval and monitoring

## Quick Start for Codex

```bash
# 1. Install skill locally
mkdir -p "$CODEX_HOME/skills"
rsync -a skill/colab-agent-fleet/ "$CODEX_HOME/skills/colab-agent-fleet/"

# 2. Configure env
cp .env.example .env
# Edit .env with your NVIDIA_API_KEY

# 3. Run dashboard (TUI)
python3 -m colab_agent_fleet.dashboard

# Or run headless
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "pesquise 5 plugins de navegação para OpenClaw"
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm
```

## Default Verification (Run Before Commit)

```bash
# 1. Syntax check all scripts
python3 -m py_compile skill/colab-agent-fleet/scripts/*.py

# 2. Unit tests
python3 -m pytest tests/ -q

# 3. Public safety scan
python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .

# 4. Validate example plan
python3 skill/colab-agent-fleet/scripts/validate_fleet_plan.py \
  --plan tests/fixtures/valid_plan.json \
  --request "pesquise 5 carros mais rápidos e 5 motos mais rápidas"
```

## Key Files for Codex Agents

| File | Purpose |
|------|---------|
| `skill/colab-agent-fleet/SKILL.md` | Skill manifest, usage, rules, scripts list |
| `skill/colab-agent-fleet/scripts/init_fleet_plan.py` | Planner: NL → validated fleet plan JSON |
| `skill/colab-agent-fleet/scripts/run_fleet.py` | Executor: runs plan on Colab fleet |
| `skill/colab-agent-fleet/scripts/validate_fleet_plan.py` | Validator: standalone plan checker |
| `skill/colab-agent-fleet/scripts/render_fleet_summary.py` | Reporter: JSONL + gates → markdown |
| `skill/colab-agent-fleet/references/plan-spec.md` | Fleet plan JSON schema & distribution rules |
| `skill/colab-agent-fleet/references/fleet-architecture.md` | Architecture, failure modes, data flow |
| `skill/colab-agent-fleet/references/openclaw-integration.md` | OpenClaw plugin, gateway, agent config |
| `skill/colab-agent-fleet/references/promotion-gates.md` | Gate logic, customization, CI integration |

## Agent Roles (If Using Multi-Agent)

| Role | Prompt File | Responsibility |
|------|-------------|----------------|
| Architect | `.codex/agents/architect.toml` | Design changes, review architecture |
| Implementer | `.codex/agents/implementer.toml` | Write code, fix bugs |
| Reviewer | `.codex/agents/reviewer.toml` | Code review, safety, tests |
| Evolver | `.codex/agents/evolver.toml` | Improve prompts, optimize plans |
| Cleanup | `.codex/agents/cleanup.toml` | Remove dead code, update deps |

## Common Tasks for Codex

### Add New Promotion Gate
1. Edit `run_fleet.py` → `PROMOTION_GATES_DEFAULTS` + `aplicar_gates()`
2. Update `promotion-gates.md` with logic
3. Add test in `tests/test_gates.py`

### Change Planner Model
1. Edit `init_fleet_plan.py` → `MODELO_PLANEJADOR` default
2. Update `SKILL.md` Quick Start
3. Test with `gpt-oss:20b` and `llama3.1:8b`

### Add New Reference Doc
1. Create `references/new-topic.md`
2. Add to `SKILL.md` References section
3. Link from relevant scripts

### Modify Dashboard
1. Edit `dashboard.py` (in repo root, not skill)
2. Update `dashboard-tui.md`
3. Test with `python3 -m textual.testing` headless

## Gotchas for Codex

| Issue | Prevention |
|-------|------------|
| SQLite lock on parallel launch | Pipeline stagger (60s) in `run_fleet.py` |
| Gateway not ready | Health-check loop (30×2s) in deploy script |
| Plugin not loaded | Explicit install + `--accept-capabilities` |
| colab ssh 429 | Serialize SSH; don't parallelize same machine |
| Secrets in logs | Use `fleet_public_safety.py` on all outputs |
| Plan validation fails | Check `plan-spec.md` for distribution rules |