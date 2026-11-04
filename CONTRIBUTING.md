# Contributing

## Development Setup

```bash
# Clone
git clone https://github.com/seu-usuario/colab-agent-fleet.git
cd colab-agent-fleet

# Install deps
pip install -e ".[dev]"
# or: pip install textual colab-cli duckduckgo-search python-dotenv pytest

# Install plugin (for local testing)
cd skill/colab-agent-fleet/scripts
# Plugin builds in Colab; local build optional

# Run tests
python3 -m pytest tests/ -q
```

## Code Style

- Python 3.11+
- Type hints on all public functions
- `black` formatting (line length 100)
- `ruff` linting
- Docstrings for all public modules/classes/functions

```bash
# Format
black skill/ tests/
ruff check --fix skill/ tests/
```

## Commit Messages

Follow Conventional Commits:
```
feat: add new promotion gate for content freshness
fix: handle SQLite lock in pipeline stagger
docs: update plan-spec.md with 10-task distribution
refactor: extract gateway health-check to helper
test: add unit tests for dedup logic
chore: update dependencies
```

## Pull Request Process

1. Fork & create branch: `git checkout -b feat/my-feature`
2. Make changes with tests
3. Run verification: `python3 -m py_compile skill/... && python3 -m pytest -q`
4. Run safety scan: `python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .`
5. Push & open PR with description of changes
6. CI must pass (syntax, tests, safety)

## Adding New Features

### New Promotion Gate
1. Edit `run_fleet.py`: add to `PROMOTION_GATES_DEFAULTS` + `aplicar_gates()`
2. Document in `references/promotion-gates.md`
3. Add test in `tests/test_gates.py`

### New Reference Doc
1. Create `references/new-topic.md`
2. Add to `SKILL.md` References section
3. Link from relevant scripts

### New Script
1. Create `scripts/new_script.py` with argparse + main()
2. Add to `SKILL.md` Bundled Scripts
3. Add unit test in `tests/`
4. Update `pyproject.toml` entry_points if CLI

## Testing

```bash
# All tests
pytest tests/ -q

# With coverage
pytest tests/ --cov=skill/colab-agent-fleet/scripts --cov-report=term-missing

# Skip integration
pytest tests/ -m "not integration" -q
```

## Documentation

- Update `docs/codex/` for Codex agent guidance
- Update `references/` for user-facing docs
- Keep `SKILL.md` in sync with script capabilities

## Releasing

1. Update version in `SKILL.md` and `pyproject.toml`
2. Tag: `git tag v0.1.1`
3. Push: `git push origin v0.1.1`
4. GitHub Actions builds and publishes to ClawHub (if configured)