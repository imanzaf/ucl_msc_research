"""Response-contract parsing, adherence, and truncation checks."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from pydantic import Field, ValidationError, model_validator

from srcv2.common import ImmutableModel


class ExactBudgetOutput(ImmutableModel):
    """Represent structured fact selection followed by prose realization."""

    selected_fact_ids: List[str]
    answer_text: str

    @model_validator(mode="after")
    def validate_distinct_ids(self) -> "ExactBudgetOutput":
        """Require selected identifiers to be distinct."""
        if len(set(self.selected_fact_ids)) != len(self.selected_fact_ids):
            raise ValueError("selected fact identifiers must be distinct")
        return self


class AdherenceResult(ImmutableModel):
    """Record structural and treatment adherence without regenerating output."""

    structurally_valid: bool
    adherent: bool
    format_adherent: bool = True
    selection_usable: bool = False
    selected_fact_ids: Optional[List[str]] = None
    answer_text: Optional[str] = None
    word_count: Optional[int] = Field(default=None, ge=0)
    truncated: bool = False
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_selection_disposition(self) -> "AdherenceResult":
        """Require usable exact-budget selections to expose their selected identifiers."""
        if self.selection_usable and self.selected_fact_ids is None:
            raise ValueError("usable selection requires selected fact identifiers")
        return self


def parse_exact_budget_output(raw_response: str, expected_k: int, valid_fact_ids: List[str]) -> AdherenceResult:
    """Parse exact-budget JSON strictly and retain malformed output as non-adherence."""
    try:
        payload = json.loads(raw_response)
        if not isinstance(payload, dict) or list(payload) != ["selected_fact_ids", "answer_text"]:
            raise ValueError("structured output fields must place selected_fact_ids before answer_text")
        output = ExactBudgetOutput.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        return AdherenceResult(
            structurally_valid=False,
            adherent=False,
            format_adherent=False,
            reason=f"malformed structured output: {type(error).__name__}",
        )
    valid = set(valid_fact_ids)
    ids = output.selected_fact_ids
    if len(ids) != expected_k:
        return AdherenceResult(
            structurally_valid=True,
            adherent=False,
            selection_usable=False,
            selected_fact_ids=ids,
            answer_text=output.answer_text,
            reason=f"selected {len(ids)} facts; expected {expected_k}",
        )
    unknown = sorted(set(ids) - valid)
    if unknown:
        return AdherenceResult(
            structurally_valid=True,
            adherent=False,
            selection_usable=False,
            selected_fact_ids=ids,
            answer_text=output.answer_text,
            reason="unknown fact identifiers: " + ", ".join(unknown),
        )
    return AdherenceResult(
        structurally_valid=True,
        adherent=True,
        selection_usable=True,
        selected_fact_ids=ids,
        answer_text=output.answer_text,
    )


def recover_exact_budget_selection(raw_response: str, expected_k: int, valid_fact_ids: List[str]) -> AdherenceResult:
    """Recover one unambiguous selection while retaining original format non-adherence."""
    strict = parse_exact_budget_output(raw_response, expected_k, valid_fact_ids)
    if strict.structurally_valid:
        return strict
    candidates = _json_object_candidates(raw_response)
    recovered = _unique_embedded_result(candidates, expected_k, valid_fact_ids)
    if recovered is not None:
        reason = "selection recovered from one unambiguous embedded JSON object; original format remains non-adherent"
        if recovered.reason is not None:
            reason = f"{reason}; {recovered.reason}"
        return recovered.model_copy(update={"adherent": False, "format_adherent": False, "reason": reason})
    if candidates:
        return strict.model_copy(update={"reason": "complete JSON objects do not contain one unambiguous ordered selection"})
    mentioned_ids = _mentioned_fact_ids(raw_response, valid_fact_ids)
    labelled_answer = _labelled_answer_text(raw_response)
    has_selection_label = re.search(r"(?i)selected(?:_|\s+)fact(?:_|\s+)ids", raw_response) is not None
    if len(mentioned_ids) == expected_k and has_selection_label:
        return AdherenceResult(
            structurally_valid=True,
            adherent=False,
            format_adherent=False,
            selection_usable=True,
            selected_fact_ids=mentioned_ids,
            answer_text=labelled_answer,
            reason="selection recovered from unambiguous labelled fields; original format remains non-adherent",
        )
    return strict


def extract_exact_budget_answer_text(raw_response: str) -> Optional[str]:
    """Extract answer prose from one unambiguous structured representation."""
    outputs: Dict[Tuple[Tuple[str, ...], str], ExactBudgetOutput] = {}
    for candidate in _json_object_candidates(raw_response):
        try:
            payload = json.loads(candidate)
            if not isinstance(payload, dict) or list(payload) != ["selected_fact_ids", "answer_text"]:
                continue
            output = ExactBudgetOutput.model_validate(payload)
            outputs[(tuple(output.selected_fact_ids), output.answer_text)] = output
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            continue
    if len(outputs) == 1:
        return next(iter(outputs.values())).answer_text
    if outputs:
        return None
    return _labelled_answer_text(raw_response)


def _json_object_candidates(raw_response: str) -> List[str]:
    """Return complete JSON objects embedded anywhere in a response without rewriting them."""
    decoder = json.JSONDecoder()
    candidates: List[str] = []
    seen = set()
    for match in re.finditer(r"\{", raw_response):
        start = match.start()
        try:
            _, end = decoder.raw_decode(raw_response[start:])
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        candidate = raw_response[start : start + end]
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def _unique_embedded_result(candidates: List[str], expected_k: int, valid_fact_ids: List[str]) -> Optional[AdherenceResult]:
    """Return one unique selected-ID sequence or reject candidates that disagree on selection."""
    parsed_results: List[AdherenceResult] = []
    for candidate in candidates:
        parsed = parse_exact_budget_output(candidate, expected_k, valid_fact_ids)
        if not parsed.structurally_valid or parsed.selected_fact_ids is None:
            continue
        parsed_results.append(parsed)
    usable_results = [result for result in parsed_results if result.selection_usable]
    relevant_results = usable_results or parsed_results
    results: Dict[Tuple[str, ...], List[AdherenceResult]] = {}
    for parsed in relevant_results:
        if parsed.selected_fact_ids is None:
            continue
        results.setdefault(tuple(parsed.selected_fact_ids), []).append(parsed)
    if len(results) != 1:
        return None
    matching = next(iter(results.values()))
    answers = {result.answer_text for result in matching}
    if len(answers) == 1:
        return matching[0]
    return matching[0].model_copy(update={"answer_text": None, "reason": "multiple answer representations share the same selected IDs"})


def _mentioned_fact_ids(raw_response: str, valid_fact_ids: List[str]) -> List[str]:
    """Return valid identifiers in their first-mentioned order for ambiguity checks."""
    if not valid_fact_ids:
        return []
    pattern = (
        r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(fact_id) for fact_id in sorted(valid_fact_ids, key=len, reverse=True)) + r")(?![A-Za-z0-9_])"
    )
    return list(dict.fromkeys(re.findall(pattern, raw_response)))


def _labelled_answer_text(raw_response: str) -> Optional[str]:
    """Extract answer text from an unambiguous labelled field without changing its content."""
    json_string = re.search(r'"answer_text"\s*:\s*"(.*)"\s*\}?\s*(?:```)?\s*$', raw_response, flags=re.DOTALL)
    if json_string is not None:
        token = '"' + json_string.group(1) + '"'
        token = token.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        try:
            value = json.loads(token)
        except (json.JSONDecodeError, TypeError, ValueError):
            value = None
        if isinstance(value, str) and value.strip():
            return value
    heading = re.search(r"(?im)^#{1,6}\s*Answer(?:\s+Text)?\s*:\s*$", raw_response)
    if heading is None:
        partial = re.search(r'"answer_text"\s*:\s*"(.*)$', raw_response, flags=re.DOTALL)
        if partial is None:
            return None
        answer = partial.group(1).strip()
        return answer or None
    answer = raw_response[heading.end() :].strip()
    return answer or None


def count_words(text: str) -> int:
    """Count word-like tokens consistently for natural word-budget adherence."""
    return len(re.findall(r"\b[\w£$€%'-]+\b", text, flags=re.UNICODE))


def check_word_budget(text: str, budget: int, finish_reason: Optional[str]) -> AdherenceResult:
    """Score word-cap adherence and provider-reported length truncation separately."""
    words = count_words(text)
    truncated = finish_reason in {"length", "max_tokens"}
    return AdherenceResult(
        structurally_valid=True,
        adherent=words <= budget,
        answer_text=text,
        word_count=words,
        truncated=truncated,
        reason=None if words <= budget else f"response contains {words} words; cap is {budget}",
    )
