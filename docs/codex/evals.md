# Evaluation & Testing

## Test Suite Structure

```
tests/
├── conftest.py              # pytest fixtures
├── test_fleet_plan.py       # Plan validation logic
├── test_gates.py            # Promotion gates logic
├── test_public_safety.py    # Redaction helpers
├── test_integration.py      # End-to-end (requires Colab)
└── fixtures/
    ├── valid_plan.json
    ├── invalid_plan_dupes.json
    └── invalid_plan_distribution.json
```

## Running Tests

```bash
# All tests
python3 -m pytest tests/ -q

# Specific module
python3 -m pytest tests/test_fleet_plan.py -v

# With coverage
python3 -m pytest tests/ --cov=skill/colab-agent-fleet/scripts --cov-report=term-missing

# Skip integration (requires Colab)
python3 -m pytest tests/ -m "not integration" -q
```

## Unit Test Examples

### test_fleet_plan.py
```python
import json
from skill.colab_agent_fleet.scripts.validate_fleet_plan import (
    validar_plano_json,
    etiquetas_esperadas,
)

VALID_PLAN = {
    "request": "pesquise 5 carros mais rápidos e 5 motos mais rápidas",
    "tasks": [
        {"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar os 5 carros mais rápidos. Traga em português."},
        {"cpu": 2, "task": 1, "prompt": "Use web_search para pesquisar as 5 motos mais rápidas. Traga em português."},
    ]
}

def test_valid_2_tasks():
    ok, erros = validar_plano_json(VALID_PLAN, VALID_PLAN["request"])
    assert ok, erros
    assert etiquetas_esperadas(2) == [(1, 1), (2, 1)]

def test_invalid_dupes():
    plan = {**VALID_PLAN, "tasks": VALID_PLAN["tasks"] * 2}
    ok, erros = validar_plano_json(plan, VALID_PLAN["request"])
    assert not ok
    assert any("repete exatamente" in e for e in erros)

def test_distribution_3_tasks():
    # 3 tasks → cpu1(1,2), cpu2(1)
    tasks = [
        {"cpu": 1, "task": 1, "prompt": "Use web_search para a."},
        {"cpu": 1, "task": 2, "prompt": "Use web_search para b."},
        {"cpu": 2, "task": 1, "prompt": "Use web_search para c."},
    ]
    ok, _ = validar_plano_json({"request": "x", "tasks": tasks}, "x")
    assert ok
```

### test_gates.py
```python
from skill.colab_agent_fleet.scripts.run_fleet import aplicar_gates, PROMOTION_GATES_DEFAULTS

def test_gate_pass():
    results = [{"sucesso": True}] * 7 + [{"sucesso": False}] * 3  # 70%
    gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
    assert gates["gate_pass"] is True
    assert gates["successful"] == 7

def test_gate_fail_low_success():
    results = [{"sucesso": True}] * 5 + [{"sucesso": False}] * 5  # 50%
    gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
    assert gates["gate_pass"] is False

def test_custom_gate():
    results = [{"sucesso": True}] * 9 + [{"sucesso": False}] * 1  # 90%
    custom = {"min_success_ratio": 0.95}
    gates = aplicar_gates(results, {**PROMOTION_GATES_DEFAULTS, **custom})
    assert gates["gate_pass"] is False
```

### test_public_safety.py
```python
from skill.colab_agent_fleet.scripts.fleet_public_safety import (
    redact_text, redact_command, sanitize_for_public, redact_env
)

def test_redact_nvidia_key():
    text = "export NVIDIA_API_KEY=nvapi-abc123def456ghi789"
    assert "nvapi-***REDACTED***" in redact_text(text)
    assert "abc123def456ghi789" not in redact_text(text)

def test_redact_colab_session():
    text = "session m-s-kkb-use1b2-b8jzjqfjmvfb ready"
    assert "m-s-***REDACTED***" in redact_text(text)

def test_redact_command():
    cmd = "echo 'nvapi-secret' | openclaw models auth paste-api-key --provider nvidia"
    assert "***REDACTED***" in redact_command(cmd)

def test_sanitize_dict():
    data = {"key": "nvapi-secret", "nested": {"token": "ghp_xxx"}}
    safe = sanitize_for_public(data)
    assert safe["key"] == "nvapi-***REDACTED***"
    assert safe["nested"]["token"] == "***REDACTED***"
```

## Integration Tests (Manual)

```bash
# Requires: Colab CLI authenticated, NVIDIA_API_KEY, active sessions
export NVIDIA_API_KEY=nvapi-xxx
colab new -s cpu1 && colab new -s cpu2  # etc.

# Full flow
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "pesquise 3 frameworks de teste Python"
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm
```

## Metrics to Track

| Metric | Target | Measurement |
|--------|--------|-------------|
| Plan validation pass rate | 100% | `validar_plano_json` on generated plans |
| Fleet success ratio | ≥ 70% | `gate_pass` in results |
| Unique sources per run | ≥ 3 | Promotion gate metric |
| Duplicate ratio | ≤ 15% | Promotion gate metric |
| Launch time (5 machines) | < 10 min | Wall clock from confirm to done |
| Planner latency | < 30s | Ollama response time |

## Regression Checklist (Before Release)

- [ ] `python3 -m py_compile skill/colab-agent-fleet/scripts/*.py`
- [ ] `python3 -m pytest tests/ -q` (all pass)
- [ ] `python3 skill/colab-agent-fleet/scripts/validate_fleet_plan.py --plan tests/fixtures/valid_plan.json --request "test"`
- [ ] `python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .` (no secrets)
- [ ] Manual fleet run with 2+ machines succeeds
- [ ] Dashboard TUI launches without error