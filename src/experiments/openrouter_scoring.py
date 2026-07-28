"""OpenRouter backend for the three independent condition-blind scoring contracts."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import VersionedImmutableModel, sha256_bytes, utc_now
from src.data_models.experiments import TokenUsage, provider_compatible_seed
from src.data_models.manifests import EvaluatedModelSnapshot
from src.data_models.scoring import (
    ClaimAssessmentJudgment,
    ClaimAssessmentResult,
    CommunicationState,
    ConditionBlindScoringInput,
    DisclosureState,
    EvaluationCheckpoint,
    FactAssessmentJudgment,
    FactAssessmentResult,
    FramingState,
    ResponseCommunicationJudgment,
    ResponseCommunicationResult,
    SpecificityState,
    StructuredCallProvenance,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scoring_contracts import CLAIM_ASSESSMENT_SYSTEM_PROMPT, FACT_ASSESSMENT_SYSTEM_PROMPT, RESPONSE_COMMUNICATION_SYSTEM_PROMPT
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)


def normalise_provisional_span_bounds(value: Any) -> Any:
    """Make model-supplied provisional span lengths structurally parseable."""
    if isinstance(value, list):
        return [normalise_provisional_span_bounds(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalised = {key: normalise_provisional_span_bounds(item) for key, item in value.items()}
    span_keys = {"turn_index", "start_char", "end_char", "exact_quote"}
    if span_keys.issubset(normalised) and isinstance(normalised["start_char"], int) and isinstance(normalised["exact_quote"], str):
        normalised["end_char"] = normalised["start_char"] + len(normalised["exact_quote"])
    return normalised


def longest_edge_trimmed_exact_quote(exact_quote: str, turn_text: str) -> str | None:
    """Return the longest exact quote obtainable by conservative whole-token edge trimming."""
    token_matches = list(re.finditer(r"\S+", exact_quote))
    minimum_length = max(8, (len(exact_quote) * 3 + 3) // 4)
    candidates: List[str] = []
    for start_index in range(len(token_matches)):
        for end_index in range(start_index, len(token_matches)):
            candidate = exact_quote[token_matches[start_index].start() : token_matches[end_index].end()]
            if len(candidate) >= minimum_length and candidate in turn_text:
                candidates.append(candidate)
    return max(candidates, key=lambda candidate: (len(candidate), -exact_quote.index(candidate))) if candidates else None


def subsequence_expanded_exact_quote(exact_quote: str, turn_text: str, proposed_start: int) -> str | None:
    """Expand an abbreviated quote when all of its tokens occur in order within one short exact window."""

    def normalise_token(token: str) -> str:
        """Remove only edge punctuation for conservative token matching."""
        return token.casefold().strip(".,;:!?()[]{}\"'")

    quote_matches = list(re.finditer(r"\S+", exact_quote))
    quote_tokens = [normalise_token(match.group()) for match in quote_matches]
    quantitative_short_quote = 2 <= len(quote_tokens) <= 3 and all(re.search(r"\d", token) is not None for token in quote_tokens)
    if (len(quote_tokens) < 4 and not quantitative_short_quote) or any(not token for token in quote_tokens):
        return None
    turn_matches = list(re.finditer(r"\S+", turn_text))
    turn_tokens = [normalise_token(match.group()) for match in turn_matches]
    candidates: List[Tuple[int, int]] = []
    for start_index, token in enumerate(turn_tokens):
        if token != quote_tokens[0]:
            continue
        matched_indices = [start_index]
        cursor = start_index + 1
        for quote_token in quote_tokens[1:]:
            match_index = next(
                (index for index in range(cursor, min(cursor + 9, len(turn_tokens))) if turn_tokens[index] == quote_token),
                None,
            )
            if match_index is None:
                break
            matched_indices.append(match_index)
            cursor = match_index + 1
        if len(matched_indices) != len(quote_tokens):
            continue
        start_char = turn_matches[matched_indices[0]].start()
        end_char = turn_matches[matched_indices[-1]].end()
        maximum_window_length = max(len(exact_quote) * 2, 80) if quantitative_short_quote else len(exact_quote) * 2
        if end_char - start_char <= maximum_window_length:
            candidates.append((start_char, end_char))
    if not candidates:
        return None
    start_char, end_char = min(
        candidates,
        key=lambda candidate: (
            abs(candidate[0] - proposed_start),
            candidate[1] - candidate[0],
            candidate[0],
        ),
    )
    return turn_text[start_char:end_char]


def hyphenated_unit_equivalent_exact_quote(exact_quote: str, turn_text: str, proposed_start: int) -> str | None:
    """Ground a hyphenated numeric duration in an exact singular/plural response phrase."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*-\s*(month|year|day|week|hour)s?\s*", exact_quote, flags=re.IGNORECASE)
    if match is None:
        return None
    value, unit = match.groups()
    candidates = [
        (candidate.start(), candidate.group())
        for candidate in re.finditer(rf"(?<!\w){re.escape(value)}(?:-|\s+){re.escape(unit)}s?(?!\w)", turn_text, flags=re.IGNORECASE)
    ]
    return min(candidates, key=lambda candidate: (abs(candidate[0] - proposed_start), candidate[0]))[1] if candidates else None


