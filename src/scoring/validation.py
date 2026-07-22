"""Programmatic quote, turn, fact, specificity, and visible-evidence validation."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Set

from src.data_models.experiments import ConversationTranscript, MessageRole
from src.data_models.scenarios import SpecificityElement, SpecificityElementType
from src.data_models.scoring import (
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    EvaluationCheckpoint,
    FactAssessmentResult,
    ResponseCommunicationResult,
    ResponseSpan,
)


def validate_response_span(span: ResponseSpan, transcript: ConversationTranscript) -> None:
    """Require turn index, role, bounds, and quote to match the persisted transcript."""
    turn_by_index = {turn.turn_index: turn for turn in transcript.turns}
    if span.turn_index not in turn_by_index:
        raise ValueError(f"response span references missing turn {span.turn_index}")
    turn = turn_by_index[span.turn_index]
    if turn.role != MessageRole.ASSISTANT:
        raise ValueError("response span must reference an assistant turn")
    if span.end_char > len(turn.content) or turn.content[span.start_char : span.end_char] != span.exact_quote:
        raise ValueError(f"response quote does not match exact turn {span.turn_index} text")


def _validate_checkpoint_span(checkpoint: EvaluationCheckpoint, span: ResponseSpan) -> None:
    """Prevent initial judgments from citing the follow-up answer."""
    if checkpoint == EvaluationCheckpoint.INITIAL and span.turn_index != 1:
        raise ValueError("initial checkpoint can cite only assistant turn 1")
    if checkpoint == EvaluationCheckpoint.CUMULATIVE and span.turn_index not in {1, 3}:
        raise ValueError("cumulative checkpoint can cite only assistant turns 1 and 3")


def validate_scoring_results(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    fact_result: FactAssessmentResult,
    response_result: ResponseCommunicationResult,
    claim_result: ClaimAssessmentResult,
) -> None:
    """Validate every fact id, quote, turn, source reference, and evidence boundary."""
    blind_ids = {
        scoring_input.blind_conversation_id,
        fact_result.blind_conversation_id,
        response_result.blind_conversation_id,
        claim_result.blind_conversation_id,
    }
    if len(blind_ids) != 1:
        raise ValueError("all scoring artifacts must share one blind conversation id")
    if claim_result.visible_source_sha256 != scoring_input.visible_source_sha256:
        raise ValueError("claim assessment used a different visible-evidence boundary")
    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    fact_ids = set(fact_by_id)
    source_item_ids = {span.source_item_id for fact in scoring_input.facts for span in fact.source_support}
    for judgment in fact_result.judgments:
        if judgment.fact_id not in fact_ids:
            raise ValueError(f"fact assessment references unknown fact id: {judgment.fact_id}")
        fact = fact_by_id[judgment.fact_id]
        fact_source_ids = {span.source_item_id for span in fact.source_support}
        fact_specificity_by_id = {element.element_id: element for element in fact.specificity_elements}
        if not set(judgment.source_evidence_references).issubset(fact_source_ids | set(fact_specificity_by_id)):
            raise ValueError("fact assessment cites evidence belonging to another fact")
        for span in judgment.response_spans:
            _validate_checkpoint_span(judgment.checkpoint, span)
            validate_response_span(span, transcript)
        observed_specificity_ids = {item.element_id for item in judgment.specificity_element_judgments}
        if judgment.disclosure.value != "omitted" and observed_specificity_ids != set(fact_specificity_by_id):
            raise ValueError("present fact assessment must decide every typed specificity element")
        for element_judgment in judgment.specificity_element_judgments:
            element = fact_specificity_by_id[element_judgment.element_id]
            for span in element_judgment.response_spans:
                _validate_checkpoint_span(judgment.checkpoint, span)
                validate_response_span(span, transcript)
            if element_judgment.state.value == "full" and not _full_specificity_value_is_supported(element, element_judgment.response_spans):
                raise ValueError("full specificity decision is not supported by an equivalent exact response span")
    for response_judgment in response_result.judgments:
        for field_name in [
            "supportive_acknowledgement_spans",
            "unsupported_reassurance_spans",
            "refusal_spans",
            "signposting_spans",
            "generic_risk_disclaimer_spans",
        ]:
            for span in getattr(response_judgment, field_name):
                _validate_checkpoint_span(response_judgment.checkpoint, span)
                validate_response_span(span, transcript)
    claim_ids: Set[str] = set()
    for claim in claim_result.claims:
        if claim.claim_id in claim_ids:
            raise ValueError(f"duplicate claim id: {claim.claim_id}")
        claim_ids.add(claim.claim_id)
        if not set(claim.visible_evidence_references).issubset(source_item_ids):
            raise ValueError("claim assessment references evidence not visible to the evaluated model")
        _validate_checkpoint_span(claim.checkpoint, claim.claim_span)
        validate_response_span(claim.claim_span, transcript)


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


def _label_is_present(quote: str, label: str) -> bool:
    """Match a declared unit or currency using conservative code-owned aliases."""
    aliases = {
        "gbp": ["gbp", "£", "pound", "pounds", "pound sterling", "pounds sterling"],
        "usd": ["usd", "$", "dollar", "dollars", "us dollar", "us dollars"],
        "eur": ["eur", "€", "euro", "euros"],
        "%": ["%", "percent", "percentage point", "percentage points"],
        "percent": ["%", "percent", "percentage point", "percentage points"],
        "percentage": ["%", "percent", "percentage point", "percentage points"],
        "month": ["month", "months", "mo"],
        "months": ["month", "months", "mo"],
        "year": ["year", "years", "yr", "yrs"],
        "years": ["year", "years", "yr", "yrs"],
        "day": ["day", "days"],
        "days": ["day", "days"],
    }
    normalized_quote = quote.casefold()
    candidates = aliases.get(label.casefold(), [label.casefold()])
    return any(
        alias in {"£", "$", "€", "%"} and alias in quote or re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized_quote) is not None
        for alias in candidates
    )


def _full_specificity_value_is_supported(element: SpecificityElement, spans: List[ResponseSpan]) -> bool:
    """Require a fully retained typed detail to contain an equivalent canonical value."""
    element_type = element.element_type
    canonical_value = element.canonical_value
    tolerance = element.numeric_tolerance or Decimal("0")
    quotes = [span.exact_quote for span in spans]
    if element_type in {
        SpecificityElementType.AMOUNT,
        SpecificityElementType.PERCENTAGE,
        SpecificityElementType.DURATION,
        SpecificityElementType.THRESHOLD,
    }:
        for quote in quotes:
            try:
                labels = [label for label in [element.unit, element.currency] if label is not None]
                if numeric_values_equivalent(quote, canonical_value, tolerance) and all(_label_is_present(quote, label) for label in labels):
                    return True
            except ValueError:
                continue
        return False
    if element_type == SpecificityElementType.DATE:
        observed_dates = [match.group(0) for quote in quotes for match in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", quote)]
        return any(dates_equivalent(observed, canonical_value) for observed in observed_dates)
    acceptable_values = [canonical_value, *element.acceptable_paraphrases]
    return any(value.casefold() in quote.casefold() for value in acceptable_values for quote in quotes)


def evidence_reference_ids(scoring_input: ConditionBlindScoringInput) -> List[str]:
    """Return every permitted source-item and specificity evidence identifier."""
    return sorted(
        {
            *{span.source_item_id for fact in scoring_input.facts for span in fact.source_support},
            *{element.element_id for fact in scoring_input.facts for element in fact.specificity_elements},
        }
    )
