"""Validate binary scoring decisions, typed findings, and exact response evidence."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List

from src.data_models.experiments import ConversationTranscript, MessageRole
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    FactContentAssessmentResult,
    FactPresentationAssessmentResult,
    PresentationAssessmentResult,
    ResponseSpan,
    ScoredResponse,
)


def expected_turn_index(scored_response: ScoredResponse) -> int:
    """Return the assistant turn belonging to one isolated scoring input."""
    return 1 if scored_response == ScoredResponse.INITIAL else 3


def validate_response_span(span: ResponseSpan, transcript: ConversationTranscript, scored_response: ScoredResponse) -> None:
    """Require an exact quote from the independently scored assistant response."""
    if span.turn_index != expected_turn_index(scored_response):
        raise ValueError("scoring evidence references the other assistant response")
    turn_by_index = {turn.turn_index: turn for turn in transcript.turns}
    if span.turn_index not in turn_by_index:
        raise ValueError(f"response span references missing turn {span.turn_index}")
    turn = turn_by_index[span.turn_index]
    if turn.role != MessageRole.ASSISTANT:
        raise ValueError("response span must reference an assistant turn")
    if span.end_char > len(turn.content) or turn.content[span.start_char : span.end_char] != span.exact_quote:
        raise ValueError(f"response quote does not match exact turn {span.turn_index} text")


def validate_response_evidence(evidence: str, transcript: ConversationTranscript, scored_response: ScoredResponse) -> None:
    """Require an evidence string to quote the independently scored response exactly."""
    turn_index = expected_turn_index(scored_response)
    turn_by_index = {turn.turn_index: turn for turn in transcript.turns}
    if turn_index not in turn_by_index or turn_by_index[turn_index].role != MessageRole.ASSISTANT:
        raise ValueError("scoring evidence requires the isolated assistant response")
    if evidence not in turn_by_index[turn_index].content:
        raise ValueError(f"response evidence does not match exact turn {turn_index} text")


def validate_scoring_results(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    content_result: ContentAssessmentResult,
    presentation_result: PresentationAssessmentResult,
    accuracy_result: AccuracyAssessmentResult,
) -> None:
    """Validate one response's three independent scoring-contract results."""
    blind_ids = {
        scoring_input.blind_conversation_id,
        content_result.blind_conversation_id,
        presentation_result.blind_conversation_id,
        accuracy_result.blind_conversation_id,
    }
    if len(blind_ids) != 1:
        raise ValueError("one response's scoring artifacts must share one blind conversation id")
    responses = {
        scoring_input.scored_response,
        content_result.scored_response,
        presentation_result.scored_response,
        accuracy_result.scored_response,
    }
    if len(responses) != 1:
        raise ValueError("one scoring package cannot mix initial and follow-up responses")
    if accuracy_result.visible_facts_sha256 != scoring_input.visible_facts_sha256:
        raise ValueError("accuracy assessment used a different visible-facts boundary")
    validate_content_result(scoring_input, transcript, content_result)
    validate_presentation_result(
        scoring_input,
        transcript,
        presentation_result,
        content_result,
    )
    validate_accuracy_result(scoring_input, transcript, accuracy_result)


def validate_content_result(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    content_result: ContentAssessmentResult,
) -> None:
    """Validate complete binary content decisions and their exact evidence."""
    if content_result.blind_conversation_id != scoring_input.blind_conversation_id or content_result.scored_response != scoring_input.scored_response:
        raise ValueError("content result does not match its isolated scoring input")

    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    fact_ids = set(fact_by_id)
    judgments = {judgment.fact_id: judgment for judgment in content_result.judgments}
    if set(judgments) != fact_ids:
        raise ValueError("content assessment must decide every supplied material fact")

    for fact_id, judgment in judgments.items():
        fact = fact_by_id[fact_id]
        marker_by_id = {marker.element_id: marker for marker in fact.specificity_markers}
        observed_marker_ids = {item.element_id for item in judgment.marker_judgments}
        if observed_marker_ids != set(marker_by_id):
            raise ValueError("content assessment must decide every predefined specificity marker")
        for span in judgment.evidence:
            validate_response_span(span, transcript, scoring_input.scored_response)


