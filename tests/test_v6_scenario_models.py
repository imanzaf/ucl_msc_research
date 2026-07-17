"""Tests for deterministic V6 family-level design constraints."""

from __future__ import annotations

import pytest

from src.data_models.scenarios import InteractionMode, RiskCategory
from src.data_models.scenarios_v6 import ScenarioFamilyV6
from tests.v6_scenario_fixtures import make_v6_family


def test_v6_family_requires_scripted_multi_turn_protocol() -> None:
    """Verify V6 cannot be instantiated as a single-turn family."""
    payload = make_v6_family().model_dump()
    payload["interaction_mode"] = InteractionMode.SINGLE_TURN

    with pytest.raises(ValueError, match="scripted multi-turn"):
        ScenarioFamilyV6.model_validate(payload)


def test_v6_task_replications_require_matching_risk_category_structure() -> None:
    """Verify paired replications cannot silently change their risk-category composition."""
    payload = make_v6_family().model_dump()
    payload["scenario_instances"][1]["fact_units"][0]["risk_category"] = RiskCategory.CREDIT

    with pytest.raises(ValueError, match="risk-category structure"):
        ScenarioFamilyV6.model_validate(payload)
