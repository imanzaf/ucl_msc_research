"""Local review blinding, washout, atomic persistence, resume, and validation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Tuple

import pytest
from pydantic import ValidationError

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ResearcherScenarioReview, ReviewDecision, ReviewPass, ScenarioReviewLabels
from src.data_models.scenarios import AcceptedScenario, ScenarioStage
from src.data_models.scoring import ConditionBlindScoringInput
from src.experiments.scoring_pipeline import build_condition_blind_input
from src.review_app import ReviewStore
from src.storage import write_model_json_atomic
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario, make_scoring_results, make_transcript


def all_pass_labels() -> ScenarioReviewLabels:
    """Return a complete passing scenario-review checklist."""
    return ScenarioReviewLabels(**{field_name: True for field_name in ScenarioReviewLabels.model_fields})


def make_store(tmp_path: Path) -> Tuple[ReviewStore, AcceptedScenario, ConditionBlindScoringInput]:
    """Create accepted scenario and blinded input files in a temporary local store."""
    accepted = make_accepted_scenario()
    candidate = make_candidate_scenario()
    transcript = make_transcript(accepted)
    scoring_input = build_condition_blind_input(transcript, accepted, fact_order_seed=7)
    candidate_path = tmp_path / "candidates" / candidate.scenario_id / "candidate.json"
    scoring_path = tmp_path / "scoring_inputs" / f"{scoring_input.blind_conversation_id}.json"
    write_model_json_atomic(candidate_path, candidate)
    write_model_json_atomic(scoring_path, scoring_input)
    store = ReviewStore(tmp_path / "candidates", tmp_path / "scoring_inputs", tmp_path / "records")
    return store, accepted, scoring_input


def test_scenario_repeat_is_blocked_then_returns_no_prior_labels(tmp_path: Path) -> None:
    """Enforce fourteen days and expose only the accepted scenario on repeat."""
    store, accepted, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    initial_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    review = ResearcherScenarioReview(
        schema_version="1.0.0",
        review_id="SCENARIO_INITIAL_1",
        anonymised_item_id="S-001",
        scenario_id=accepted.scenario_id,
        review_pass=ReviewPass.INITIAL,
        decision=ReviewDecision.ACCEPT,
        labels=all_pass_labels(),
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=initial_time,
        researcher_id="researcher",
        notes="A prior note that must remain hidden.",
    )
    store.save_scenario_review(review)
    with pytest.raises(ValueError, match="14-day washout"):
        store.scenario_repeat_context(review.review_id, initial_time + timedelta(days=13))

    repeat_context = store.scenario_repeat_context(review.review_id, initial_time + timedelta(days=14))
    assert repeat_context.scenario_id == accepted.scenario_id
    assert not hasattr(repeat_context, "labels")
    assert store.eligible_scenario_repeats(initial_time + timedelta(days=14)) == [(accepted.scenario_id, review.review_id)]


def test_conversation_repeat_hides_prior_annotation_and_atomic_resume(tmp_path: Path) -> None:
    """Persist strict JSONL atomically and return only blind input after washout."""
    store, accepted, scoring_input = make_store(tmp_path)
    transcript = make_transcript(accepted)
    fact_result, response_result, claim_result = make_scoring_results(accepted, transcript)
    fact_result = fact_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})
    response_result = response_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})
    initial_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    annotation = ConversationAnnotation(
        schema_version="1.0.0",
        annotation_id="ANNOTATION_INITIAL_1",
        anonymised_item_id="C-001",
        blind_conversation_id=scoring_input.blind_conversation_id,
        annotation_pass=ReviewPass.INITIAL,
        fact_judgments=fact_result.judgments,
        response_judgments=response_result.judgments,
        claim_judgments=claim_result.claims,
        scoring_input_sha256=artifact_sha256(scoring_input),
        rubric_sha256=ZERO_HASH,
        researcher_id="researcher",
        submitted_at=initial_time,
    )
    store.save_conversation_annotation(annotation)
    assert len(store.conversation_annotations()) == 1
    context = store.conversation_repeat_context(annotation.annotation_id, initial_time + timedelta(days=14))
    assert context.blind_conversation_id != scoring_input.blind_conversation_id
    assert context.facts != scoring_input.facts
    assert not hasattr(context, "fact_judgments")
    with pytest.raises(ValueError, match="duplicate"):
        store.save_conversation_annotation(annotation)


def test_repeat_work_is_limited_to_the_frozen_evaluation_subsample(tmp_path: Path) -> None:
    """Permit a sampled initial annotation but reject repeats outside the frozen forty."""
    _, accepted, scoring_input = make_store(tmp_path)
    conversation_ids = [scoring_input.blind_conversation_id, *[f"BLIND_{index:04d}" for index in range(1, 160)]]
    repeat_ids = conversation_ids[1:41]
    sample_payload = {
        "schema_version": "1.0.0",
        "sample_id": "evaluation_annotation_sample_v1",
        "sample_stage": ScenarioStage.EVALUATION,
        "random_seed": 7,
        "conversation_ids": conversation_ids,
        "repeat_conversation_ids": repeat_ids,
        "strata_summary": {"evaluation": 160},
        "selection_probabilities": {"evaluation": Decimal("1")},
        "scoring_execution_manifest_sha256": ZERO_HASH,
        "source_transcripts_sha256": ZERO_HASH,
        "frozen_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
    }
    sample = AnnotationSampleManifest.model_validate({**sample_payload, "manifest_sha256": artifact_sha256(sample_payload)})
    sample_path = tmp_path / "sample.json"
    write_model_json_atomic(sample_path, sample)
    store = ReviewStore(
        tmp_path / "candidates",
        tmp_path / "scoring_inputs",
        tmp_path / "records",
        annotation_sample_manifest_path=sample_path,
    )
    transcript = make_transcript(accepted)
    fact_result, response_result, claim_result = make_scoring_results(accepted, transcript)
    initial_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    annotation = ConversationAnnotation(
        schema_version="1.0.0",
        annotation_id="ANNOTATION_SAMPLE_INITIAL_1",
        anonymised_item_id="C-SAMPLE-001",
        blind_conversation_id=scoring_input.blind_conversation_id,
        annotation_pass=ReviewPass.INITIAL,
        fact_judgments=fact_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id}).judgments,
        response_judgments=response_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id}).judgments,
        claim_judgments=claim_result.claims,
        scoring_input_sha256=artifact_sha256(scoring_input),
        rubric_sha256=ZERO_HASH,
        researcher_id="researcher",
        submitted_at=initial_time,
    )
    store.save_conversation_annotation(annotation)
    assert store.eligible_conversation_repeats(initial_time + timedelta(days=14)) == []
    with pytest.raises(ValueError, match="not selected"):
        store.conversation_repeat_context(annotation.annotation_id, initial_time + timedelta(days=14))


def test_invalid_review_forms_are_rejected_before_write(tmp_path: Path) -> None:
    """Reject unknown fields and accepted records with failing checklist labels."""
    store, accepted, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    labels = all_pass_labels().model_copy(update={"pair_matching_acceptable": False})
    with pytest.raises(ValidationError):
        ResearcherScenarioReview(
            schema_version="1.0.0",
            review_id="INVALID_1",
            anonymised_item_id="S-002",
            scenario_id=accepted.scenario_id,
            review_pass=ReviewPass.INITIAL,
            decision=ReviewDecision.ACCEPT,
            labels=labels,
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewed_at=datetime.now(timezone.utc),
            researcher_id="researcher",
            notes="",
            unexpected_field=True,
        )
    assert not store.scenario_reviews_path.exists()


def test_review_app_has_no_api_or_experiment_controls() -> None:
    """Keep the local review module free of provider and runner invocations."""
    source = (Path(__file__).resolve().parents[1] / "src/review_app.py").read_text(encoding="utf-8")
    assert "OpenRouter" not in source
    assert "complete_text" not in source
    assert "execute_run_plan" not in source