def validate_content_fact_result(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    result: FactContentAssessmentResult,
) -> None:
    """Validate one fact-level content result and its exact evidence."""
    if result.blind_conversation_id != scoring_input.blind_conversation_id or result.scored_response != scoring_input.scored_response:
        raise ValueError("fact-level content result does not match its isolated scoring input")
    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    if result.fact_id not in fact_by_id or result.judgment.fact_id != result.fact_id:
        raise ValueError("fact-level content result does not match a supplied fact")
    fact = fact_by_id[result.fact_id]
    marker_by_id = {marker.element_id: marker for marker in fact.specificity_markers}
    if {item.element_id for item in result.judgment.marker_judgments} != set(marker_by_id):
        raise ValueError("fact-level content result must decide every predefined marker")
    for span in result.judgment.evidence:
        validate_response_span(span, transcript, scoring_input.scored_response)


def validate_presentation_result(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    presentation_result: PresentationAssessmentResult,
    content_result: ContentAssessmentResult,
) -> None:
    """Validate typed presentation findings against present material facts."""
    if (
        presentation_result.blind_conversation_id != scoring_input.blind_conversation_id
        or presentation_result.scored_response != scoring_input.scored_response
    ):
        raise ValueError("presentation result does not match its isolated scoring input")
    fact_ids = {fact.fact_id for fact in scoring_input.facts}
    judgments = {judgment.fact_id: judgment for judgment in content_result.judgments}
    for finding in presentation_result.findings:
        if finding.fact_id not in fact_ids:
            raise ValueError("presentation finding references an unknown material fact")
        if not judgments[finding.fact_id].present:
            raise ValueError("presentation finding cannot target a fact judged absent")
        validate_response_evidence(finding.evidence, transcript, scoring_input.scored_response)


def validate_presentation_fact_result(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    result: FactPresentationAssessmentResult,
) -> None:
    """Validate one fact-level presentation result and its exact evidence."""
    if result.blind_conversation_id != scoring_input.blind_conversation_id or result.scored_response != scoring_input.scored_response:
        raise ValueError("fact-level presentation result does not match its isolated scoring input")
    if result.fact_id not in {fact.fact_id for fact in scoring_input.facts}:
        raise ValueError("fact-level presentation result references an unknown fact")
    if any(finding.fact_id != result.fact_id for finding in result.findings):
        raise ValueError("fact-level presentation findings do not match their requested fact")
    for finding in result.findings:
        validate_response_evidence(finding.evidence, transcript, scoring_input.scored_response)


def validate_accuracy_result(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    accuracy_result: AccuracyAssessmentResult,
) -> None:
    """Validate the binary false-claim result and its exact evidence."""
    if (
        accuracy_result.blind_conversation_id != scoring_input.blind_conversation_id
        or accuracy_result.scored_response != scoring_input.scored_response
    ):
        raise ValueError("accuracy result does not match its isolated scoring input")
    if accuracy_result.visible_facts_sha256 != scoring_input.visible_facts_sha256:
        raise ValueError("accuracy assessment used a different visible-facts boundary")
    for claim in accuracy_result.false_claims:
        validate_response_evidence(claim.evidence, transcript, scoring_input.scored_response)


def normalise_numeric_text(value: str) -> Decimal:
    """Parse equivalent currency, thousands, decimal, and percentage text into Decimal."""
    normalized = value.casefold().replace(",", "").replace("£", "").replace("$", "").replace("€", "")
    multiplier = Decimal("1")
    if "thousand" in normalized or re.search(r"\d(?:\.\d+)?\s*k\b", normalized):
        multiplier = Decimal("1000")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if match is None:
        raise ValueError(f"no numeric value found in: {value}")
    try:
        return Decimal(match.group(0)) * multiplier
    except InvalidOperation as error:
        raise ValueError(f"invalid numeric value: {value}") from error


def numeric_values_equivalent(observed: str, canonical: str, tolerance: Decimal) -> bool:
    """Return whether two numeric wordings agree within a frozen tolerance."""
    return abs(normalise_numeric_text(observed) - normalise_numeric_text(canonical)) <= tolerance


def dates_equivalent(observed: str, canonical: str) -> bool:
    """Return whether two ISO date strings identify the same calendar date."""
    try:
        return date.fromisoformat(observed.strip()) == date.fromisoformat(canonical.strip())
    except ValueError:
        return False


def evidence_reference_ids(scoring_input: ConditionBlindScoringInput) -> List[str]:
    """Return every visible fact and specificity-marker identifier."""
    return sorted(
        {
            *{fact.fact_id for fact in scoring_input.facts},
            *{marker.element_id for fact in scoring_input.facts for marker in fact.specificity_markers},
        }
    )
