"""Integração real, somente com opt-in explícito e infraestrutura configurada.

Execute deliberadamente com ``FLEET_RUN_INTEGRATION=1`` e ``NVIDIA_API_KEY``.
A presença da chave, sozinha, nunca habilita estas chamadas externas.
"""

import os

import pytest


requires_integration = pytest.mark.skipif(
    os.getenv("FLEET_RUN_INTEGRATION") != "1",
    reason="integração desligada; defina FLEET_RUN_INTEGRATION=1 para opt-in",
)
requires_colab = pytest.mark.skipif(
    not os.getenv("NVIDIA_API_KEY"),
    reason="NVIDIA_API_KEY not set",
)
pytestmark = pytest.mark.integration


@requires_colab
@requires_integration
def test_init_fleet_plan_generates_valid_json():
    from skill.colab_agent_fleet.scripts.init_fleet_plan import gerar_plano

    plan = gerar_plano("pesquise 2 frameworks de teste Python", "gpt-oss:20b", max_tentativas=1)
    assert plan is not None
    assert "tasks" in plan
    assert len(plan["tasks"]) >= 1
    assert all("cpu" in t and "task" in t and "prompt" in t for t in plan["tasks"])


@requires_colab
@requires_integration
def test_validate_fleet_plan_accepts_generated():
    from skill.colab_agent_fleet.scripts.init_fleet_plan import gerar_plano
    from skill.colab_agent_fleet.scripts.validate_fleet_plan import validar_plano_json

    plan = gerar_plano("pesquise 3 linguagens de programação populares", "gpt-oss:20b", max_tentativas=1)
    assert plan is not None

    ok, erros = validar_plano_json(plan, plan["request"])
    assert ok, f"Generated plan failed validation: {erros}"


@requires_colab
@requires_integration
def test_run_fleet_dry_run():
    """Test run_fleet with --dry-run flag if implemented, or minimal plan."""
    pytest.skip("Full fleet run requires 2+ Colab sessions and takes 5+ min")