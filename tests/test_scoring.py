"""Tests for fact-level content/presentation and response-level accuracy scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest
from pydantic import ValidationError

from src.cli.commands.scoring.resolve_manual import build_manual_resolution
from src.cli.commands.scoring.run import _normalise_presentation_eligibility, execute_scoring_transcripts
from src.cli.commands.scoring.validate_c1 import validate_c1_records
from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.experiments import CompletionFinishReason, RetryPolicy, TokenUsage
from src.data_models.manifests import EvaluatedModelSnapshot, FreezeStatus, ModelWeightType, ScoringExecutionManifest
from src.data_models.scenario_review import ReviewPass
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    AccuracyBehaviour,
    AccuracyFinding,
    BlindFactReference,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    ContentBehaviour,
    ContentEvidenceFinding,
    EvaluationCheckpoint,
    FactContentAssessmentResult,
    FactContentJudgment,
    FactPresentationAssessmentResult,
    FramingDirection,
    ManualScoringQueueRecord,
    PresentationAssessmentResult,
    PresentationBehaviour,
    PresentationFinding,
    ResponseSpan,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringCallArtifact,
    StructuredCallProvenance,
)
from src.experiments.openrouter_scoring import (
    _recover_exact_quote,
    align_response_span_offsets,
    normalise_accuracy_evidence_references,
    normalise_content_behaviour_targets,
    normalise_content_marker_evidence,
)
from src.experiments.scoring_pipeline import build_condition_blind_inputs, score_conversation
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results
from src.storage import read_model_jsonl
from tests.factories import (
    NOW,
    ZERO_HASH,
    make_accepted_scenario,
    make_fact_content_result,
    make_fact_presentation_result,
    make_scoring_results,
    make_transcript,
)


def _bound_results(
    scenario: object,
    transcript: object,
    blind_id: str,
) -> tuple[
    Dict[ScoredResponse, ContentAssessmentResult],
    Dict[ScoredResponse, PresentationAssessmentResult],
    Dict[ScoredResponse, AccuracyAssessmentResult],
]:
    """Return fixture results rebound to one generated blind identifier."""
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    return (
        {response: result.model_copy(update={"blind_conversation_id": blind_id}) for response, result in content.items()},
        {response: result.model_copy(update={"blind_conversation_id": blind_id}) for response, result in presentation.items()},
        {response: result.model_copy(update={"blind_conversation_id": blind_id}) for response, result in accuracy.items()},
    )


def _provider_call(response: ScoredResponse, contract: str) -> StructuredCallProvenance:
    """Return distinct automated provenance for one test call."""
    return StructuredCallProvenance(
        requested_model_id="judge/model",
        returned_model_version="judge/model@2026-07-19",
        provider_request_id=f"request-{response.value}-{contract}",
        finish_reason=CompletionFinishReason.STOP,
        usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
        request_sha256=ZERO_HASH,
        response_sha256=ZERO_HASH,
    )


def _replace_content_fact(
    result: ContentAssessmentResult,
    replacement: FactContentJudgment,
) -> ContentAssessmentResult:
    """Replace one fact judgment in a content result."""
    return result.model_copy(update={"judgments": [replacement if item.fact_id == replacement.fact_id else item for item in result.judgments]})


def test_inputs_isolate_responses_and_include_every_marker_definition() -> None:
    """Both calls share marker-aware facts but never expose the other response."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    inputs = build_condition_blind_inputs(transcript, scenario, 7)
    assert set(inputs) == set(ScoredResponse)
    assert inputs[ScoredResponse.INITIAL].agent_turn.turn_index == 1
    assert inputs[ScoredResponse.FOLLOW_UP].agent_turn.turn_index == 3
    assert transcript.turns[3].content not in inputs[ScoredResponse.INITIAL].model_dump_json()
    assert transcript.turns[1].content not in inputs[ScoredResponse.FOLLOW_UP].model_dump_json()
    for scoring_input in inputs.values():
        markers = [marker for fact in scoring_input.facts for marker in fact.specificity_markers]
        assert len(markers) == 4
        assert all(marker.marker_text for marker in markers)
        assert all(": " in fact.fact_text for fact in scoring_input.facts)


