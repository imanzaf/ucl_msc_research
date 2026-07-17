"""Tests for current scenario-generation Pydantic models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.data_models.scenarios import (
    FactEvaluationRole,
    GeneratedScenarioInstance,
    PromptCondition,
    ScenarioFamily,
    ScenarioSeed,
    ScenarioSeedCollection,
)
from tests.scenario_fixtures import (
    SEED_PATH,
    make_family,
    make_generated_instance,
    make_no_false_claim_assessment,
)


def test_seed_file_has_no_payload_schema_versions() -> None:
    """Verify scenario set versioning lives in the folder, not the seed payload."""
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    assert "schema_version" not in payload
    assert all("schema_version" not in seed for seed in payload["seeds"])
    assert ScenarioSeedCollection.model_validate(payload).seeds


def test_current_family_accepts_valid_generated_artifact() -> None:
    """Verify a valid current family can be constructed and round-tripped."""
    family = make_family()
    round_tripped = ScenarioFamily.model_validate(family.model_dump())

    assert len(round_tripped.scenario_instances) == 4
    assert "schema_version" not in round_tripped.model_dump()
    assert {variant.condition for variant in round_tripped.prompt_variants} == {
        PromptCondition.NEUTRAL,
        PromptCondition.PRODUCTION_BASELINE,
        PromptCondition.PRODUCTION_INTEGRITY,
    }


def test_generated_instance_excludes_code_owned_fields() -> None:
    """Verify LLM-facing scenario instances exclude seed-owned family fields."""
    for field_name in [
        "schema_version",
        "scenario_family_id",
        "segment",
        "interaction_mode",
        "tool_using",
        "agent_role",
        "agent_task",
        "task_guidance",
        "integrity_instructions",
        "user_role",
        "prompt_variants",
        "prompt_template",
        "scenario_id",
        "task_type_id",
        "replication_id",
        "user_goal",
        "core_initial_request",
        "core_risk_followup",
    ]:
        assert field_name not in GeneratedScenarioInstance.model_fields


def test_fact_units_require_current_role_distribution() -> None:
    """Verify generated scenario instances require the current fact-role counts."""
    data = make_generated_instance("case").model_dump()
    data["fact_units"][0]["evaluation_role"] = FactEvaluationRole.FAVORABLE_CONTROL.value

    with pytest.raises(ValidationError):
        GeneratedScenarioInstance.model_validate(data)


def test_seed_rejects_payload_schema_version() -> None:
    """Verify seed records reject schema-version fields."""
    seed_payload = ScenarioSeed.model_validate(
        json.loads(SEED_PATH.read_text(encoding="utf-8"))["seeds"][0]
    ).model_dump()
    seed_payload["schema_version"] = "legacy_seed_schema"

    with pytest.raises(ValidationError):
        ScenarioSeed.model_validate(seed_payload)


def test_false_claim_fixture_is_unversioned() -> None:
    """Verify scoring helper outputs do not carry schema-version metadata."""
    assessment = make_no_false_claim_assessment()

    assert "schema_version" not in assessment.model_dump()
