"""Test hash-linked researcher acceptance and atomic accepted-bundle publication."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import pytest

from src.cli.commands.scenarios import build_manifest as build_manifest_command
from src.cli.commands.scenarios import publish as publish_command
from src.cli.commands.scenarios.publish import validate_candidate_seed_ownership
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import AcceptedScenarioManifest, ScenarioManifestScope
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ResearcherFactReview,
    ResearcherScenarioReview,
    ReviewDecision,
    ScenarioAcceptanceRecord,
    ScenarioReviewHistory,
)
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioHiddenDesign, ScenarioUseCaseSeed
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario, validate_accepted_bundle
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json
from tests.factories import ZERO_HASH, make_candidate_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_fact_reviews(candidate: CandidateScenario) -> list[ResearcherFactReview]:
    """Copy candidate facts and generated markers into researcher review records."""
    return [
        ResearcherFactReview(
            fact_id=fact.fact_id,
            fact_text=fact.canonical_proposition,
            specificity_markers=[element.canonical_value for element in candidate.specificity_elements if element.fact_id == fact.fact_id],
        )
        for fact in candidate.material_facts
    ]


def make_acceptance_bundle(
    scenario_id: str,
) -> Tuple[AcceptedScenario, ScenarioReviewHistory, ScenarioAcceptanceRecord]:
    """Build one complete accepted bundle for final-set publication tests."""
    candidate = make_candidate_scenario(scenario_id)
    accepted_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    automated = AutomatedScenarioReview(
        schema_version="3.1.0",
        scenario_id=scenario_id,
        review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
        decision=ReviewDecision.ACCEPT,
        findings=[],
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewer_model_id="reviewer/scenario-quality",
        reviewer_prompt_sha256=ZERO_HASH,
        reviewed_at=accepted_at,
    )
    researcher = ResearcherScenarioReview(
        schema_version="3.3.0",
        review_id=f"{scenario_id}_REVIEW_ACCEPT",
        anonymised_item_id=f"ITEM_{scenario_id}",
        scenario_id=scenario_id,
        decision=ReviewDecision.ACCEPT,
        fact_reviews=make_fact_reviews(candidate),
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=accepted_at,
        researcher_id="researcher",
    )
    history = ScenarioReviewHistory(
        schema_version="3.3.0",
        scenario_id=scenario_id,
        automated_reviews=[automated],
        revisions=[],
        researcher_reviews=[researcher],
    )
    acceptance_record, accepted = build_accepted_scenario(
        candidate,
        history,
        accepted_at=accepted_at,
        accepted_by="researcher",
    )
    return accepted, history, acceptance_record


def test_acceptance_requires_one_researcher_review_and_publishes_complete_atomic_bundle(tmp_path: Path) -> None:
    """Build and reload the acyclic three-file bundle after one researcher review passes."""
    candidate = make_candidate_scenario()
    automated = [
        AutomatedScenarioReview(
            schema_version="3.1.0",
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
    fact_reviews = make_fact_reviews(candidate)
    fact_reviews[0] = fact_reviews[0].model_copy(
        update={
            "fact_text": fact_reviews[0].fact_text.replace("£120", "£125"),
            "specificity_markers": ["£125"],
            "notes": "Corrected the generated amount.",
        }
    )
    initial = ResearcherScenarioReview(
        schema_version="3.3.0",
        review_id="SCENARIO_INITIAL_ACCEPT",
        anonymised_item_id="S-001",
        scenario_id=candidate.scenario_id,
        decision=ReviewDecision.ACCEPT,
        pair_diagnostics=build_pair_diagnostics(candidate),
        fact_reviews=fact_reviews,
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=initial_at,
        researcher_id="researcher",
    )
    history = ScenarioReviewHistory(
        schema_version="3.3.0",
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
    assert "£125" in accepted.material_facts[0].canonical_proposition
    assert accepted.specificity_elements[0].canonical_value == "£125"
    publish_accepted_scenario(accepted, history, acceptance_record, tmp_path)
    scenario_root = tmp_path / candidate.scenario_id
    assert sorted(path.name for path in scenario_root.iterdir()) == [
        "acceptance_record.json",
        "accepted_scenario.json",
        "review_history.json",
    ]
    reloaded_history = read_model_json(scenario_root / "review_history.json", ScenarioReviewHistory)
    validate_accepted_bundle(accepted, reloaded_history, acceptance_record)


def test_publish_stages_bundles_and_calibration_manifest_as_one_final_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish ten staged C1 bundles and their self-hashed manifest together."""
    input_root = tmp_path / "v2.0.0"
    accepted_root = input_root / "accepted"
    source_seed_root = REPO_ROOT / "data/inputs/scenarios/v2.0.0"
    input_root.mkdir(parents=True)
    for filename in [
        "scenario_generation_seeds.json",
        "scenario_generation_seed_schema.json",
        "scenario_customer_queries.json",
        "scenario_customer_queries_schema.json",
    ]:
        shutil.copy2(source_seed_root / filename, input_root / filename)
    monkeypatch.setattr(publish_command, "ACTIVE_SCENARIO_INPUT_ROOT", input_root)
    monkeypatch.setattr(publish_command, "ACTIVE_SCENARIO_ACCEPTED_ROOT", accepted_root)
    monkeypatch.setattr(build_manifest_command, "ACTIVE_SCENARIO_INPUT_ROOT", input_root)
    bundles = [make_acceptance_bundle(f"CF{index:03d}_C1") for index in range(1, 11)]
    staging_root = input_root / ".scenario-publish.test"
    staging_root.mkdir()
    published_at = datetime(2026, 7, 1, tzinfo=timezone.utc)

    staged_manifest = publish_command._stage_final_set(
        staging_root=staging_root,
        bundles=bundles,
        scope=ScenarioManifestScope.CALIBRATION,
        published_at=published_at,
        published_by="researcher",
    )
    manifest_output = build_manifest_command.accepted_manifest_output_path(ScenarioManifestScope.CALIBRATION)
    publish_command._promote_final_set(staging_root, staged_manifest, bundles, manifest_output)

    manifest = read_model_json(manifest_output, AcceptedScenarioManifest)
    validate_model_self_hash(manifest, "manifest_sha256")
    assert len(manifest.entries) == 10
    assert {path.name for path in accepted_root.iterdir()} == {f"CF{index:03d}_C1" for index in range(1, 11)}