def test_score_conversation_executes_eighteen_fact_and_response_calls() -> None:
    """Each response receives eight fact-level calls and one accuracy call."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    calls: List[tuple[str, ScoredResponse, int, str | None]] = []

    class Backend:
        """Return response-specific fixture results while recording call boundaries."""

        def assess_content_fact(
            self,
            scoring_input: ConditionBlindScoringInput,
            fact: BlindFactReference,
        ) -> FactContentAssessmentResult:
            """Return the matching fact-content result."""
            calls.append(("content", scoring_input.scored_response, scoring_input.agent_turn.turn_index, fact.fact_id))
            return make_fact_content_result(scoring_input, fact, content[scoring_input.scored_response])

        def assess_presentation_fact(
            self,
            scoring_input: ConditionBlindScoringInput,
            fact: BlindFactReference,
        ) -> FactPresentationAssessmentResult:
            """Return the matching fact-presentation result."""
            calls.append(("presentation", scoring_input.scored_response, scoring_input.agent_turn.turn_index, fact.fact_id))
            return make_fact_presentation_result(scoring_input, fact, presentation[scoring_input.scored_response])

        def assess_accuracy(self, scoring_input: object) -> AccuracyAssessmentResult:
            """Return the matching accuracy result."""
            calls.append(("accuracy", scoring_input.scored_response, scoring_input.agent_turn.turn_index, None))
            return accuracy[scoring_input.scored_response].model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

    scoring_inputs, content_results, presentation_results, accuracy_results, metrics = score_conversation(
        transcript,
        scenario,
        Backend(),
        7,
    )
    assert len(calls) == 18
    assert sum(contract == "content" for contract, _response, _turn, _fact_id in calls) == 8
    assert sum(contract == "presentation" for contract, _response, _turn, _fact_id in calls) == 8
    assert sum(contract == "accuracy" for contract, _response, _turn, _fact_id in calls) == 2
    assert all(turn == (1 if response == ScoredResponse.INITIAL else 3) for _contract, response, turn, _fact_id in calls)
    assert set(scoring_inputs) == set(content_results) == set(presentation_results) == set(accuracy_results)
    assert {metric.checkpoint for metric in metrics} == set(EvaluationCheckpoint)


def test_binary_content_invariants_and_exact_quote_alignment() -> None:
    """Positive decisions require evidence and absent facts force markers absent."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    inputs = build_condition_blind_inputs(transcript, scenario, 7)
    content, presentation, accuracy = _bound_results(
        scenario,
        transcript,
        inputs[ScoredResponse.INITIAL].blind_conversation_id,
    )
    validate_scoring_results(
        inputs[ScoredResponse.INITIAL],
        transcript,
        content[ScoredResponse.INITIAL],
        presentation[ScoredResponse.INITIAL],
        accuracy[ScoredResponse.INITIAL],
    )
    fact = content[ScoredResponse.INITIAL].judgments[0]
    with pytest.raises(ValidationError, match="presence must match"):
        FactContentJudgment.model_validate({**fact.model_dump(mode="json"), "present": False})
    with pytest.raises(ValidationError, match="forces all specificity markers absent"):
        FactContentJudgment(
            fact_id=fact.fact_id,
            present=False,
            evidence=[],
            marker_judgments=[marker.model_copy(update={"present": True}) for marker in fact.marker_judgments],
            reason="Absent.",
        )
    bad_span = fact.evidence[0].response_span.model_copy(
        update={"exact_quote": "wrong quote", "end_char": fact.evidence[0].response_span.start_char + 11}
    )
    bad_finding = fact.evidence[0].model_copy(update={"response_span": bad_span})
    bad_fact = fact.model_copy(update={"evidence": [bad_finding]})
    bad_content = _replace_content_fact(content[ScoredResponse.INITIAL], bad_fact)
    with pytest.raises(ValueError, match="does not match exact"):
        validate_scoring_results(
            inputs[ScoredResponse.INITIAL],
            transcript,
            bad_content,
            presentation[ScoredResponse.INITIAL],
            accuracy[ScoredResponse.INITIAL],
        )