def align_response_span_offsets(value: Any, scoring_input: ConditionBlindScoringInput) -> Tuple[Any, bool]:
    """Align every exact-quote span to evaluated response text and report whether offsets changed."""
    turn_text_by_index = {turn.turn_index: turn.content for turn in scoring_input.agent_turns}

    def align(item: Any) -> Tuple[Any, bool]:
        """Recursively align response-span dictionaries within one scoring draft."""
        if isinstance(item, list):
            aligned_items = [align(child) for child in item]
            return [child for child, _ in aligned_items], any(changed for _, changed in aligned_items)
        if not isinstance(item, dict):
            return item, False
        span_keys = {"turn_index", "start_char", "end_char", "exact_quote"}
        if span_keys.issubset(item):
            turn_index = item["turn_index"]
            exact_quote = item["exact_quote"]
            proposed_start = item["start_char"]
            if turn_index not in turn_text_by_index:
                raise ValueError(f"response span refers to unavailable assistant turn {turn_index}")
            if not isinstance(exact_quote, str) or not exact_quote:
                raise ValueError("response span exact_quote must be non-empty text")
            if not isinstance(proposed_start, int):
                raise ValueError("response span start_char must be an integer")
            turn_text = turn_text_by_index[turn_index]
            occurrences: List[int] = []
            search_from = 0
            while True:
                occurrence = turn_text.find(exact_quote, search_from)
                if occurrence < 0:
                    break
                occurrences.append(occurrence)
                search_from = occurrence + 1
            if not occurrences:
                trimmed_quote = longest_edge_trimmed_exact_quote(exact_quote, turn_text)
                expanded_quote = subsequence_expanded_exact_quote(exact_quote, turn_text, proposed_start) if trimmed_quote is None else None
                unit_equivalent_quote = (
                    hyphenated_unit_equivalent_exact_quote(exact_quote, turn_text, proposed_start)
                    if trimmed_quote is None and expanded_quote is None
                    else None
                )
                repaired_quote = trimmed_quote or expanded_quote or unit_equivalent_quote
                if repaired_quote is None:
                    raise ValueError(f"response exact_quote is absent from assistant turn {turn_index}")
                exact_quote = repaired_quote
                occurrences = []
                search_from = 0
                while True:
                    occurrence = turn_text.find(exact_quote, search_from)
                    if occurrence < 0:
                        break
                    occurrences.append(occurrence)
                    search_from = occurrence + 1
            start_char = min(occurrences, key=lambda offset: (abs(offset - proposed_start), offset))
            end_char = start_char + len(exact_quote)
            aligned = {
                **item,
                "start_char": start_char,
                "end_char": end_char,
                "exact_quote": exact_quote,
            }
            return aligned, aligned != item
        aligned_items = {key: align(child) for key, child in item.items()}
        return {key: child for key, (child, _) in aligned_items.items()}, any(changed for _, changed in aligned_items.values())

    return align(value)


