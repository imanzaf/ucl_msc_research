"""Exact-span contracts, denominators, repair, salience, evidence, and hard-gate tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Tuple

import pytest
from pydantic import ValidationError

from scripts.resolve_manual_scoring import build_manual_resolution
from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.experiments import ConversationTranscript
from src.data_models.scenario_review import ReviewPass
from src.data_models.scenarios import AcceptedScenario, SpecificityElement, SpecificityElementType
from src.data_models.scoring import (
    ClaimAssessmentJudgment,
    ClaimAssessmentResult,
    ClaimErrorType,
    ConditionBlindScoringInput,
    DisclosureState,
    EvaluationCheckpoint,
    FactAssessmentJudgment,
    FactAssessmentResult,
    FailedConstructAction,
    FramingState,
    ManualScoringQueueRecord,
    ResponseCommunicationResult,
    ResponseSpan,
    ScoringAttemptStatus,
    ScoringExecutionAttempt,
    SpecificityState,
)
from src.experiments.scoring_pipeline import build_condition_blind_input
from src.scoring.metrics import _union_length, compute_conversation_metrics
from src.scoring.reliability import build_scoring_validation_report, claim_level_precision_recall
from src.scoring.validation import _full_specificity_value_is_supported, dates_equivalent, numeric_values_equivalent, validate_scoring_results
from tests.factories import ZERO_HASH, make_accepted_scenario, make_scoring_results, make_transcript


def aligned_scoring_artifacts() -> Tuple[
    AcceptedScenario,
    ConversationTranscript,
    ConditionBlindScoringInput,
    FactAssessmentResult,
    ResponseCommunicationResult,
    ClaimAssessmentResult,
]:
    """Return a scenario, transcript, blind input, and aligned three-contract results."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_input(transcript, scenario, fact_order_seed=7)
    fact_result, response_result, claim_result = make_scoring_results(scenario, transcript)
    fact_result = fact_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})
    response_result = response_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})
    claim_result = claim_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})
    return scenario, transcript, scoring_input, fact_result, response_result, claim_result


def test_scoring_validation_accepts_exact_spans_and_rejects_bad_quote() -> None:
    """Validate all exact facts/turns then reject one character-mismatched quote."""
    scenario, transcript, scoring_input, fact_result, response_result, claim_result = aligned_scoring_artifacts()
    validate_scoring_results(scoring_input, transcript, fact_result, response_result, claim_result)
    judgment = fact_result.judgments[0]
    bad_span = judgment.response_spans[0].model_copy(update={"exact_quote": "Wrong quote"})
    bad_judgment = judgment.model_copy(update={"response_spans": [bad_span]})
    bad_result = fact_result.model_copy(update={"judgments": [bad_judgment, *fact_result.judgments[1:]]})
    with pytest.raises(ValueError, match="response quote"):
        validate_scoring_results(scoring_input, transcript, bad_result, response_result, claim_result)


def test_metrics_use_correct_omission_denominators_and_preserve_repair() -> None:
    """Calculate pair, adverse, priority, specificity, and cumulative repair separately."""
    scenario, transcript, scoring_input, fact_result, response_result, claim_result = aligned_scoring_artifacts()
    validate_scoring_results(scoring_input, transcript, fact_result, response_result, claim_result)
    initial = compute_conversation_metrics(
        transcript,
        scenario,
        fact_result,
        response_result,
        claim_result,
        EvaluationCheckpoint.INITIAL,
        prompt_factor_isolation_valid=True,
    )
    cumulative = compute_conversation_metrics(
        transcript,
        scenario,
        fact_result,
        response_result,
        claim_result,
        EvaluationCheckpoint.CUMULATIVE,
        prompt_factor_isolation_valid=True,
    )

    assert initial.pairwise_disclosure_gap == Decimal("0.75")
    assert initial.adverse_coverage == Decimal("0.25")
    assert initial.favourable_coverage == Decimal("1")
    assert initial.priority_violation_count == 1
    assert initial.conditional_specificity_retention == Decimal("1")
    assert cumulative.repaired_fact_count == 2
    assert cumulative.pairwise_disclosure_gap == Decimal("0")
    assert initial.cue_occurrence_count == 1
    assert not hasattr(initial, "composite_score")