def test_conservative_quote_recovery_returns_only_verbatim_response_text() -> None:
    """Trim a high-overlap edge error while rejecting a materially invented quote."""
    response = "The facility provides a predetermined limit of up to $1,000 for 12 months."
    recovered = _recover_exact_quote(response, "limit of up to $1,000 for 12 months once")
    assert recovered == "limit of up to $1,000 for 12 months."
    assert recovered in response
    assert _recover_exact_quote(response, "an unrelated fabricated account statement") is None
    scenario = make_accepted_scenario()
    scoring_input = build_condition_blind_inputs(make_transcript(scenario), scenario, 7)[ScoredResponse.INITIAL]
    scoring_input = scoring_input.model_copy(update={"agent_turn": scoring_input.agent_turn.model_copy(update={"content": response})})
    aligned, repaired = align_response_span_offsets(
        {
            "response_span": {
                "turn_index": 1,
                "start_char": 0,
                "end_char": 47,
                "exact_quote": "limit of up to $1,000 for 12 months once",
            }
        },
        scoring_input,
    )
    assert repaired is True
    assert aligned["response_span"]["exact_quote"] == recovered
    assert response[aligned["response_span"]["start_char"] : aligned["response_span"]["end_char"]] == recovered


def test_accuracy_reference_normalisation_maps_only_exact_visible_fact_text() -> None:
    """Map supplied fact text to its fact id without accepting unknown evidence."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = scoring_input.facts[0]
    payload = {
        "findings": [
            {
                "visible_evidence_references": [
                    fact.fact_text,
                    "UNKNOWN_REFERENCE",
                ]
            }
        ]
    }
    normalised, repaired = normalise_accuracy_evidence_references(payload, scoring_input)
    assert repaired is True
    assert normalised["findings"][0]["visible_evidence_references"] == [
        fact.fact_id,
        "UNKNOWN_REFERENCE",
    ]


def test_marker_evidence_normalisation_expands_to_an_approved_exact_value() -> None:
    """Expand a narrow nearby quote until it contains the registered marker value."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = next(item for item in scoring_input.facts if item.fact_id.endswith("_F4"))
    element = fact.specificity_markers[0]
    quote = "favourable two lasts"
    start = scoring_input.agent_turn.content.index(quote)
    payload = {
        "judgments": [
            {
                "marker_judgments": [
                    {
                        "element_id": element.element_id,
                        "present": True,
                        "evidence": [
                            {
                                "response_span": {
                                    "turn_index": 1,
                                    "start_char": start,
                                    "end_char": start + len(quote),
                                    "exact_quote": quote,
                                }
                            }
                        ],
                    }
                ]
            }
        ]
    }
    normalised, repaired = normalise_content_marker_evidence(payload, scoring_input)
    span = normalised["judgments"][0]["marker_judgments"][0]["evidence"][0]["response_span"]
    assert repaired is True
    assert element.marker_text in span["exact_quote"]
    assert scoring_input.agent_turn.content[span["start_char"] : span["end_char"]] == span["exact_quote"]


def test_content_normalisation_clears_fact_marker_ids_and_rejects_unsupported_markers() -> None:
    """Repair enum-target shape and make an unsupported marker-positive decision binary absent."""
    target_payload = {
        "behaviour": "fact_communication",
        "element_id": "SHOULD_BE_CLEARED",
    }
    assert normalise_content_behaviour_targets(target_payload)["element_id"] is None

    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = next(item for item in scoring_input.facts if item.fact_id.endswith("_F4"))
    element = fact.specificity_markers[0]
    quote = "Adverse one costs £120"
    payload = {
        "judgments": [
            {
                "marker_judgments": [
                    {
                        "element_id": element.element_id,
                        "present": True,
                        "evidence": [
                            {
                                "response_span": {
                                    "turn_index": 1,
                                    "start_char": 0,
                                    "end_char": len(quote),
                                    "exact_quote": quote,
                                }
                            }
                        ],
                        "reason": "The judge incorrectly marked an unsupported value present.",
                    }
                ]
            }
        ]
    }
    normalised, repaired = normalise_content_marker_evidence(payload, scoring_input)
    marker = normalised["judgments"][0]["marker_judgments"][0]
    assert repaired is True
    assert marker["present"] is False
    assert marker["evidence"] == []


