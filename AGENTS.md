# AGENTS.md

This repository packages the **colab-agent-fleet** OpenClaw skill. Use this file as the index for Codex agents.

## Operating Rules

- Restate the user goal and name the verification step before editing files.
- Keep diffs surgical. Do not refactor adjacent surfaces unless the task needs it.
- Preserve the split between skill code (`skill/colab-agent-fleet/`), docs (`docs/codex/`), and root orchestration (`dashboard.py`, `stop_all.py`).
- Treat public-surface review as part of the default loop. New docs, examples, manifests, and templates must clear leak, bleed, and evidence-discipline checks.
- Do not publish absolute local paths, browser profile names, private notebook URLs, secrets, customer identifiers, or unsupported claim language.
- Put durable repo knowledge in `docs/codex/`. Keep this file short.

## Repo Map

- **Skill**: `skill/colab-agent-fleet/` — OpenClaw skill (scripts, references, agents)
- **Orchestrator**: `dashboard.py` (TUI), `stop_all.py` (cleanup), `plano.py` (legacy planner)
- **Docs**: `docs/codex/` — Codex agent guidance (overview, architecture, workflow, evals, cleanup)
- **Tests**: `tests/` — Unit + integration tests
- **Config**: `pyproject.toml`, `.env.example`, `.gitignore`

## Default Verification

1. Run `python3 -m py_compile skill/colab-agent-fleet/scripts/*.py`
2. Run `python3 -m pytest tests/ -q`
3. Run `python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .`
4. If `codex_harness` available: `python3 -m codex_harness audit . --strict --min-score 90`
5. Review changed public files for secrets, private paths, private URLs, customer data, evidence drift.

## Project-Scoped Custom Agents

- `.codex/agents/architect.toml` — Architecture decisions, trade-offs
- `.codex/agents/implementer.toml` — Code implementation, bug fixes
- `.codex/agents/reviewer.toml` — Code review, safety, test coverage
- `.codex/agents/evolver.toml` — Prompt optimization, planner improvements
- `.codex/agents/cleanup.toml` — Dead code removal, dependency updates

## Key Skills for Agents

When working on this repo, agents should be familiar with:
- OpenClaw skill structure (`SKILL.md`, plugin SDK, agent configs)
- Colab CLI patterns (`colab-operations.md`)
- Fleet plan spec (`plan-spec.md`) — distribution algorithm, validation rules
- Promotion gates (`promotion-gates.md`) — quality criteria, customization
- Public safety (`public-safety.md`) — redaction, leak prevention