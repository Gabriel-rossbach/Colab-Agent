"""
Integration tests - require Colab CLI, active sessions, NVIDIA_API_KEY.
Marked as 'integration' to skip in normal CI.
Run with: pytest tests/test_integration.py -m integration
"""

import pytest
import os


# Skip if no Colab or no API key
requires_colab = pytest.mark.skipif(
    not os.getenv("NVIDIA_API_KEY"),
    reason="NVIDIA_API_KEY not set",
)
requires_integration = pytest.mark.integration


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