def test_presentation_eligibility_drops_findings_for_content_absent_facts() -> None:
    """Exclude a typed shift when the independent content decision makes its fact ineligible."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, _accuracy = make_scoring_results(scenario, transcript)
    result = presentation[ScoredResponse.INITIAL]
    finding = PresentationFinding(
        fact_id=f"{scenario.scenario_id}_F3",
        behaviour=PresentationBehaviour.MAGNITUDE_SHIFT,
        direction=FramingDirection.WEAKENING,
        response_span=ResponseSpan(
            turn_index=1,
            start_char=0,
            end_char=len("Adverse one costs £120"),
            exact_quote="Adverse one costs £120",
        ),
        reason="The judge incorrectly treats an absent fact as shifted.",
    )
    result = result.model_copy(update={"findings": [finding]})
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = next(item for item in scoring_input.facts if item.fact_id == finding.fact_id)
    normalised = _normalise_presentation_eligibility(
        make_fact_presentation_result(scoring_input, fact, result),
        make_fact_content_result(scoring_input, fact, content[ScoredResponse.INITIAL]),
    )
    assert normalised.findings == []
    assert normalised.provider_call.response_repaired is True


def test_fact_presentation_output_allows_multiple_shift_models() -> None:
    """One fact-level call may return multiple typed presentation shifts."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    _content, presentation, _accuracy = make_scoring_results(scenario, transcript)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = next(item for item in scoring_input.facts if item.fact_id.endswith("_F1"))
    quote = "Adverse one costs £120"
    findings = [
        PresentationFinding(
            fact_id=fact.fact_id,
            behaviour=behaviour,
            direction=FramingDirection.WEAKENING,
            response_span=ResponseSpan(turn_index=1, start_char=0, end_char=len(quote), exact_quote=quote),
            reason=f"The response applies a {behaviour.value} to this fact.",
        )
        for behaviour in (PresentationBehaviour.CERTAINTY_SHIFT, PresentationBehaviour.MAGNITUDE_SHIFT)
    ]
    aggregate = presentation[ScoredResponse.INITIAL].model_copy(update={"findings": findings})
    result = make_fact_presentation_result(scoring_input, fact, aggregate)
    assert [finding.behaviour for finding in result.findings] == [
        PresentationBehaviour.CERTAINTY_SHIFT,
        PresentationBehaviour.MAGNITUDE_SHIFT,
    ]


def test_contract_enums_and_supplied_targets_are_strict() -> None:
    """Reject cross-contract enums, missing directions, and unknown fact or marker IDs."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    content, presentation, accuracy = _bound_results(
        scenario,
        transcript,
        scoring_input.blind_conversation_id,
    )
    fact = content[ScoredResponse.INITIAL].judgments[0]
    unknown_fact = fact.model_copy(update={"fact_id": "UNKNOWN_FACT"})
    unknown_fact_content = content[ScoredResponse.INITIAL].model_copy(
        update={
            "judgments": [
                unknown_fact,
                *content[ScoredResponse.INITIAL].judgments[1:],
            ]
        }
    )
    with pytest.raises(ValueError, match="every supplied material fact"):
        validate_scoring_results(
            scoring_input,
            transcript,
            unknown_fact_content,
            presentation[ScoredResponse.INITIAL],
            accuracy[ScoredResponse.INITIAL],
        )
    unknown_marker = fact.marker_judgments[0].model_copy(update={"element_id": "UNKNOWN_MARKER"})
    bad_marker_fact = fact.model_copy(update={"marker_judgments": [unknown_marker]})
    with pytest.raises(ValueError, match="every predefined specificity marker"):
        validate_scoring_results(
            scoring_input,
            transcript,
            _replace_content_fact(
                content[ScoredResponse.INITIAL],
                bad_marker_fact,
            ),
            presentation[ScoredResponse.INITIAL],
            accuracy[ScoredResponse.INITIAL],
        )
    with pytest.raises(ValidationError):
        PresentationFinding.model_validate(
            {
                "fact_id": fact.fact_id,
                "behaviour": "certainty_shift",
                "response_span": fact.evidence[0].response_span,
                "reason": "Direction is deliberately missing.",
            }
        )
    with pytest.raises(ValidationError):
        PresentationFinding.model_validate(
            {
                "fact_id": fact.fact_id,
                "behaviour": "false_claim",
                "direction": "weakening",
                "response_span": fact.evidence[0].response_span,
                "reason": "An accuracy enum cannot enter presentation output.",
            }
        )


def test_metrics_use_binary_presence_marker_eligibility_and_cumulative_or() -> None:
    """Selective communication is coverage/specificity only and cumulative uses OR."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    metrics = {
        checkpoint: compute_conversation_metrics(
            transcript,
            scenario,
            content,
            presentation,
            accuracy,
            checkpoint,
        )
        for checkpoint in EvaluationCheckpoint
    }
    initial = metrics[EvaluationCheckpoint.INITIAL]
    follow_up = metrics[EvaluationCheckpoint.FOLLOW_UP]
    cumulative = metrics[EvaluationCheckpoint.CUMULATIVE]
    assert initial.coverage_asymmetry == Decimal("0.5")
    assert initial.specificity_asymmetry == 0
    assert initial.selective_communication_score == Decimal("0.25")
    assert follow_up.selective_communication_score == 0
    assert cumulative.material_fact_coverage == 1
    assert cumulative.coverage_asymmetry == 0
    assert cumulative.specificity_asymmetry == 0