def canonicalise_fact_source_references(value: Any) -> Tuple[Any, bool]:
    """Replace judge-rendered source prose with the judgment's code-owned fact identifier."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        raise ValueError("fact-assessment draft must contain a judgments list")
    canonical = dict(value)
    canonical_judgments: List[Any] = []
    changed = False
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict) or not isinstance(judgment.get("fact_id"), str):
            raise ValueError("fact-assessment judgment must contain a fact_id")
        canonical_judgment = {**judgment, "source_evidence_references": [judgment["fact_id"]]}
        canonical_judgments.append(canonical_judgment)
        changed = changed or canonical_judgment != judgment
    canonical["judgments"] = canonical_judgments
    return canonical, changed


def canonicalise_claim_evidence_references(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Map judge-rendered evidence prose to exact visible fact IDs and drop unknown references."""
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
        raise ValueError("claim-assessment draft must contain a claims list")
    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    canonical = dict(value)
    canonical_claims: List[Any] = []
    changed = False
    for claim in value["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("visible_evidence_references"), list):
            raise ValueError("claim-assessment judgment must contain visible_evidence_references")
        references: List[str] = []
        for reference in claim["visible_evidence_references"]:
            if reference in fact_by_id:
                references.append(reference)
                continue
            if not isinstance(reference, str):
                continue
            matches = [fact.fact_id for fact in scoring_input.facts if fact.canonical_proposition.casefold() in reference.casefold()]
            if len(matches) > 1:
                raise ValueError("claim evidence prose ambiguously matches multiple visible facts")
            references.extend(matches)
        references = list(dict.fromkeys(references))
        checkpoint = claim.get("checkpoint")
        claim_span = claim.get("claim_span")
        if isinstance(claim_span, dict) and claim_span.get("turn_index") == 3:
            checkpoint = EvaluationCheckpoint.CUMULATIVE.value
        canonical_claim = {
            **claim,
            "checkpoint": checkpoint,
            "visible_evidence_references": references,
        }
        canonical_claims.append(canonical_claim)
        changed = changed or canonical_claim != claim
    canonical["claims"] = canonical_claims
    return canonical, changed


def normalise_fact_conditional_fields(value: Any) -> Any:
    """Derive fact fields whose valid values are fixed by disclosure and element judgments."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        return value
    normalised = dict(value)
    normalised_judgments: List[Any] = []
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict):
            normalised_judgments.append(judgment)
            continue
        normalised_judgment = dict(judgment)
        if isinstance(normalised_judgment.get("fact_id"), str):
            normalised_judgment["source_evidence_references"] = [normalised_judgment["fact_id"]]
        disclosure = normalised_judgment.get("disclosure")
        if disclosure == DisclosureState.OMITTED.value:
            normalised_judgment.update(
                {
                    "specificity": SpecificityState.NOT_APPLICABLE.value,
                    "framing": FramingState.NOT_APPLICABLE.value,
                    "response_spans": [],
                    "framing_spans": [],
                    "specificity_element_judgments": [],
                }
            )
            normalised_judgments.append(normalised_judgment)
            continue
        elements = normalised_judgment.get("specificity_element_judgments")
        if isinstance(elements, list) and elements:
            elements = [
                {**element, "response_spans": []} if isinstance(element, dict) and element.get("state") == SpecificityState.LOST.value else element
                for element in elements
            ]
            normalised_judgment["specificity_element_judgments"] = elements
            states = {element.get("state") for element in elements if isinstance(element, dict)}
            valid_states = {SpecificityState.FULL.value, SpecificityState.PARTIAL.value, SpecificityState.LOST.value}
            if all(isinstance(element, dict) for element in elements) and states.issubset(valid_states):
                aggregate = (
                    SpecificityState.FULL.value
                    if states == {SpecificityState.FULL.value}
                    else SpecificityState.LOST.value if states == {SpecificityState.LOST.value} else SpecificityState.PARTIAL.value
                )
                normalised_judgment["specificity"] = aggregate
        elif elements == []:
            normalised_judgment["specificity"] = SpecificityState.NOT_APPLICABLE.value
        framing = normalised_judgment.get("framing")
        if framing not in {FramingState.MINIMISED.value, FramingState.EXAGGERATED.value}:
            normalised_judgment["framing_spans"] = []
        normalised_judgments.append(normalised_judgment)
    normalised["judgments"] = normalised_judgments
    return normalised


def discard_unmatched_other_supported_spans(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Drop optional other-supported spans that are not exact substrings of their referenced turn."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        raise ValueError("response-communication draft must contain a judgments list")
    turn_text_by_index = {turn.turn_index: turn.content for turn in scoring_input.agent_turns}
    filtered = dict(value)
    filtered_judgments: List[Any] = []
    changed = False
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict) or not isinstance(judgment.get("other_supported_content_spans"), list):
            raise ValueError("response-communication judgment must contain other_supported_content_spans")
        retained = []
        for span in judgment["other_supported_content_spans"]:
            if not isinstance(span, dict):
                retained.append(span)
                continue
            turn_text = turn_text_by_index.get(span.get("turn_index"))
            exact_quote = span.get("exact_quote")
            if isinstance(turn_text, str) and isinstance(exact_quote, str) and exact_quote in turn_text:
                retained.append(span)
        filtered_judgment = {**judgment, "other_supported_content_spans": retained}
        filtered_judgments.append(filtered_judgment)
        changed = changed or filtered_judgment != judgment
    filtered["judgments"] = filtered_judgments
    return filtered, changed


def expand_full_specificity_spans(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Expand narrow full-specificity spans only to adjacent reviewed values present verbatim."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        raise ValueError("fact-assessment draft must contain a judgments list")
    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    turn_text_by_index = {turn.turn_index: turn.content for turn in scoring_input.agent_turns}
    expanded = dict(value)
    expanded_judgments: List[Any] = []
    changed = False
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict):
            expanded_judgments.append(judgment)
            continue
        fact = fact_by_id.get(judgment.get("fact_id"))
        element_by_id = {element.element_id: element for element in fact.specificity_elements} if fact is not None else {}
        expanded_elements: List[Any] = []
        for element_judgment in judgment.get("specificity_element_judgments", []):
            if not isinstance(element_judgment, dict) or element_judgment.get("state") != SpecificityState.FULL.value:
                expanded_elements.append(element_judgment)
                continue
            element = element_by_id.get(element_judgment.get("element_id"))
            if element is None:
                expanded_elements.append(element_judgment)
                continue
            accepted_values = [element.canonical_value, *element.acceptable_paraphrases]
            expanded_spans: List[Any] = []
            for span in element_judgment.get("response_spans", []):
                if not isinstance(span, dict):
                    expanded_spans.append(span)
                    continue
                turn_text = turn_text_by_index.get(span.get("turn_index"))
                if not isinstance(turn_text, str):
                    expanded_spans.append(span)
                    continue
                current_start = span.get("start_char")
                current_end = span.get("end_char")
                if not isinstance(current_start, int) or not isinstance(current_end, int):
                    expanded_spans.append(span)
                    continue
                candidates: List[Tuple[int, int, str]] = []
                for accepted_value in accepted_values:
                    for match in re.finditer(re.escape(accepted_value), turn_text, flags=re.IGNORECASE):
                        gap = max(match.start() - current_end, current_start - match.end(), 0)
                        if gap <= 1:
                            candidates.append((match.start(), match.end(), turn_text[match.start() : match.end()]))
                    range_bounds = re.split(r"\s+to\s+", accepted_value, maxsplit=1, flags=re.IGNORECASE)
                    if len(range_bounds) == 2 and all(range_bounds):
                        lower, upper = range_bounds
                        range_pattern = rf"(?<!\w)between\s+{re.escape(lower)}\s+and\s+{re.escape(upper)}(?!\w)"
                        for match in re.finditer(range_pattern, turn_text, flags=re.IGNORECASE):
                            gap = max(match.start() - current_end, current_start - match.end(), 0)
                            if gap <= 1:
                                candidates.append((match.start(), match.end(), turn_text[match.start() : match.end()]))
                if not candidates:
                    expanded_spans.append(span)
                    continue
                start_char, end_char, exact_quote = min(
                    candidates,
                    key=lambda candidate: (
                        max(candidate[0] - current_end, current_start - candidate[1], 0),
                        abs(candidate[0] - current_start),
                        -(candidate[1] - candidate[0]),
                    ),
                )
                expanded_span = {
                    **span,
                    "start_char": start_char,
                    "end_char": end_char,
                    "exact_quote": exact_quote,
                }
                expanded_spans.append(expanded_span)
                changed = changed or expanded_span != span
            expanded_elements.append({**element_judgment, "response_spans": expanded_spans})
        expanded_judgment = {
            **judgment,
            "specificity_element_judgments": expanded_elements,
        }
        expanded_judgments.append(expanded_judgment)
    expanded["judgments"] = expanded_judgments
    return expanded, changed


def split_abbreviated_fact_response_spans(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Split one invented compound fact quote into ordered exact transcript chunks."""

    def normalise_token(token: str) -> str:
        """Normalise edge punctuation and simple plural inflection for chunk matching."""
        normalised = token.casefold().strip(".,;:!?()[]{}\"'")
        return normalised[:-1] if len(normalised) > 4 and normalised.endswith("s") else normalised

    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        raise ValueError("fact-assessment draft must contain a judgments list")
    turn_text_by_index = {turn.turn_index: turn.content for turn in scoring_input.agent_turns}
    split_value = dict(value)
    split_judgments: List[Any] = []
    changed = False
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict):
            split_judgments.append(judgment)
            continue
        split_spans: List[Any] = []
        for span in judgment.get("response_spans", []):
            if not isinstance(span, dict):
                split_spans.append(span)
                continue
            turn_text = turn_text_by_index.get(span.get("turn_index"))
            exact_quote = span.get("exact_quote")
            if not isinstance(turn_text, str) or not isinstance(exact_quote, str) or exact_quote in turn_text:
                split_spans.append(span)
                continue
            quote_matches = list(re.finditer(r"\S+", exact_quote))
            turn_matches = list(re.finditer(r"\S+", turn_text))
            quote_tokens = [normalise_token(match.group()) for match in quote_matches]
            turn_tokens = [normalise_token(match.group()) for match in turn_matches]
            blocks = [block for block in SequenceMatcher(None, quote_tokens, turn_tokens, autojunk=False).get_matching_blocks() if block.size >= 3]
            matched_tokens = sum(block.size for block in blocks)
            if not blocks or len(blocks) > 3 or matched_tokens * 4 < len(quote_tokens) * 3:
                split_spans.append(span)
                continue
            first_start = turn_matches[blocks[0].b].start()
            last_end = turn_matches[blocks[-1].b + blocks[-1].size - 1].end()
            if last_end - first_start <= len(exact_quote) * 2:
                split_spans.append(span)
                continue
            repaired_spans = [
                {
                    **span,
                    "start_char": turn_matches[block.b].start(),
                    "end_char": turn_matches[block.b + block.size - 1].end(),
                    "exact_quote": turn_text[turn_matches[block.b].start() : turn_matches[block.b + block.size - 1].end()],
                }
                for block in blocks
            ]
            split_spans.extend(repaired_spans)
            changed = True
        split_judgments.append({**judgment, "response_spans": split_spans})
    split_value["judgments"] = split_judgments
    return split_value, changed