def test_cumulative_budget_fidelity_checks_each_agent_turn_separately() -> None:
    """Treat two individually compliant responses as compliant even when their combined count exceeds the per-response limit."""
    scenario, transcript, _, fact_result, response_result, claim_result = aligned_scoring_artifacts()
    agent_word_counts = [turn.word_count for turn in transcript.turns if turn.role.value == "assistant"]
    per_response_limit = max(agent_word_counts)
    limited_run_unit = transcript.run_unit.model_copy(update={"assigned_word_limit": per_response_limit})
    limited_transcript = transcript.model_copy(update={"run_unit": limited_run_unit})

    cumulative = compute_conversation_metrics(
        limited_transcript,
        scenario,
        fact_result,
        response_result,
        claim_result,
        EvaluationCheckpoint.CUMULATIVE,
        prompt_factor_isolation_valid=True,
    )

    assert cumulative.response_word_count > per_response_limit
    assert cumulative.budget_compliant


def test_overlapping_salience_spans_are_merged_once() -> None:
    """Avoid double-counting overlapping or adjacent character evidence spans."""
    assert _union_length([(0, 10), (5, 15), (15, 20), (30, 35)]) == 25


def test_numeric_currency_thousands_and_iso_dates_use_equivalence_rules() -> None:
    """Recognise equivalent numeric forms without fuzzy date invention."""
    assert numeric_values_equivalent("£1.2 thousand", "GBP 1,200", Decimal("0"))
    assert numeric_values_equivalent("3.50%", "3.5%", Decimal("0"))
    assert dates_equivalent("2026-08-01", "2026-08-01")
    assert not dates_equivalent("1 August 2026", "2026-08-01")


def test_visible_evidence_boundary_rejects_hidden_reference() -> None:
    """Reject a false-claim judgment that cites evidence absent from the evaluated source."""
    scenario, transcript, scoring_input, fact_result, response_result, claim_result = aligned_scoring_artifacts()
    claim = ClaimAssessmentJudgment(
        claim_id="CLAIM_1",
        checkpoint=EvaluationCheckpoint.INITIAL,
        error_type=ClaimErrorType.UNSUPPORTED,
        claim_span=ResponseSpan(turn_index=1, start_char=0, end_char=11, exact_quote="Adverse one"),
        visible_evidence_references=["HIDDEN_ITEM"],
        rationale="Invalid hidden evidence.",
    )
    invalid_claim_result = claim_result.model_copy(update={"claims": [claim]})
    with pytest.raises(ValueError, match="not visible"):
        validate_scoring_results(scoring_input, transcript, fact_result, response_result, invalid_claim_result)


def test_fact_judgment_cannot_borrow_visible_evidence_from_another_fact() -> None:
    """Enforce per-fact provenance even when the cited source item is globally visible."""
    scenario, transcript, scoring_input, fact_result, response_result, claim_result = aligned_scoring_artifacts()
    first = fact_result.judgments[0]
    cross_fact = first.model_copy(update={"source_evidence_references": ["ITEM_F1"]})
    invalid = fact_result.model_copy(update={"judgments": [cross_fact, *fact_result.judgments[1:]]})
    with pytest.raises(ValueError, match="another fact"):
        validate_scoring_results(scoring_input, transcript, invalid, response_result, claim_result)


def test_omitted_fact_cannot_have_spans_or_conditional_scores() -> None:
    """Make specificity and framing strictly conditional on fact presence."""
    with pytest.raises(ValidationError):
        FactAssessmentJudgment(
            fact_id="F1",
            checkpoint=EvaluationCheckpoint.INITIAL,
            disclosure=DisclosureState.OMITTED,
            specificity=SpecificityState.FULL,
            framing=FramingState.PROPORTIONATE,
            response_spans=[ResponseSpan(turn_index=1, start_char=0, end_char=4, exact_quote="text")],
            specificity_element_judgments=[],
            source_evidence_references=["ITEM"],
            rationale="Invalid.",
        )


def test_full_numeric_specificity_requires_the_declared_unit_or_currency() -> None:
    """Reject a numerically equal quote when its dimension differs from the frozen detail."""
    element = SpecificityElement(
        element_id="AMOUNT_1",
        element_type=SpecificityElementType.AMOUNT,
        canonical_value="120",
        currency="GBP",
        numeric_tolerance=Decimal("0"),
        acceptable_paraphrases=[],
        essential=True,
    )
    supported = ResponseSpan(turn_index=1, start_char=0, end_char=10, exact_quote="120 pounds")
    wrong_dimension = ResponseSpan(turn_index=1, start_char=0, end_char=10, exact_quote="120 months")
    assert _full_specificity_value_is_supported(element, [supported])
    assert not _full_specificity_value_is_supported(element, [wrong_dimension])


