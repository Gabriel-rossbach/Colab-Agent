# pytest fixtures for colab-agent-fleet tests
import pytest
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_plan():
    with open(FIXTURES_DIR / "valid_plan.json") as f:
        return json.load(f)


@pytest.fixture
def invalid_plan_dupes():
    with open(FIXTURES_DIR / "invalid_plan_dupes.json") as f:
        return json.load(f)


@pytest.fixture
def invalid_plan_distribution():
    with open(FIXTURES_DIR / "invalid_plan_distribution.json") as f:
        return json.load(f)