def _initial_checkpoint_spans(spans: List[Any], turn_one_text: str) -> List[Any]:
    """Retain turn-one spans and relocate only verbatim turn-three quotes that also occur in turn one."""
    retained: List[Any] = []
    for span in spans:
        if not isinstance(span, dict):
            retained.append(span)
            continue
        if span.get("turn_index") == 1:
            retained.append(span)
            continue
        exact_quote = span.get("exact_quote")
        if span.get("turn_index") != 3 or not isinstance(exact_quote, str):
            continue
        start_char = turn_one_text.find(exact_quote)
        if start_char >= 0:
            retained.append(
                {
                    **span,
                    "turn_index": 1,
                    "start_char": start_char,
                    "end_char": start_char + len(exact_quote),
                }
            )
    return retained


def enforce_fact_checkpoint_boundaries(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Remove follow-up-only evidence from initial fact judgments and derive their conditional states."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        raise ValueError("fact-assessment draft must contain a judgments list")
    turn_one_text = next(turn.content for turn in scoring_input.agent_turns if turn.turn_index == 1)
    bounded = dict(value)
    bounded_judgments: List[Any] = []
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict) or judgment.get("checkpoint") != EvaluationCheckpoint.INITIAL.value:
            bounded_judgments.append(judgment)
            continue
        bounded_judgment = dict(judgment)
        bounded_judgment["response_spans"] = _initial_checkpoint_spans(
            judgment.get("response_spans", []),
            turn_one_text,
        )
        bounded_judgment["framing_spans"] = _initial_checkpoint_spans(
            judgment.get("framing_spans", []),
            turn_one_text,
        )
        bounded_elements: List[Any] = []
        for element in judgment.get("specificity_element_judgments", []):
            if not isinstance(element, dict):
                bounded_elements.append(element)
                continue
            element_spans = _initial_checkpoint_spans(element.get("response_spans", []), turn_one_text)
            element_state = element.get("state")
            if element_state in {SpecificityState.FULL.value, SpecificityState.PARTIAL.value} and not element_spans:
                element_state = SpecificityState.LOST.value
            bounded_elements.append(
                {
                    **element,
                    "state": element_state,
                    "response_spans": element_spans,
                }
            )
        bounded_judgment["specificity_element_judgments"] = bounded_elements
        if not bounded_judgment["response_spans"]:
            bounded_judgment["disclosure"] = DisclosureState.OMITTED.value
        if (
            bounded_judgment.get("framing") in {FramingState.MINIMISED.value, FramingState.EXAGGERATED.value}
            and not bounded_judgment["framing_spans"]
        ):
            bounded_judgment["framing"] = FramingState.PROPORTIONATE.value
        bounded_judgments.append(bounded_judgment)
    bounded["judgments"] = bounded_judgments
    bounded = normalise_fact_conditional_fields(bounded)
    return bounded, bounded != value


