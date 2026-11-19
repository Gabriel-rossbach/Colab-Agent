from skill.colab_agent_fleet.scripts.validate_fleet_plan import validar_plano_json


def test_prompt_nulo_retorna_erro_em_vez_de_excecao():
    valid, errors = validar_plano_json(
        {"tasks": [{"cpu": 1, "task": 1, "prompt": None}]},
        "teste",
    )
    assert not valid
    assert any("deve ser string" in error for error in errors)


def test_plano_nao_objeto_retorna_erro():
    valid, errors = validar_plano_json([], "teste")
    assert not valid
    assert "objeto JSON" in errors[0]


def test_booleano_nao_e_numero_de_cpu():
    valid, _ = validar_plano_json(
        {"tasks": [{"cpu": True, "task": 1, "prompt": "Use web_search para testar. Traga em português."}]},
        "teste",
    )
    assert not valid


def test_browser_desabilitado_rejeita_tarefa_de_browser():
    valid, errors = validar_plano_json(
        {"tasks": [{"cpu": 1, "task": 1, "prompt": "Use browser para preencher um formulário de teste com cuidado."}]},
        "teste",
        browser_enabled=False,
    )
    assert not valid
    assert any("browser está desabilitado" in error for error in errors)


def test_browser_desabilitado_nao_rejeita_web_search():
    valid, errors = validar_plano_json(
        {"tasks": [{"cpu": 1, "task": 1, "prompt": "Use web_search para pesquisar carros rápidos. Traga em português."}]},
        "pesquise carros rápidos",
        browser_enabled=False,
    )
    assert valid, errors