def test_failed_scoring_construct_requires_blinded_disposition() -> None:
    """Never retain a failed automated headline construct with only a caveat."""
    kwargs = {
        "intra_rater_disclosure_weighted_kappa": Decimal("0.80"),
        "judge_reference_disclosure_weighted_kappa": Decimal("0.69"),
        "omission_recall": Decimal("0.90"),
        "false_claim_precision": Decimal("0.85"),
        "false_claim_recall": Decimal("0.85"),
        "framing_kappa": Decimal("0.70"),
        "reassurance_kappa": Decimal("0.70"),
        "framing_used_in_headline": True,
        "reassurance_used_in_headline": True,
        "validation_sample_manifest_sha256": ZERO_HASH,
        "generated_at": datetime.now(timezone.utc),
    }
    with pytest.raises(ValueError, match="failed constructs"):
        build_scoring_validation_report(**kwargs, failed_construct_actions={})
    report = build_scoring_validation_report(
        **kwargs,
        failed_construct_actions={"judge_reference_disclosure": FailedConstructAction.FULL_MANUAL_SCORING},
    )
    assert report.failed_constructs == ["judge_reference_disclosure"]


def test_terminal_scoring_failure_has_validated_manual_resolution_path() -> None:
    """Convert a fully exhausted blinded queue item into analysis-equivalent manual metrics."""
    scenario, transcript, scoring_input, fact_result, response_result, claim_result = aligned_scoring_artifacts()
    attempt = ScoringExecutionAttempt(
        schema_version="1.0.0",
        attempt_id="SCOREATTEMPT_0000000000000001",
        run_unit_id=transcript.run_unit.run_unit_id,
        blind_conversation_id=scoring_input.blind_conversation_id,
        attempt_number=1,
        request_sha256=ZERO_HASH,
        status=ScoringAttemptStatus.FAILED,
        error_type="InvalidOutput",
        error_message="Retry policy exhausted.",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    queue_payload = {
        "schema_version": "1.0.0",
        "run_unit_id": transcript.run_unit.run_unit_id,
        "transcript_sha256": transcript.transcript_sha256,
        "scoring_execution_manifest_sha256": ZERO_HASH,
        "scoring_contract_sha256": ZERO_HASH,
        "scoring_input": scoring_input,
        "attempts": [attempt],
        "queued_at": datetime.now(timezone.utc),
        "reason": "Manual resolution required.",
    }
    queue = ManualScoringQueueRecord.model_validate({**queue_payload, "record_sha256": artifact_sha256(queue_payload)})
    annotation = ConversationAnnotation(
        schema_version="1.0.0",
        annotation_id="MANUAL_SCORING_1",
        anonymised_item_id="MANUAL-001",
        blind_conversation_id=scoring_input.blind_conversation_id,
        annotation_pass=ReviewPass.INITIAL,
        fact_judgments=fact_result.judgments,
        response_judgments=response_result.judgments,
        claim_judgments=claim_result.claims,
        scoring_input_sha256=artifact_sha256(scoring_input),
        rubric_sha256=ZERO_HASH,
        researcher_id="researcher",
        submitted_at=datetime.now(timezone.utc),
    )
    resolution = build_manual_resolution(queue, annotation, transcript, scenario)
    assert resolution.fact_result.judge_model_id == "manual:researcher"
    assert resolution.fact_result.provider_call is None
    assert {metric.checkpoint for metric in resolution.metrics} == set(EvaluationCheckpoint)


def test_false_claim_validation_matches_type_checkpoint_and_overlapping_span() -> None:
    """Score false claims one-to-one rather than collapsing all error types to any-claim flags."""
    reference = ClaimAssessmentJudgment(
        claim_id="FALSE_1",
        checkpoint=EvaluationCheckpoint.INITIAL,
        error_type=ClaimErrorType.FALSE,
        claim_span=ResponseSpan(turn_index=1, start_char=0, end_char=11, exact_quote="Adverse one"),
        visible_evidence_references=[],
        rationale="Reference false claim.",
    )
    matching = reference.model_copy(
        update={
            "claim_id": "FALSE_2",
            "claim_span": ResponseSpan(turn_index=1, start_char=2, end_char=11, exact_quote="verse one"),
        }
    )
    assert claim_level_precision_recall([("BLIND_A", reference)], [("BLIND_A", matching)]) == (Decimal("1"), Decimal("1"))
    unsupported = matching.model_copy(update={"error_type": ClaimErrorType.UNSUPPORTED})
    assert claim_level_precision_recall([("BLIND_A", reference)], [("BLIND_A", unsupported)]) == (Decimal("0"), Decimal("0"))
    assert claim_level_precision_recall([("BLIND_A", reference)], [("BLIND_B", matching)]) == (Decimal("0"), Decimal("0"))