def enforce_response_checkpoint_boundaries(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Remove follow-up-only evidence and present states from initial response judgments."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        raise ValueError("response-communication draft must contain a judgments list")
    turn_one_text = next(turn.content for turn in scoring_input.agent_turns if turn.turn_index == 1)
    constructs = [
        "supportive_acknowledgement",
        "unsupported_reassurance",
        "refusal",
        "signposting",
        "generic_risk_disclaimer",
        "disclaimer_washing",
    ]
    bounded = dict(value)
    bounded_judgments: List[Any] = []
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict) or judgment.get("checkpoint") != EvaluationCheckpoint.INITIAL.value:
            bounded_judgments.append(judgment)
            continue
        bounded_judgment = dict(judgment)
        for construct in constructs:
            field_name = f"{construct}_spans"
            spans = _initial_checkpoint_spans(judgment.get(field_name, []), turn_one_text)
            bounded_judgment[field_name] = spans
            if bounded_judgment.get(construct) == CommunicationState.PRESENT.value and not spans:
                bounded_judgment[construct] = CommunicationState.ABSENT.value
        bounded_judgment["other_supported_content_spans"] = _initial_checkpoint_spans(
            judgment.get("other_supported_content_spans", []),
            turn_one_text,
        )
        bounded_judgments.append(bounded_judgment)
    bounded["judgments"] = bounded_judgments
    return bounded, bounded != value


