"""Test local single-pass review, pair diagnostics, and atomic persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Tuple

import pytest
from pydantic import ValidationError

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ResearcherScenarioReview, ReviewDecision, ReviewPass, ScenarioReviewLabels
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioStage
from src.data_models.scoring import ConditionBlindScoringInput, ResponseSpan
from src.experiments.scoring_pipeline import build_condition_blind_input
from src.review_app import SCENARIO_REVIEW_LABELS, ReviewStore, build_researcher_scenario_review, build_specificity_elements
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.storage import write_model_json_atomic
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario, make_scoring_results, make_transcript


def all_pass_labels() -> ScenarioReviewLabels:
    """Return a complete passing scenario-review checklist."""
    return ScenarioReviewLabels(**{field_name: True for field_name in ScenarioReviewLabels.model_fields})


def specificity_by_fact(candidate: CandidateScenario) -> dict[str, list[str]]:
    """Select one exact phrase from every candidate material fact."""
    return {fact.fact_id: ["£120" if fact.polarity.value == "benefit" else "12-months"] for fact in candidate.material_facts}


def make_store(tmp_path: Path) -> Tuple[ReviewStore, AcceptedScenario, ConditionBlindScoringInput]:
    """Create candidate and blinded-input files in a temporary local store."""
    accepted = make_accepted_scenario()
    candidate = make_candidate_scenario()
    transcript = make_transcript(accepted)
    scoring_input = build_condition_blind_input(transcript, accepted, fact_order_seed=7)
    write_model_json_atomic(tmp_path / "candidates" / candidate.scenario_id / "candidate.json", candidate)
    write_model_json_atomic(tmp_path / "scoring_inputs" / f"{scoring_input.blind_conversation_id}.json", scoring_input)
    return ReviewStore(tmp_path / "candidates", tmp_path / "scoring_inputs", tmp_path / "records"), accepted, scoring_input


def make_annotation(accepted: AcceptedScenario, scoring_input: ConditionBlindScoringInput) -> ConversationAnnotation:
    """Build one schema-valid initial annotation."""
    transcript = make_transcript(accepted)
    fact_result, response_result, claim_result = make_scoring_results(accepted, transcript)
    return ConversationAnnotation(
        schema_version="2.0.0",
        annotation_id="ANNOTATION_INITIAL_1",
        anonymised_item_id="C-001",
        blind_conversation_id=scoring_input.blind_conversation_id,
        annotation_pass=ReviewPass.INITIAL,
        fact_judgments=fact_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id}).judgments,
        response_judgments=response_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id}).judgments,
        claim_judgments=claim_result.claims,
        scoring_input_sha256=artifact_sha256(scoring_input),
        rubric_sha256=ZERO_HASH,
        researcher_id="researcher",
        submitted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_scenario_review_requires_pair_diagnostics_and_rejects_a_duplicate(tmp_path: Path) -> None:
    """Persist both displayed pair diagnostics with the single scenario decision."""
    store, accepted, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    common = {
        "schema_version": "3.0.0",
        "review_id": "SCENARIO_INITIAL_1",
        "anonymised_item_id": "S-001",
        "scenario_id": accepted.scenario_id,
        "decision": ReviewDecision.ACCEPT,
        "labels": all_pass_labels(),
        "specificity_elements": accepted.specificity_elements,
        "reviewed_artifact_sha256": candidate.candidate_sha256,
        "reviewed_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "researcher_id": "researcher",
        "notes": "Single researcher review.",
    }
    with pytest.raises(ValidationError, match="both pair diagnostics"):
        ResearcherScenarioReview(**common)
    review = ResearcherScenarioReview(**common, pair_diagnostics=build_pair_diagnostics(candidate))
    store.save_scenario_review(review)
    with pytest.raises(ValueError, match="already exists"):
        store.save_scenario_review(review.model_copy(update={"review_id": "SCENARIO_INITIAL_2"}))
    assert store.scenario_reviews() == [review]


def test_point_and_click_scenario_submission_writes_schema_v3_review(tmp_path: Path) -> None:
    """Build and persist one complete scenario review without a reference response."""
    store, _, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    reviewed_at = datetime.now(timezone.utc)
    labels = {field_name: True for field_name in SCENARIO_REVIEW_LABELS}
    review = build_researcher_scenario_review(
        scenario=candidate,
        decision=ReviewDecision.ACCEPT,
        labels=labels,
        researcher_id=" iman ",
        notes=" Reviewed in the local checklist. ",
        reviewed_at=reviewed_at,
        specificity_by_fact=specificity_by_fact(candidate),
    )
    store.save_scenario_submission(review)

    assert review.schema_version == "3.0.0"
    assert review.researcher_id == "iman"
    assert review.notes == "Reviewed in the local checklist."
    assert set(review.labels.model_dump()) == set(ScenarioReviewLabels.model_fields)
    assert store.scenario_reviews() == [review]


def test_scenario_submission_persists_a_non_accept_decision_without_extra_artifacts(tmp_path: Path) -> None:
    """Persist a revise decision as the complete scenario-review record."""
    store, _, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    reviewed_at = datetime.now(timezone.utc)
    revised = build_researcher_scenario_review(
        candidate,
        ReviewDecision.REVISE,
        {field_name: False for field_name in SCENARIO_REVIEW_LABELS},
        "researcher",
        "Needs revision.",
        reviewed_at,
    )
    store.save_scenario_submission(revised)
    assert store.scenario_reviews() == [revised]


def test_scenario_form_labels_match_the_complete_typed_checklist() -> None:
    """Keep every researcher acceptance criterion exposed as a named checkbox."""
    assert set(SCENARIO_REVIEW_LABELS) == set(ScenarioReviewLabels.model_fields)


def test_specificity_markers_are_optional_per_fact() -> None:
    """Accept an empty or partial marker selection without inventing specificity."""
    candidate = make_candidate_scenario()
    assert build_specificity_elements(candidate, {}) == []
    first = candidate.material_facts[0]
    selected = build_specificity_elements(candidate, {first.fact_id: ["£120"]})
    assert len(selected) == 1
    assert selected[0].fact_id == first.fact_id


def test_conversation_annotation_is_single_pass_and_resumable(tmp_path: Path) -> None:
    """Persist one sampled annotation and reject a second annotation for the same item."""
    store, accepted, scoring_input = make_store(tmp_path)
    annotation = make_annotation(accepted, scoring_input)
    store.save_conversation_annotation(annotation)
    assert store.conversation_annotations() == [annotation]
    with pytest.raises(ValueError, match="already exists|duplicate"):
        store.save_conversation_annotation(annotation.model_copy(update={"annotation_id": "ANNOTATION_INITIAL_2"}))
    with pytest.raises(ValidationError, match="Input should be 'initial'"):
        ConversationAnnotation.model_validate({**annotation.model_dump(mode="json"), "annotation_pass": "repeat"})


def test_locked_evaluation_sample_contains_160_one_pass_items(tmp_path: Path) -> None:
    """Bind annotation to the exact evaluation sample without repeat fields."""
    store, accepted, scoring_input = make_store(tmp_path)
    conversation_ids = [scoring_input.blind_conversation_id, *[f"BLIND_{index:04d}" for index in range(1, 160)]]
    payload = {
        "schema_version": "2.0.0",
        "sample_id": "evaluation_annotation_sample_v2",
        "sample_stage": ScenarioStage.EVALUATION,
        "random_seed": 7,
        "conversation_ids": conversation_ids,
        "strata_summary": {"evaluation": 160},
        "selection_probabilities": {"evaluation": Decimal("1")},
        "scoring_execution_manifest_sha256": ZERO_HASH,
        "source_transcripts_sha256": ZERO_HASH,
        "frozen_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
    }
    sample = AnnotationSampleManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    sample_path = tmp_path / "sample.json"
    write_model_json_atomic(sample_path, sample)
    sampled_store = ReviewStore(
        tmp_path / "candidates",
        tmp_path / "scoring_inputs",
        tmp_path / "records",
        annotation_sample_manifest_path=sample_path,
    )
    sampled_store.save_conversation_annotation(make_annotation(accepted, scoring_input))
    assert len(sampled_store.conversation_annotations()) == 1


def test_invalid_review_forms_are_rejected_before_write(tmp_path: Path) -> None:
    """Reject accepted scenario records with a failing mandatory pair judgement."""
    store, accepted, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    labels = all_pass_labels().model_copy(update={"pair_matching_acceptable": False})
    with pytest.raises(ValidationError):
        ResearcherScenarioReview(
            schema_version="3.0.0",
            review_id="INVALID_1",
            anonymised_item_id="S-002",
            scenario_id=accepted.scenario_id,
            decision=ReviewDecision.ACCEPT,
            labels=labels,
            pair_diagnostics=build_pair_diagnostics(candidate),
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewed_at=datetime.now(timezone.utc),
            researcher_id="researcher",
            notes="",
        )
    assert not store.scenario_reviews_path.exists()


def test_annotation_rejects_an_invalid_framing_span_before_write(tmp_path: Path) -> None:
    """Validate framing evidence against the exact condition-blind response bytes."""
    store, accepted, scoring_input = make_store(tmp_path)
    annotation = make_annotation(accepted, scoring_input)
    bad_span = ResponseSpan(turn_index=1, start_char=0, end_char=1, exact_quote="X")
    first = annotation.fact_judgments[0].model_copy(update={"framing_spans": [bad_span]})
    invalid = annotation.model_copy(update={"fact_judgments": [first, *annotation.fact_judgments[1:]]})
    with pytest.raises(ValueError, match="exact blind-input response text"):
        store.save_conversation_annotation(invalid)
    assert not store.conversation_annotations_path.exists()


def test_annotation_rejects_an_invalid_disclaimer_washing_span_before_write(tmp_path: Path) -> None:
    """Validate disclaimer-washing evidence against the exact condition-blind response bytes."""
    store, accepted, scoring_input = make_store(tmp_path)
    annotation = make_annotation(accepted, scoring_input)
    bad_span = ResponseSpan(turn_index=1, start_char=0, end_char=1, exact_quote="X")
    first = annotation.response_judgments[0].model_copy(update={"disclaimer_washing_spans": [bad_span]})
    invalid = annotation.model_copy(update={"response_judgments": [first, *annotation.response_judgments[1:]]})
    with pytest.raises(ValueError, match="exact blind-input response text"):
        store.save_conversation_annotation(invalid)
    assert not store.conversation_annotations_path.exists()


def test_review_app_has_no_api_or_experiment_controls() -> None:
    """Keep the local review module free of provider and runner invocations."""
    source = (Path(__file__).resolve().parents[1] / "src/review_app.py").read_text(encoding="utf-8")
    assert "OpenRouter" not in source
    assert "complete_text" not in source
    assert "execute_run_plan" not in source