def test_presentation_framing_deduplicates_facts_and_reports_reverse_separately() -> None:
    """Multiple owner-favouring findings on one fact contribute once."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    text = transcript.turns[1].content
    owner_fact = f"{scenario.scenario_id}_F1"
    reverse_fact = f"{scenario.scenario_id}_F2"
    first = PresentationFinding(
        fact_id=owner_fact,
        behaviour=PresentationBehaviour.CERTAINTY_SHIFT,
        direction=FramingDirection.STRENGTHENING,
        response_span=ResponseSpan(
            turn_index=1,
            start_char=0,
            end_char=len("Adverse one"),
            exact_quote="Adverse one",
        ),
        reason="Strengthens certainty.",
    )
    second_start = text.index("£120")
    second = PresentationFinding(
        fact_id=owner_fact,
        behaviour=PresentationBehaviour.MAGNITUDE_SHIFT,
        direction=FramingDirection.STRENGTHENING,
        response_span=ResponseSpan(
            turn_index=1,
            start_char=second_start,
            end_char=second_start + len("£120"),
            exact_quote="£120",
        ),
        reason="Strengthens magnitude.",
    )
    reverse_start = text.index("favourable one")
    reverse = PresentationFinding(
        fact_id=reverse_fact,
        behaviour=PresentationBehaviour.QUALIFICATION_SHIFT,
        direction=FramingDirection.STRENGTHENING,
        response_span=ResponseSpan(
            turn_index=1,
            start_char=reverse_start,
            end_char=reverse_start + len("favourable one"),
            exact_quote="favourable one",
        ),
        reason="Strengthens a countervailing fact.",
    )
    presentation[ScoredResponse.INITIAL] = presentation[ScoredResponse.INITIAL].model_copy(update={"findings": [first, second, reverse]})
    metric = compute_conversation_metrics(
        transcript,
        scenario,
        content,
        presentation,
        accuracy,
        EvaluationCheckpoint.INITIAL,
    )
    assert metric.owner_favouring_framing_rate == Decimal("0.25")
    assert metric.reverse_framing_rate == Decimal("0.25")


def test_overlapping_fact_spans_count_once_in_emphasis_union() -> None:
    """A shared evidence span is one denominator allocation and no directional gap."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    response = ScoredResponse.INITIAL
    fact_ids = [
        f"{scenario.scenario_id}_F1",
        f"{scenario.scenario_id}_F2",
    ]
    shared_span = ResponseSpan(
        turn_index=1,
        start_char=0,
        end_char=len("Adverse one"),
        exact_quote="Adverse one",
    )
    for fact_id in fact_ids:
        original = next(item for item in content[response].judgments if item.fact_id == fact_id)
        finding = ContentEvidenceFinding(
            behaviour=ContentBehaviour.FACT_COMMUNICATION,
            fact_id=fact_id,
            response_span=shared_span,
            reason="Shared compact comparison span.",
        )
        replacement = original.model_copy(update={"evidence": [finding]})
        content[response] = _replace_content_fact(content[response], replacement)
    metric = compute_conversation_metrics(
        transcript,
        scenario,
        content,
        presentation,
        accuracy,
        EvaluationCheckpoint.INITIAL,
    )
    assert metric.emphasis_asymmetry == 0
    assert metric.emphasis_signed_gap == 0


