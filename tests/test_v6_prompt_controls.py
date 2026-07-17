"""Tests for current V0.3.1 prompt-control seed compilation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_v6_scenario_drafts import DEFAULT_SCENARIO_SET, load_v6_scenario_seeds
from src.data_models.prompt_controls import PromptControlProfileId, get_prompt_control_profile
from src.data_models.scenarios import PromptCondition
from src.data_models.scenarios_v6 import ScenarioFamilyV6, ScenarioSeedV6
from tests.v6_scenario_fixtures import load_test_v6_seed, make_v6_family

LEGACY_SEED_PATH = Path("data/inputs/scenarios/v0.3.0/scenario_generation_seeds.json")
CONTROLLED_SEED_PATH = Path("data/inputs/scenarios/v0.3.1/scenario_generation_seeds.json")


def test_v0_3_1_is_the_only_loadable_seed_protocol() -> None:
    """Verify archival seeds remain on disk but are rejected by the current generator."""
    controlled_seeds = load_v6_scenario_seeds(CONTROLLED_SEED_PATH)

    assert DEFAULT_SCENARIO_SET == "v0.3.1"
    assert LEGACY_SEED_PATH.exists()
    assert len(controlled_seeds) == 6
    assert all(isinstance(seed, ScenarioSeedV6) for seed in controlled_seeds)
    with pytest.raises(ValueError, match="current V6 generator requires"):
        load_v6_scenario_seeds(LEGACY_SEED_PATH)


def test_controlled_seed_compiles_isolated_prompt_conditions() -> None:
    """Verify prompt conditions differ only at their predeclared control boundary."""
    seed = load_test_v6_seed()
    family = make_v6_family(seed)
    profile = get_prompt_control_profile(PromptControlProfileId.OMISSION_INTEGRITY_V1)
    variants = {variant.condition: variant.system_prompt for variant in family.prompt_variants}
    neutral = variants[PromptCondition.NEUTRAL]
    baseline = variants[PromptCondition.PRODUCTION_BASELINE]
    integrity = variants[PromptCondition.PRODUCTION_INTEGRITY]
    expected_invariant = [
        *profile.invariant_core_instructions,
        *seed.invariant_task_constraints,
    ]

    assert neutral.guidance == expected_invariant
    assert baseline.guidance == [
        *expected_invariant,
        *profile.baseline_factuality_instructions,
    ]
    assert integrity.guidance == baseline.guidance
    assert neutral.integrity_instructions == baseline.integrity_instructions == []
    assert integrity.integrity_instructions == list(profile.integrity_completeness_instructions)
    assert neutral.agent_role == baseline.agent_role == integrity.agent_role
    assert neutral.agent_task == baseline.agent_task == integrity.agent_task


def test_every_v0_3_1_family_compiles_the_same_control_profile() -> None:
    """Verify every migrated family resolves the canonical controlled prompt structure."""
    seeds = load_v6_scenario_seeds(CONTROLLED_SEED_PATH)

    for seed in seeds:
        family = make_v6_family(seed)
        assert family.prompt_control_profile_id == PromptControlProfileId.OMISSION_INTEGRITY_V1
        assert family.invariant_task_constraints == seed.invariant_task_constraints
        assert len(family.prompt_variants) == 3


def test_controlled_seed_rejects_integrity_leakage_and_case_values() -> None:
    """Verify invariant seed constraints cannot contain treatment language or values."""
    payload = load_test_v6_seed().model_dump()
    payload["invariant_task_constraints"][0] = "Never omit a material downside."
    with pytest.raises(ValueError, match="integrity-treatment language"):
        ScenarioSeedV6.model_validate(payload)

    payload = load_test_v6_seed().model_dump()
    payload["invariant_task_constraints"][0] = "Apply the 30 day authority boundary."
    with pytest.raises(ValueError, match="case-specific values"):
        ScenarioSeedV6.model_validate(payload)

    payload = load_test_v6_seed().model_dump()
    payload["invariant_task_constraints"][0] = "Distinguish facts from inference."
    with pytest.raises(ValueError, match="baseline-factuality language"):
        ScenarioSeedV6.model_validate(payload)


def test_seed_models_reject_cross_version_schema_members() -> None:
    """Verify the current seed model rejects an archival schema member."""
    payload = load_test_v6_seed().model_dump()
    payload["schema_version"] = "scenario_seed.v6"

    with pytest.raises(ValueError, match="scenario_seed.v6.1"):
        ScenarioSeedV6.model_validate(payload)


def test_controlled_family_rejects_profile_drift() -> None:
    """Verify persisted families cannot alter canonical factuality or integrity blocks."""
    payload = make_v6_family(load_test_v6_seed()).model_dump()
    payload["task_guidance"][0] = "Use a different factuality control."
    for variant in payload["prompt_variants"]:
        if variant["condition"] != PromptCondition.NEUTRAL:
            variant["system_prompt"]["guidance"][-3] = payload["task_guidance"][0]

    with pytest.raises(ValueError, match="baseline guidance must match"):
        ScenarioFamilyV6.model_validate(payload)


def test_v0_3_1_seed_json_contains_no_free_prompt_treatment_blocks() -> None:
    """Verify controlled seeds reference the profile instead of duplicating prompt prose."""
    payload = CONTROLLED_SEED_PATH.read_text(encoding="utf-8")

    assert '"prompt_control_profile_id": "omission_integrity_v1"' in payload
    assert '"task_guidance"' not in payload
    assert '"integrity_instructions"' not in payload
