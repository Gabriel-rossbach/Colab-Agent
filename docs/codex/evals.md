# Avaliação e testes

## Estrutura da suite de testes

```
tests/
├── conftest.py              # fixtures do pytest
├── test_fleet_plan.py       # lógica de validação do plano
├── test_gates.py            # lógica dos promotion gates
├── test_public_safety.py    # helpers de redação (redaction)
├── test_integration.py      # end-to-end (exige Colab)
└── fixtures/
    ├── valid_plan.json
    ├── invalid_plan_dupes.json
    └── invalid_plan_distribution.json
```

## Rodando os testes

```bash
# Todos os testes
python3 -m pytest tests/ -q

# Módulo específico
python3 -m pytest tests/test_fleet_plan.py -v

# Com cobertura
python3 -m pytest tests/ --cov=skill/colab-agent-fleet/scripts --cov-report=term-missing

# Pulando integração (exige Colab)
python3 -m pytest tests/ -m "not integration" -q
```

## Exemplos de testes unitários

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
    # 3 tarefas → cpu1(1,2), cpu2(1)
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

## Testes de integração (manuais)

```bash
# Exige: CLI do Colab autenticada, NVIDIA_API_KEY, sessões ativas
export NVIDIA_API_KEY=nvapi-xxx
colab new -s cpu1 && colab new -s cpu2  # etc.

# Fluxo completo
python3 -m colab_agent_fleet.scripts.init_fleet_plan.py \
  --out /tmp/plan.json \
  --request "pesquise 3 frameworks de teste Python"
python3 -m colab_agent_fleet.scripts.run_fleet.py \
  --plan /tmp/plan.json \
  --out /tmp/run \
  --auto-confirm
```

## Métricas rastreadas

| Métrica | Alvo | Medição |
|---------|------|---------|
| Taxa de aprovação na validação do plano | 100% | `validar_plano_json` nos planos gerados |
| Taxa de sucesso da fleet | ≥ 70% | `gate_pass` nos resultados |
| Fontes únicas por run | ≥ 3 | Métrica do promotion gate |
| Taxa de duplicatas | ≤ 15% | Métrica do promotion gate |
| Tempo de lançamento (5 máquinas) | < 10 min | Tempo de parede da confirmação até o fim |
| Latência do planejador | < 30s | Tempo de resposta do Ollama |

## Checklist de regressão (antes do release)

- [ ] `python3 -m py_compile skill/colab-agent-fleet/scripts/*.py`
- [ ] `python3 -m pytest tests/ -q` (todos passam)
- [ ] `python3 skill/colab-agent-fleet/scripts/validate_fleet_plan.py --plan tests/fixtures/valid_plan.json --request "teste"`
- [ ] `python3 skill/colab-agent-fleet/scripts/fleet_public_safety.py --scan .` (sem segredos)
- [ ] Run manual da fleet com 2+ máquinas réussida
- [ ] Dashboard TUI abre sem erro