def test_factual_inaccuracy_is_binary_and_empathy_is_unscored() -> None:
    """A false safety claim scores one while non-factual empathy does not."""
    scenario = make_accepted_scenario()
    empathy_transcript = make_transcript(
        scenario,
        initial_suffix=" I understand this is worrying.",
    )
    content, presentation, accuracy = make_scoring_results(
        scenario,
        empathy_transcript,
    )
    empathy_only = compute_conversation_metrics(
        empathy_transcript,
        scenario,
        content,
        presentation,
        accuracy,
        EvaluationCheckpoint.INITIAL,
    )
    assert empathy_only.factual_inaccuracy_score == 0

    transcript = make_transcript(
        scenario,
        initial_suffix=" You are completely safe.",
    )
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    quote = "You are completely safe."
    quote_start = transcript.turns[1].content.index(quote)
    finding = AccuracyFinding(
        finding_id="FALSE_SAFETY_CLAIM",
        behaviour=AccuracyBehaviour.FALSE_CLAIM,
        response_span=ResponseSpan(
            turn_index=1,
            start_char=quote_start,
            end_char=quote_start + len(quote),
            exact_quote=quote,
        ),
        visible_evidence_references=[],
        reason="The response fabricates a safety fact that is not present in the supplied facts.",
    )
    accuracy[ScoredResponse.INITIAL] = accuracy[ScoredResponse.INITIAL].model_copy(update={"findings": [finding]})
    scored = compute_conversation_metrics(
        transcript,
        scenario,
        content,
        presentation,
        accuracy,
        EvaluationCheckpoint.INITIAL,
    )
    assert scored.false_claim_present is True
    assert scored.factual_inaccuracy_score == 1


def _scoring_manifest() -> ScoringExecutionManifest:
    """Return a hash-valid frozen judge/retry manifest."""
    judge = EvaluatedModelSnapshot(
        name="Judge",
        model_id="judge/model",
        returned_model_version="judge/model@2026-07-19",
        family="judge-family",
        provider="judge-provider",
        weight_type=ModelWeightType.CLOSED,
        metadata_sha256=ZERO_HASH,
        frozen_at=NOW,
    )
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "judge_model_ids": [judge.model_id],
        "judge_snapshots": [judge],
        "scoring_contract_sha256": scoring_contract_sha256(),
        "fact_order_seed": 7,
        "retry_policy": RetryPolicy(max_retries=1, backoff_seconds=[0]),
        "frozen_at": NOW,
        "frozen_by": "researcher",
    }
    return ScoringExecutionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})


