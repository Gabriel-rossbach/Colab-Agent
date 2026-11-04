import pytest
from skill.colab_agent_fleet.scripts.run_fleet import (
    aplicar_gates,
    PROMOTION_GATES_DEFAULTS,
)


def make_result(sucesso: bool, saida: str = "") -> dict:
    return {"sucesso": sucesso, "saida_bruta": saida, "timestamp": 1234567890.0}


def test_gate_pass_default():
    results = [make_result(True)] * 7 + [make_result(False)] * 3  # 70%
    gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
    assert gates["gate_pass"] is True
    assert gates["total_tasks"] == 10
    assert gates["successful"] == 7


def test_gate_fail_low_success():
    results = [make_result(True)] * 5 + [make_result(False)] * 5  # 50%
    gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
    assert gates["gate_pass"] is False
    assert gates["details"]["actual_ratio"] == 0.5


def test_gate_pass_custom_threshold():
    results = [make_result(True)] * 9 + [make_result(False)] * 1  # 90%
    custom = {"min_success_ratio": 0.95}
    gates = aplicar_gates(results, {**PROMOTION_GATES_DEFAULTS, **custom})
    assert gates["gate_pass"] is False
    assert gates["gates_config"]["min_success_ratio"] == 0.95


def test_gate_all_success():
    results = [make_result(True)] * 5
    gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
    assert gates["gate_pass"] is True
    assert gates["successful"] == 5


def test_gate_all_fail():
    results = [make_result(False)] * 5
    gates = aplicar_gates(results, PROMOTION_GATES_DEFAULTS)
    assert gates["gate_pass"] is False
    assert gates["successful"] == 0


def test_gate_empty_results():
    gates = aplicar_gates([], PROMOTION_GATES_DEFAULTS)
    assert gates["total_tasks"] == 0
    assert gates["successful"] == 0
    # 0 tasks = gate_pass False (can't promote nothing)
    assert gates["gate_pass"] is False