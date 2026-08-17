"""Response-contract parsing, adherence, and truncation checks."""

from __future__ import annotations

import json
import re
from typing import List, Optional

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
    """Recover one unambiguous fenced-JSON selection while retaining format non-adherence."""
    strict = parse_exact_budget_output(raw_response, expected_k, valid_fact_ids)
    if strict.structurally_valid:
        return strict
    match = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw_response, flags=re.IGNORECASE | re.DOTALL)
    if match is None:
        return strict
    recovered = parse_exact_budget_output(match.group(1), expected_k, valid_fact_ids)
    if not recovered.structurally_valid:
        return strict
    reason = "structured selection recovered from one complete Markdown fence; original format remains non-adherent"
    if not recovered.selection_usable and recovered.reason is not None:
        reason = f"{reason}; {recovered.reason}"
    return recovered.model_copy(update={"adherent": False, "format_adherent": False, "reason": reason})


def extract_exact_budget_answer_text(raw_response: str) -> Optional[str]:
    """Extract prose from strict or wholly fenced exact-budget JSON without changing adherence."""
    candidates = [raw_response]
    match = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", raw_response, flags=re.IGNORECASE | re.DOTALL)
    if match is not None:
        candidates.append(match.group(1))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            if not isinstance(payload, dict) or list(payload) != ["selected_fact_ids", "answer_text"]:
                continue
            output = ExactBudgetOutput.model_validate(payload)
            return output.answer_text
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            continue
    return None


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