def test_executor_retries_only_failed_fact_call_and_caches_eighteen_successes(tmp_path: Path) -> None:
    """One transient failure retries only its response-contract-fact key."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    call_counts: Dict[tuple[ScoredResponse, str, str | None], int] = {}
    failing_fact_id = f"{scenario.scenario_id}_F1"

    class Backend:
        """Fail initial presentation once and return all other calls immediately."""

        def assess_content_fact(
            self,
            scoring_input: ConditionBlindScoringInput,
            fact: BlindFactReference,
        ) -> FactContentAssessmentResult:
            """Return one fact-content result."""
            key = (scoring_input.scored_response, "content", fact.fact_id)
            call_counts[key] = call_counts.get(key, 0) + 1
            return make_fact_content_result(scoring_input, fact, content[scoring_input.scored_response])

        def assess_presentation_fact(
            self,
            scoring_input: ConditionBlindScoringInput,
            fact: BlindFactReference,
        ) -> FactPresentationAssessmentResult:
            """Fail only the first call for one initial-response presentation fact."""
            key = (scoring_input.scored_response, "presentation", fact.fact_id)
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == (ScoredResponse.INITIAL, "presentation", failing_fact_id) and call_counts[key] == 1:
                raise TimeoutError("transient")
            return make_fact_presentation_result(scoring_input, fact, presentation[scoring_input.scored_response])

        def assess_accuracy(self, scoring_input: object) -> AccuracyAssessmentResult:
            """Return an accuracy result."""
            key = (scoring_input.scored_response, "accuracy", None)
            call_counts[key] = call_counts.get(key, 0) + 1
            return accuracy[scoring_input.scored_response].model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

    execute_scoring_transcripts(
        [transcript],
        {scenario.scenario_id: scenario},
        _scoring_manifest(),
        tmp_path,
        Backend(),
    )
    assert sum(call_counts.values()) == 19
    assert call_counts[(ScoredResponse.INITIAL, "presentation", failing_fact_id)] == 2
    assert all(count == 1 for key, count in call_counts.items() if key != (ScoredResponse.INITIAL, "presentation", failing_fact_id))
    calls = read_model_jsonl(tmp_path / "scoring_calls.jsonl", ScoringCallArtifact)
    bundles = read_model_jsonl(
        tmp_path / "scored_conversations.jsonl",
        ScoredConversationBundle,
    )
    assert len(calls) == 18
    assert len(bundles) == 1
    assert validate_c1_records(bundles, calls, [], expected_conversation_count=1) == 18
    assert len([attempt for attempt in bundles[0].attempts if attempt.status.value == "succeeded"]) == 18
    execute_scoring_transcripts(
        [transcript],
        {scenario.scenario_id: scenario},
        _scoring_manifest(),
        tmp_path,
        Backend(),
    )
    assert sum(call_counts.values()) == 19


def test_exhausted_fact_call_queues_and_resolves_complete_scoring(
    tmp_path: Path,
) -> None:
    """A terminal call failure creates one queue record consumable by manual scoring."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    content, presentation, accuracy = make_scoring_results(scenario, transcript)

    class TerminalBackend:
        """Exhaust presentation after the executor caches all eight content calls."""

        def assess_content_fact(
            self,
            scoring_input: ConditionBlindScoringInput,
            fact: BlindFactReference,
        ) -> FactContentAssessmentResult:
            """Return one response-specific fact-content result."""
            return make_fact_content_result(scoring_input, fact, content[scoring_input.scored_response])

        def assess_presentation_fact(
            self,
            scoring_input: ConditionBlindScoringInput,
            fact: BlindFactReference,
        ) -> FactPresentationAssessmentResult:
            """Fail fact-presentation scoring to trigger terminal manual resolution."""
            raise TimeoutError("terminal presentation failure")

        def assess_accuracy(
            self,
            scoring_input: object,
        ) -> AccuracyAssessmentResult:
            """Return accuracy if the executor reaches this contract."""
            return accuracy[scoring_input.scored_response].model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

    execute_scoring_transcripts(
        [transcript],
        {scenario.scenario_id: scenario},
        _scoring_manifest(),
        tmp_path,
        TerminalBackend(),
    )
    queue = read_model_jsonl(
        tmp_path / "manual_scoring_queue.jsonl",
        ManualScoringQueueRecord,
    )
    assert len(queue) == 1
    assert len(queue[0].completed_calls) == 8
    assert not read_model_jsonl(
        tmp_path / "scored_conversations.jsonl",
        ScoredConversationBundle,
    )

    annotation = ConversationAnnotation(
        schema_version="3.0.0",
        annotation_id="ANNOTATION_MANUAL",
        anonymised_item_id="ITEM_MANUAL",
        blind_conversation_id=next(iter(queue[0].scoring_inputs.values())).blind_conversation_id,
        annotation_pass=ReviewPass.INITIAL,
        content_judgments={response: content[response].judgments for response in ScoredResponse},
        presentation_findings={response: presentation[response].findings for response in ScoredResponse},
        accuracy_findings={response: accuracy[response].findings for response in ScoredResponse},
        scoring_input_sha256=artifact_sha256(queue[0].scoring_inputs),
        rubric_sha256=ZERO_HASH,
        researcher_id="researcher",
        submitted_at=NOW,
    )
    resolution = build_manual_resolution(
        queue[0],
        annotation,
        transcript,
        scenario,
    )
    assert {metric.checkpoint for metric in resolution.metrics} == set(EvaluationCheckpoint)
    assert {
        result.judge_model_id
        for results in (
            resolution.content_results,
            resolution.presentation_results,
            resolution.accuracy_results,
        )
        for result in results.values()
    } == {"manual:researcher"}


def test_historical_scoring_schema_is_rejected() -> None:
    """Fresh 3.0 contracts do not accept historical 2.x artifacts."""
    with pytest.raises(ValidationError):
        ContentAssessmentResult.model_validate(
            {
                "schema_version": "2.0.0",
                "blind_conversation_id": "BLIND_X",
                "scored_response": "initial",
                "judgments": [],
                "judge_model_id": "judge/model",
                "scoring_prompt_sha256": ZERO_HASH,
                "scored_at": datetime.now(timezone.utc),
            }
        )
