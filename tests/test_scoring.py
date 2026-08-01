"""Tests for fact-level content/presentation and response-level accuracy scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest
from pydantic import ValidationError

from src.cli.commands.scoring.resolve_manual import build_manual_resolution
from src.cli.commands.scoring.run import execute_scoring_transcripts
from src.cli.commands.scoring.validate_c1 import validate_c1_records
from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.experiments import CompletionFinishReason, RetryPolicy, TokenUsage
from src.data_models.manifests import EvaluatedModelSnapshot, FreezeStatus, ModelWeightType, ScoringExecutionManifest
from src.data_models.scenario_review import ReviewPass
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    AccuracyResponse,
    BlindFactReference,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    EvaluationCheckpoint,
    FactContentAssessmentResult,
    FactContentJudgment,
    FactContentResponse,
    FactPresentationAssessmentResult,
    FactPresentationResponse,
    FalseClaim,
    FramingDirection,
    ManualScoringQueueRecord,
    MarkerPresence,
    PresentationAssessmentResult,
    PresentationBehaviour,
    PresentationFinding,
    PresentationShift,
    ResponseSpan,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringCallArtifact,
    StructuredCallProvenance,
)
from src.experiments.openrouter_scoring import derive_content_judgment, derive_presentation_findings, validate_accuracy_response
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


def test_content_response_schema_contains_only_requested_llm_fields() -> None:
    """Keep metadata, offsets, and marker evidence out of the content LLM response."""
    schema = FactContentResponse.model_json_schema()
    assert set(schema["properties"]) == {"fact_present", "evidence_sentences", "markers", "reasoning"}
    marker_properties = schema["$defs"]["MarkerPresence"]["properties"]
    assert set(marker_properties) == {"element_id", "present"}
    schema_text = str(schema)
    assert "schema_version" not in schema_text
    assert "turn_index" not in schema_text
    assert "start_char" not in schema_text
    assert "end_char" not in schema_text


def test_other_response_schemas_contain_only_requested_llm_fields() -> None:
    """Keep identifiers, versions, and offsets out of presentation and accuracy output."""
    presentation_schema = FactPresentationResponse.model_json_schema()
    accuracy_schema = AccuracyResponse.model_json_schema()
    assert set(presentation_schema["properties"]) == {"shifts"}
    assert set(presentation_schema["$defs"]["PresentationShift"]["properties"]) == {
        "behaviour",
        "direction",
        "evidence",
        "reasoning",
    }
    assert set(accuracy_schema["properties"]) == {"false_claim_present", "false_claims"}
    assert set(accuracy_schema["$defs"]["FalseClaim"]["properties"]) == {"evidence", "reasoning"}
    for schema in (presentation_schema, accuracy_schema):
        schema_text = str(schema)
        assert "schema_version" not in schema_text
        assert "fact_id" not in schema_text
        assert "response_span" not in schema_text
        assert "finding_id" not in schema_text
        assert "visible_evidence_references" not in schema_text


def test_score_conversation_runs_presentation_only_for_present_facts() -> None:
    """Each response receives content, gated presentation, and one accuracy call."""
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
    assert len(calls) == 14
    assert sum(contract == "content" for contract, _response, _turn, _fact_id in calls) == 8
    assert sum(contract == "presentation" for contract, _response, _turn, _fact_id in calls) == 4
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
            reasoning="Absent.",
        )
    bad_span = fact.evidence[0].model_copy(update={"exact_quote": "wrong quote", "end_char": fact.evidence[0].start_char + 11})
    bad_fact = fact.model_copy(update={"evidence": [bad_span]})
    bad_content = _replace_content_fact(content[ScoredResponse.INITIAL], bad_fact)
    with pytest.raises(ValueError, match="does not match exact"):
        validate_scoring_results(
            inputs[ScoredResponse.INITIAL],
            transcript,
            bad_content,
            presentation[ScoredResponse.INITIAL],
            accuracy[ScoredResponse.INITIAL],
        )


def test_presentation_and_accuracy_require_exact_evidence_strings() -> None:
    """Attach fact IDs to exact presentation evidence and reject invented quotes."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = scoring_input.facts[0]
    evidence = "Adverse one costs £120"
    presentation = FactPresentationResponse(
        shifts=[
            PresentationShift(
                behaviour=PresentationBehaviour.MAGNITUDE_SHIFT,
                direction=FramingDirection.WEAKENING,
                evidence=evidence,
                reasoning="The response reduces the stated magnitude.",
            )
        ]
    )
    findings = derive_presentation_findings(presentation, scoring_input, fact)
    assert findings[0].fact_id == fact.fact_id
    assert findings[0].evidence == evidence
    bad_presentation = presentation.model_copy(update={"shifts": [presentation.shifts[0].model_copy(update={"evidence": "Invented."})]})
    with pytest.raises(ValueError, match="exact response substring"):
        derive_presentation_findings(bad_presentation, scoring_input, fact)

    accuracy = AccuracyResponse(
        false_claim_present=True,
        false_claims=[FalseClaim(evidence=evidence, reasoning="This statement is false.")],
    )
    assert validate_accuracy_response(accuracy, scoring_input) == accuracy
    with pytest.raises(ValueError, match="exact response substring"):
        validate_accuracy_response(
            AccuracyResponse(
                false_claim_present=True,
                false_claims=[FalseClaim(evidence="Invented.", reasoning="This statement is false.")],
            ),
            scoring_input,
        )


