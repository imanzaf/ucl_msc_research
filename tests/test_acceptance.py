"""Test hash-linked researcher acceptance and atomic accepted-bundle publication."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.cli.commands.scenarios.publish import validate_candidate_seed_ownership
from src.data_models.common import artifact_sha256
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ResearcherScenarioReview,
    ReviewDecision,
    ScenarioReviewHistory,
    ScenarioReviewLabels,
)
from src.data_models.scenarios import CandidateScenario, V09UseCaseSeed
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario, validate_accepted_bundle
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]


def _passing_labels() -> ScenarioReviewLabels:
    """Return the complete passing researcher checklist."""
    return ScenarioReviewLabels(**{name: True for name in ScenarioReviewLabels.model_fields})


def test_acceptance_requires_one_researcher_review_and_publishes_complete_atomic_bundle(tmp_path: Path) -> None:
    """Build and reload the acyclic three-file bundle after one researcher review passes."""
    candidate = make_candidate_scenario()
    automated = [
        AutomatedScenarioReview(
            schema_version="3.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=kind,
            decision=ReviewDecision.ACCEPT,
            findings=[],
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id=f"reviewer/{kind.value}",
            reviewer_prompt_sha256=ZERO_HASH,
            reviewed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        for kind in AutomatedReviewKind
    ]
    initial_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    specificity_elements = make_accepted_scenario().specificity_elements
    initial = ResearcherScenarioReview(
        schema_version="3.0.0",
        review_id="SCENARIO_INITIAL_ACCEPT",
        anonymised_item_id="S-001",
        scenario_id=candidate.scenario_id,
        decision=ReviewDecision.ACCEPT,
        labels=_passing_labels(),
        pair_diagnostics=build_pair_diagnostics(candidate),
        specificity_elements=specificity_elements,
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=initial_at,
        researcher_id="researcher",
        notes="Initial acceptance.",
    )
    history = ScenarioReviewHistory(
        schema_version="3.0.0",
        scenario_id=candidate.scenario_id,
        automated_reviews=automated,
        revisions=[],
        researcher_reviews=[initial],
    )
    acceptance_record, accepted = build_accepted_scenario(
        candidate,
        history,
        accepted_at=initial_at,
        accepted_by="researcher",
    )
    publish_accepted_scenario(accepted, history, acceptance_record, tmp_path)
    scenario_root = tmp_path / candidate.scenario_id
    assert sorted(path.name for path in scenario_root.iterdir()) == [
        "acceptance_record.json",
        "accepted_scenario.json",
        "review_history.json",
    ]
    reloaded_history = read_model_json(scenario_root / "review_history.json", ScenarioReviewHistory)
    validate_accepted_bundle(accepted, reloaded_history, acceptance_record)


def test_candidate_publication_requires_exact_seed_owned_metadata() -> None:
    """Reject a hash-valid reviewed candidate whose researcher-owned task fields drift."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.9.0"
    seed = load_and_validate_seed(
        seed_root / "scenario_generation_seeds.json",
        seed_root / "scenario_generation_seed_schema.json",
    )
    use_case = seed.use_cases[0]
    assert isinstance(use_case, V09UseCaseSeed)
    candidate = make_candidate_scenario("CF001_R1")
    payload = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    payload.update(
        {
            "deployment_context": use_case.deployment_context.model_dump(mode="json"),
            "customer_messages": use_case.customer_messages.model_dump(mode="json"),
            "hidden_design": use_case.hidden_design.model_dump(mode="json"),
        }
    )
    seed_bound = CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})
    validate_candidate_seed_ownership(seed_bound, seed)
    tampered_payload = seed_bound.model_dump(mode="json", exclude={"candidate_sha256"})
    tampered_payload["deployment_context"]["task"] = "promote the provider option"
    tampered = CandidateScenario.model_validate({**tampered_payload, "candidate_sha256": artifact_sha256(tampered_payload)})
    with pytest.raises(ValueError, match="seed-owned metadata"):
        validate_candidate_seed_ownership(tampered, seed)
