"""Test local single-pass review, pair diagnostics, and atomic persistence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Tuple

import pytest
from pydantic import ValidationError

from src.cli.commands.review import launch as review_launch
from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ResearcherScenarioReview, ReviewDecision, ReviewPass
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioStage
from src.data_models.scoring import ConditionBlindScoringInput, ResponseSpan
from src.experiments.scoring_pipeline import build_condition_blind_input
from src.review_app import SCENARIO_REVIEW_GUIDANCE, ReviewStore, build_researcher_fact_reviews, build_researcher_scenario_review
from src.storage import write_model_json_atomic
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario, make_scoring_results, make_transcript


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


def test_scenario_review_persists_diagnostics_and_rejects_a_duplicate(tmp_path: Path) -> None:
    """Persist descriptive pair diagnostics with the single scenario decision."""
    store, _, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    review = build_researcher_scenario_review(
        scenario=candidate,
        decision=ReviewDecision.ACCEPT,
        researcher_id="researcher",
        reviewed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert len(review.pair_diagnostics) == 2
    store.save_scenario_review(review)
    with pytest.raises(ValueError, match="already exists"):
        store.save_scenario_review(review.model_copy(update={"review_id": "SCENARIO_INITIAL_2"}))
    assert store.scenario_reviews() == [review]


def test_point_and_click_scenario_submission_writes_schema_v33_review(tmp_path: Path) -> None:
    """Build and persist one complete scenario review without a reference response."""
    store, _, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    reviewed_at = datetime.now(timezone.utc)
    review = build_researcher_scenario_review(
        scenario=candidate,
        decision=ReviewDecision.ACCEPT,
        researcher_id=" iman ",
        reviewed_at=reviewed_at,
        specificity_by_fact=specificity_by_fact(candidate),
    )
    store.save_scenario_submission(review)

    assert review.schema_version == "3.3.0"
    assert review.researcher_id == "iman"
    assert len(review.fact_reviews) == 4
    assert [item.specificity_markers for item in review.fact_reviews] == list(specificity_by_fact(candidate).values())
    assert "labels" not in type(review).model_fields
    assert "revision_findings" not in type(review).model_fields
    assert store.scenario_reviews() == [review]


def test_scenario_submission_persists_a_non_accept_decision_without_extra_artifacts(tmp_path: Path) -> None:
    """Persist a revise decision as the complete scenario-review record."""
    store, _, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    reviewed_at = datetime.now(timezone.utc)
    first, _, third, _ = candidate.material_facts
    revised = build_researcher_scenario_review(
        scenario=candidate,
        decision=ReviewDecision.REVISE,
        researcher_id="researcher",
        reviewed_at=reviewed_at,
        notes_by_fact={
            first.fact_id: "State whether this amount is guaranteed.",
            third.fact_id: "Clarify which customer segment this applies to.",
        },
    )
    store.save_scenario_submission(revised)
    notes_by_id = {fact_review.fact_id: fact_review.notes for fact_review in revised.fact_reviews}
    assert notes_by_id[first.fact_id] == "State whether this amount is guaranteed."
    assert notes_by_id[third.fact_id] == "Clarify which customer segment this applies to."
    assert store.scenario_reviews() == [revised]


def test_scenario_form_uses_concise_guidance_instead_of_a_checklist() -> None:
    """Keep the review criteria concise and the record free of boolean checklist fields."""
    assert len(SCENARIO_REVIEW_GUIDANCE) == 5
    assert "labels" not in ResearcherScenarioReview.model_fields


def test_researcher_fact_notes_are_optional_per_fact_but_required_for_revise() -> None:
    """Persist complete fact records while requiring one note for a revise decision."""
    candidate = make_candidate_scenario()
    first, second, _, _ = candidate.material_facts
    fact_reviews = build_researcher_fact_reviews(
        candidate,
        {},
        None,
        {
            first.fact_id: "  Clarify the applicable period.  ",
            second.fact_id: " ",
        },
    )
    assert len(fact_reviews) == 4
    assert fact_reviews[0].notes == "Clarify the applicable period."
    assert fact_reviews[1].notes == ""
    with pytest.raises(ValidationError, match="at least one per-fact note"):
        build_researcher_scenario_review(
            scenario=candidate,
            decision=ReviewDecision.REVISE,
            researcher_id="researcher",
            reviewed_at=datetime.now(timezone.utc),
        )


def test_review_launch_resolves_candidates_and_reviews_from_one_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep candidate decisions scoped to the selected generation run."""
    run_root = tmp_path / "c1_calibration_v1"
    run_root.mkdir(parents=True)
    monkeypatch.setattr(review_launch, "scenario_generation_run_root", lambda run_id: tmp_path / run_id)
    args = argparse.Namespace(
        run_id="c1_calibration_v1",
        candidate_root=None,
        scenario_review_root=None,
        output_root=tmp_path / "conversation_reviews",
    )

    resolved_candidates, resolved_reviews = review_launch._resolve_scenario_roots(args)

    assert resolved_candidates == run_root
    assert resolved_reviews == run_root / "researcher_review"