def test_candidate_publication_requires_exact_seed_owned_metadata() -> None:
    """Reject a hash-valid reviewed candidate whose researcher-owned task fields drift."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v2.0.0"
    seed = load_and_validate_seed(
        seed_root / "scenario_generation_seeds.json",
        seed_root / "scenario_generation_seed_schema.json",
        seed_root / "scenario_customer_queries.json",
        seed_root / "scenario_customer_queries_schema.json",
    )
    use_case = seed.use_cases[0]
    assert isinstance(use_case, ScenarioUseCaseSeed)
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_R1")
    candidate = make_candidate_scenario("CF001_R1")
    payload = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    payload.update(
        {
            "deployment_context": use_case.deployment_context.model_dump(mode="json"),
            "customer_messages": replication.customer_messages.model_dump(mode="json"),
            "hidden_design": ScenarioHiddenDesign(
                decision_type=replication.decision_type,
                options=replication.options,
                owner_supporting_option=replication.owner_supporting_option,
                owner_benefit_mechanism=replication.owner_benefit_mechanism,
                presentation_order=replication.presentation_order,
            ).model_dump(mode="json"),
        }
    )
    seed_bound = CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})
    validate_candidate_seed_ownership(seed_bound, seed)
    tampered_payload = seed_bound.model_dump(mode="json", exclude={"candidate_sha256"})
    tampered_payload["deployment_context"]["task"] = "promote the provider option"
    tampered = CandidateScenario.model_validate({**tampered_payload, "candidate_sha256": artifact_sha256(tampered_payload)})
    with pytest.raises(ValueError, match="seed-owned metadata"):
        validate_candidate_seed_ownership(tampered, seed)