def test_content_response_derives_offsets_from_exact_evidence_sentences() -> None:
    """Derive response spans while retaining only binary specificity results."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = next(item for item in scoring_input.facts if item.fact_id.endswith("_F4"))
    quote = scoring_input.agent_turn.content
    response = FactContentResponse(
        fact_present=True,
        evidence_sentences=[quote],
        markers=[MarkerPresence(element_id=marker.element_id, present=True) for marker in fact.specificity_markers],
        reasoning="The response communicates the fact and its supplied marker.",
    )
    judgment = derive_content_judgment(response, scoring_input, fact)
    assert judgment.present is True
    assert judgment.evidence == [
        ResponseSpan(turn_index=1, start_char=0, end_char=len(quote), exact_quote=quote),
    ]
    assert all(not hasattr(marker, "evidence") and not hasattr(marker, "reason") for marker in judgment.marker_judgments)


def test_content_response_rejects_nonexact_sentences_and_missing_markers() -> None:
    """Reject invented evidence text and incomplete marker decisions."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_input = build_condition_blind_inputs(transcript, scenario, 7)[ScoredResponse.INITIAL]
    fact = next(item for item in scoring_input.facts if item.specificity_markers)
    response = FactContentResponse(
        fact_present=True,
        evidence_sentences=["This sentence was not in the response."],
        markers=[MarkerPresence(element_id=marker.element_id, present=False) for marker in fact.specificity_markers],
        reasoning="The fact is present.",
    )
    with pytest.raises(ValueError, match="exact response substring"):
        derive_content_judgment(response, scoring_input, fact)
    with pytest.raises(ValueError, match="every supplied specificity marker"):
        derive_content_judgment(response.model_copy(update={"markers": []}), scoring_input, fact)


def test_accuracy_response_allows_multiple_claims_and_checks_presence() -> None:
    """Allow multiple false claims while keeping the response-level Boolean consistent."""
    claims = [
        FalseClaim(evidence="First false claim.", reasoning="The first claim is fabricated."),
        FalseClaim(evidence="Second false claim.", reasoning="The second claim contradicts the facts."),
    ]
    response = AccuracyResponse(false_claim_present=True, false_claims=claims)
    assert len(response.false_claims) == 2
    with pytest.raises(ValidationError, match="must match"):
        AccuracyResponse(false_claim_present=False, false_claims=claims)


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
            evidence=quote,
            reasoning=f"The response applies a {behaviour.value} to this fact.",
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
                "evidence": fact.evidence[0].exact_quote,
                "reasoning": "Direction is deliberately missing.",
            }
        )
    with pytest.raises(ValidationError):
        PresentationFinding.model_validate(
            {
                "fact_id": fact.fact_id,
                "behaviour": "false_claim",
                "direction": "weakening",
                "evidence": fact.evidence[0].exact_quote,
                "reasoning": "An accuracy enum cannot enter presentation output.",
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
    owner_fact = f"{scenario.scenario_id}_F1"
    reverse_fact = f"{scenario.scenario_id}_F2"
    first = PresentationFinding(
        fact_id=owner_fact,
        behaviour=PresentationBehaviour.CERTAINTY_SHIFT,
        direction=FramingDirection.STRENGTHENING,
        evidence="Adverse one",
        reasoning="Strengthens certainty.",
    )
    second = PresentationFinding(
        fact_id=owner_fact,
        behaviour=PresentationBehaviour.MAGNITUDE_SHIFT,
        direction=FramingDirection.STRENGTHENING,
        evidence="£120",
        reasoning="Strengthens magnitude.",
    )
    reverse = PresentationFinding(
        fact_id=reverse_fact,
        behaviour=PresentationBehaviour.QUALIFICATION_SHIFT,
        direction=FramingDirection.STRENGTHENING,
        evidence="favourable one",
        reasoning="Strengthens a countervailing fact.",
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
        replacement = original.model_copy(update={"evidence": [shared_span]})
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
    finding = FalseClaim(
        evidence=quote,
        reasoning="The response fabricates a safety fact that is not present in the supplied facts.",
    )
    accuracy[ScoredResponse.INITIAL] = accuracy[ScoredResponse.INITIAL].model_copy(update={"false_claim_present": True, "false_claims": [finding]})
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


def test_executor_retries_only_failed_fact_call_and_caches_gated_successes(tmp_path: Path) -> None:
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
    assert sum(call_counts.values()) == 15
    assert call_counts[(ScoredResponse.INITIAL, "presentation", failing_fact_id)] == 2
    assert all(count == 1 for key, count in call_counts.items() if key != (ScoredResponse.INITIAL, "presentation", failing_fact_id))
    calls = read_model_jsonl(tmp_path / "scoring_calls.jsonl", ScoringCallArtifact)
    bundles = read_model_jsonl(
        tmp_path / "scored_conversations.jsonl",
        ScoredConversationBundle,
    )
    assert len(calls) == 14
    assert len(bundles) == 1
    assert validate_c1_records(bundles, calls, [], expected_conversation_count=1) == 14
    assert len([attempt for attempt in bundles[0].attempts if attempt.status.value == "succeeded"]) == 14
    execute_scoring_transcripts(
        [transcript],
        {scenario.scenario_id: scenario},
        _scoring_manifest(),
        tmp_path,
        Backend(),
    )
    assert sum(call_counts.values()) == 15


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
        false_claims={response: accuracy[response].false_claims for response in ScoredResponse},
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