def test_named_run_review_store_resolves_latest_versions_and_allows_re_review(tmp_path: Path) -> None:
    """Merge rounds by scenario hash and permit one decision for each candidate version."""
    run_root = tmp_path / "c1_calibration_v1"
    run_root.mkdir()
    (run_root / "run_config.json").write_text("{}\n", encoding="utf-8")
    original = make_candidate_scenario("CF005_C1")
    original_payload = original.model_dump(mode="json", exclude={"candidate_sha256"})
    original_payload["material_facts"][0]["canonical_proposition"] += " Clarified."
    replacement = CandidateScenario.model_validate({**original_payload, "candidate_sha256": artifact_sha256(original_payload)})
    write_model_json_atomic(
        run_root / "20260726T120000000001Z" / "scenarios" / original.scenario_id / "candidate.json",
        original,
    )
    write_model_json_atomic(
        run_root / "20260726T130000000001Z" / "scenarios" / replacement.scenario_id / "candidate.json",
        replacement,
    )
    initial_review = build_researcher_scenario_review(
        scenario=original,
        decision=ReviewDecision.REVISE,
        researcher_id="researcher",
        reviewed_at=datetime.now(timezone.utc),
        notes_by_fact={original.material_facts[0].fact_id: "Clarify the fact."},
    )
    store = ReviewStore(
        run_root,
        tmp_path / "scoring_inputs",
        tmp_path / "records",
        scenario_review_root=run_root / "researcher_review",
    )
    store.scenario_reviews_path.parent.mkdir(parents=True)
    store.scenario_reviews_path.write_text(initial_review.model_dump_json() + "\n", encoding="utf-8")

    assert store.list_candidates() == [replacement]
    replacement_review = build_researcher_scenario_review(
        scenario=replacement,
        decision=ReviewDecision.ACCEPT,
        researcher_id="researcher",
        reviewed_at=datetime.now(timezone.utc),
    )
    store.save_scenario_review(replacement_review)

    assert initial_review.review_id != replacement_review.review_id
    assert store.scenario_reviews() == [initial_review, replacement_review]


def test_specificity_markers_are_editable_and_optional_per_fact() -> None:
    """Accept empty or partial marker lists without inventing specificity."""
    candidate = make_candidate_scenario()
    cleared = build_researcher_fact_reviews(candidate, {}, {}, {})
    assert all(not fact_review.specificity_markers for fact_review in cleared)
    first = candidate.material_facts[0]
    selected = build_researcher_fact_reviews(candidate, {}, {first.fact_id: ["£120"]}, {})
    assert selected[0].specificity_markers == ["£120"]


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


def test_researcher_review_rejects_non_binary_pipeline_decisions(tmp_path: Path) -> None:
    """Restrict the researcher-facing decision to accept or revise."""
    store, accepted, _ = make_store(tmp_path)
    candidate = store.list_candidates()[0]
    with pytest.raises(ValidationError, match="only accept or revise"):
        ResearcherScenarioReview(
            schema_version="3.3.0",
            review_id="INVALID_1",
            anonymised_item_id="S-002",
            scenario_id=accepted.scenario_id,
            decision=ReviewDecision.REJECT,
            fact_reviews=build_researcher_fact_reviews(candidate, {}, None, {}),
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewed_at=datetime.now(timezone.utc),
            researcher_id="researcher",
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