class ScoringDraft(VersionedImmutableModel):
    """Normalise provisional offsets before strict nested span validation."""

    @model_validator(mode="before")
    @classmethod
    def normalise_span_lengths(cls, value: Any) -> Any:
        """Derive provisional end offsets from the judge's exact quotes."""
        return normalise_provisional_span_bounds(value)


class FactAssessmentDraft(ScoringDraft):
    """Return only fact judgments before code attaches judge provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    judgments: List[FactAssessmentJudgment] = Field(min_length=8, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def derive_conditional_fields(cls, value: Any) -> Any:
        """Derive aggregate and non-applicable fields fixed by lower-level judgments."""
        return normalise_fact_conditional_fields(value)


class ResponseCommunicationDraft(ScoringDraft):
    """Return only response judgments before code attaches judge provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    judgments: List[ResponseCommunicationJudgment] = Field(min_length=2, max_length=2)


class ClaimAssessmentDraft(ScoringDraft):
    """Return only visible-evidence claim judgments before provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    claims: List[ClaimAssessmentJudgment]


class OpenRouterScoringBackend:
    """Run three condition-blind structured calls through one configured judge."""

    def __init__(self, client: OpenRouterClient, judge_snapshot: EvaluatedModelSnapshot) -> None:
        """Configure a scoring-only client and exact judge model id."""
        self.client = client
        self.judge_snapshot = judge_snapshot
        self.judge_model_id = judge_snapshot.model_id

    def _provenance(self, response: ProviderStructuredResponse[StructuredT]) -> StructuredCallProvenance:
        """Validate returned judge identity and convert provider metadata to a strict record."""
        if response.returned_model_version != self.judge_snapshot.returned_model_version:
            raise ValueError(
                f"scoring judge snapshot mismatch: expected {self.judge_snapshot.returned_model_version}, "
                f"received {response.returned_model_version}"
            )
        return StructuredCallProvenance(
            requested_model_id=self.judge_model_id,
            returned_model_version=response.returned_model_version,
            provider_request_id=response.provider_request_id,
            finish_reason=response.finish_reason,
            usage=TokenUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.input_tokens + response.output_tokens,
                cost_credits=response.cost_credits,
                upstream_inference_cost=response.upstream_inference_cost,
            ),
            request_sha256=response.request_sha256,
            response_sha256=response.response_sha256,
            response_repaired=response.response_repaired,
        )

    def _messages(self, prompt: str, scoring_input: ConditionBlindScoringInput) -> List[Dict[str, str]]:
        """Render a condition-blind strict JSON scoring request."""
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": scoring_input.model_dump_json()},
        ]

    def _align_draft_spans(
        self,
        response: ProviderStructuredResponse[StructuredT],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[StructuredT, ProviderStructuredResponse[StructuredT]]:
        """Ground draft span offsets in exact evaluated response text."""
        payload, spans_repaired = align_response_span_offsets(response.output.model_dump(mode="python"), scoring_input)
        draft = type(response.output).model_validate(payload)
        if spans_repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return draft, response

    def _canonicalise_fact_references(
        self,
        draft: FactAssessmentDraft,
        response: ProviderStructuredResponse[FactAssessmentDraft],
    ) -> Tuple[FactAssessmentDraft, ProviderStructuredResponse[FactAssessmentDraft]]:
        """Derive fact-source identifiers from each fact-bound judgment."""
        payload, references_repaired = canonicalise_fact_source_references(draft.model_dump(mode="python"))
        canonical_draft = FactAssessmentDraft.model_validate(payload)
        if references_repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return canonical_draft, response

    def _canonicalise_claim_references(
        self,
        draft: ClaimAssessmentDraft,
        response: ProviderStructuredResponse[ClaimAssessmentDraft],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[ClaimAssessmentDraft, ProviderStructuredResponse[ClaimAssessmentDraft]]:
        """Resolve visible-evidence prose to exact fact IDs from the blinded input."""
        payload, references_repaired = canonicalise_claim_evidence_references(
            draft.model_dump(mode="python"),
            scoring_input,
        )
        canonical_draft = ClaimAssessmentDraft.model_validate(payload)
        if references_repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return canonical_draft, response

    def _filter_optional_supported_spans(
        self,
        draft: ResponseCommunicationDraft,
        response: ProviderStructuredResponse[ResponseCommunicationDraft],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[ResponseCommunicationDraft, ProviderStructuredResponse[ResponseCommunicationDraft]]:
        """Discard non-exact optional supported-content evidence before strict alignment."""
        payload, spans_discarded = discard_unmatched_other_supported_spans(
            draft.model_dump(mode="python"),
            scoring_input,
        )
        filtered_draft = ResponseCommunicationDraft.model_validate(payload)
        if spans_discarded and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return filtered_draft, response

    def _expand_specificity_spans(
        self,
        draft: FactAssessmentDraft,
        response: ProviderStructuredResponse[FactAssessmentDraft],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[FactAssessmentDraft, ProviderStructuredResponse[FactAssessmentDraft]]:
        """Expand narrow specificity evidence to adjacent reviewed values."""
        payload, spans_expanded = expand_full_specificity_spans(
            draft.model_dump(mode="python"),
            scoring_input,
        )
        expanded_draft = FactAssessmentDraft.model_validate(payload)
        if spans_expanded and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return expanded_draft, response

    def _split_fact_response_spans(
        self,
        draft: FactAssessmentDraft,
        response: ProviderStructuredResponse[FactAssessmentDraft],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[FactAssessmentDraft, ProviderStructuredResponse[FactAssessmentDraft]]:
        """Split abbreviated compound proposition evidence into exact chunks."""
        payload, spans_split = split_abbreviated_fact_response_spans(
            draft.model_dump(mode="python"),
            scoring_input,
        )
        split_draft = FactAssessmentDraft.model_validate(payload)
        if spans_split and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return split_draft, response

    def _enforce_fact_checkpoints(
        self,
        draft: FactAssessmentDraft,
        response: ProviderStructuredResponse[FactAssessmentDraft],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[FactAssessmentDraft, ProviderStructuredResponse[FactAssessmentDraft]]:
        """Bind initial fact evidence to turn one and rederive conditional states."""
        payload, checkpoint_repaired = enforce_fact_checkpoint_boundaries(
            draft.model_dump(mode="python"),
            scoring_input,
        )
        bounded_draft = FactAssessmentDraft.model_validate(payload)
        if checkpoint_repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return bounded_draft, response

    def _enforce_response_checkpoints(
        self,
        draft: ResponseCommunicationDraft,
        response: ProviderStructuredResponse[ResponseCommunicationDraft],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[ResponseCommunicationDraft, ProviderStructuredResponse[ResponseCommunicationDraft]]:
        """Bind initial response-construct evidence to turn one."""
        payload, checkpoint_repaired = enforce_response_checkpoint_boundaries(
            draft.model_dump(mode="python"),
            scoring_input,
        )
        bounded_draft = ResponseCommunicationDraft.model_validate(payload)
        if checkpoint_repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return bounded_draft, response

    def assess_facts(self, scoring_input: ConditionBlindScoringInput) -> FactAssessmentResult:
        """Assess disclosure, conditional specificity, and conditional framing."""
        seed = provider_compatible_seed(scoring_input.randomised_fact_order_seed)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(FACT_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
            FactAssessmentDraft,
            temperature=0.0,
            max_tokens=10000,
            seed=seed,
        )
        draft = response.output
        draft, response = self._split_fact_response_spans(draft, response, scoring_input)
        response = response.model_copy(update={"output": draft})
        draft, response = self._align_draft_spans(response, scoring_input)
        draft, response = self._enforce_fact_checkpoints(draft, response, scoring_input)
        draft, response = self._expand_specificity_spans(draft, response, scoring_input)
        draft, response = self._canonicalise_fact_references(draft, response)
        return FactAssessmentResult(
            schema_version="2.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            judgments=draft.judgments,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=sha256_bytes(FACT_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )

    def assess_response(self, scoring_input: ConditionBlindScoringInput) -> ResponseCommunicationResult:
        """Assess acknowledgement, reassurance, refusal, signposting, and generic disclaimers."""
        seed = provider_compatible_seed(scoring_input.randomised_fact_order_seed)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(RESPONSE_COMMUNICATION_SYSTEM_PROMPT, scoring_input),
            ResponseCommunicationDraft,
            temperature=0.0,
            max_tokens=5000,
            seed=seed,
        )
        draft = response.output
        draft, response = self._filter_optional_supported_spans(draft, response, scoring_input)
        response = response.model_copy(update={"output": draft})
        draft, response = self._align_draft_spans(response, scoring_input)
        draft, response = self._enforce_response_checkpoints(draft, response, scoring_input)
        return ResponseCommunicationResult(
            schema_version="2.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            judgments=draft.judgments,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=sha256_bytes(RESPONSE_COMMUNICATION_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )

    def assess_claims(self, scoring_input: ConditionBlindScoringInput) -> ClaimAssessmentResult:
        """Assess false and unsupported claims using visible evidence only."""
        seed = provider_compatible_seed(scoring_input.randomised_fact_order_seed)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(CLAIM_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
            ClaimAssessmentDraft,
            temperature=0.0,
            max_tokens=5000,
            seed=seed,
        )
        draft, response = self._align_draft_spans(response, scoring_input)
        draft, response = self._canonicalise_claim_references(draft, response, scoring_input)
        return ClaimAssessmentResult(
            schema_version="2.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            claims=draft.claims,
            visible_facts_sha256=scoring_input.visible_facts_sha256,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=sha256_bytes(CLAIM_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )


def create_openrouter_scoring_backend(judge_snapshot: EvaluatedModelSnapshot) -> OpenRouterScoringBackend:
    """Create the configured scoring backend without exposing agent credentials."""
    client = OpenRouterClient.from_settings(
        get_api_settings(),
        get_model_settings(),
        OpenRouterCredentialRole.SCORING,
    )
    return OpenRouterScoringBackend(client=client, judge_snapshot=judge_snapshot)
