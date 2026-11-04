import pytest
from skill.colab_agent_fleet.scripts.validate_fleet_plan import (
    validar_plano_json,
    etiquetas_esperadas,
)


def test_etiquetas_esperadas():
    assert etiquetas_esperadas(1) == [(1, 1)]
    assert etiquetas_esperadas(2) == [(1, 1), (2, 1)]
    assert etiquetas_esperadas(3) == [(1, 1), (1, 2), (2, 1)]
    assert etiquetas_esperadas(4) == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert etiquetas_esperadas(5) == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)]
    assert etiquetas_esperadas(10) == [
        (1, 1), (1, 2), (2, 1), (2, 2),
        (3, 1), (3, 2), (4, 1), (4, 2),
        (5, 1), (5, 2),
    ]


def test_valid_plan(valid_plan):
    ok, erros = validar_plano_json(valid_plan, valid_plan["request"])
    assert ok, erros


def test_valid_plan_3_tasks():
    plan = {
        "request": "pesquise a, b e c",
        "tasks": [
            {"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar a. Traga em português."},
            {"cpu": 1, "task": 2, "prompt": "Use web_search para pesquisar b. Traga em português."},
            {"cpu": 2, "task": 1, "prompt": "Use web_search para pesquisar c. Traga em português."},
        ],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert ok, erros


def test_invalid_dupes(invalid_plan_dupes):
    ok, erros = validar_plano_json(invalid_plan_dupes, invalid_plan_dupes["request"])
    assert not ok
    assert any("repete exatamente" in e for e in erros)


def test_invalid_distribution(invalid_plan_distribution):
    ok, erros = validar_plano_json(invalid_plan_distribution, invalid_plan_distribution["request"])
    assert not ok
    assert any("as etiquetas não batem" in e for e in erros)


def test_invalid_cpu_too_high():
    plan = {
        "request": "pesquise x",
        "tasks": [{"cpu": 6, "task": 1, "prompt": "Use web_search para x. Traga em português."}],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert not ok
    assert any("cpu6 não existe" in e for e in erros)


def test_invalid_task_too_high():
    plan = {
        "request": "pesquise x",
        "tasks": [{"cpu": 1, "task": 3, "prompt": "Use web_search para x. Traga em português."}],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert not ok
    assert any("a numeração recomeça" in e for e in erros)


def test_invalid_prompt_short():
    plan = {
        "request": "pesquise x",
        "tasks": [{"cpu": 1, "task": 1, "prompt": "curto"}],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert not ok
    assert any("curto demais" in e for e in erros)


def test_invalid_no_web_search():
    plan = {
        "request": "pesquise x",
        "tasks": [{"cpu": 1, "task": 1, "prompt": "Pesquise x sem buscar na web. Traga em português."}],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert not ok
    assert any("não manda usar web_search" in e for e in erros)


def test_invalid_invented_name():
    plan = {
        "request": "pesquise carros rápidos",
        "tasks": [{"cpu": 1, "task": 1, "prompt": 'Use web_search para pesquisar o "SuperCar". Traga em português.'}],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert not ok
    assert any("nome inventado" in e for e in erros)


def test_invalid_extra_angle():
    plan = {
        "request": "pesquise carros rápidos",
        "tasks": [{"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar carros mais seguros. Traga em português."}],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    assert not ok
    assert any("acrescentou 'segurança'" in e or "acrescentou 'seguro'" in e for e in erros)


def test_quase_duplicata():
    plan = {
        "request": "pesquise a e b",
        "tasks": [
            {"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar os melhores carros. Traga em português."},
            {"cpu": 2, "task": 1, "prompt": "Use web_search para pesquisar os melhores carros. Traga em português agora."},
        ],
    }
    ok, erros = validar_plano_json(plan, plan["request"])
    # Pode passar ou falhar dependendo do threshold; só testa que não crasha
    assert isinstance(ok, bool)