"""Structured adherence, word-limit, truncation, and retry-policy tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from openai import BadRequestError
from pydantic import ValidationError

from src.experiments.matrix import MatrixAssignment
from src.experiments.responses import check_word_budget, extract_exact_budget_answer_text, parse_exact_budget_output, recover_exact_budget_selection
from src.experiments.runner import _response_metadata
from src.llm.openrouter import OpenRouterClient, ProviderReply
from src.models.enums import Affect, CommercialInterestInstruction, CommercialInterestTask, ExactFactBudget, ExecutionStatus
from src.models.experiments import AttemptMetadata, CommercialInterestCell, RunUnit


def test_exact_budget_requires_distinct_valid_ids_and_field_order() -> None:
    """Treat malformed, reordered, duplicate, wrong-k, and unknown IDs as non-adherence."""
    valid = [f"F{index}" for index in range(1, 7)]
    assert parse_exact_budget_output('{"selected_fact_ids":["F1","F2"],"answer_text":"Answer"}', 2, valid).adherent
    assert not parse_exact_budget_output('{"answer_text":"Answer","selected_fact_ids":["F1","F2"]}', 2, valid).structurally_valid
    assert not parse_exact_budget_output('{"selected_fact_ids":["F1","F1"],"answer_text":"Answer"}', 2, valid).structurally_valid
    assert not parse_exact_budget_output('{"selected_fact_ids":["F1"],"answer_text":"Answer"}', 2, valid).adherent
    assert not parse_exact_budget_output('{"selected_fact_ids":["F1","F9"],"answer_text":"Answer"}', 2, valid).adherent
    assert not parse_exact_budget_output("not json", 2, valid).structurally_valid


def test_embedded_exact_budget_selection_is_usable_but_format_nonadherent() -> None:
    """Recover one unambiguous embedded JSON object without changing its adherence label."""
    valid = [f"F{index}" for index in range(1, 7)]
    fenced = '```json\n{"selected_fact_ids":["F1","F2"],"answer_text":"Answer"}\n```'
    recovered = recover_exact_budget_selection(fenced, 2, valid)
    assert recovered.structurally_valid and recovered.selection_usable
    assert not recovered.adherent and not recovered.format_adherent
    assert recovered.selected_fact_ids == ["F1", "F2"]
    wrapped = "Prose before " + fenced + " prose after"
    assert recover_exact_budget_selection(wrapped, 2, valid).selection_usable
    assert extract_exact_budget_answer_text(fenced) == "Answer"
    assert extract_exact_budget_answer_text(wrapped) == "Answer"


def test_exact_budget_recovery_rejects_conflicting_selection_fields() -> None:
    """Reject different structured selections while treating one selected-ID field as authoritative."""
    valid = [f"F{index}" for index in range(1, 7)]
    first = '{"selected_fact_ids":["F1","F2"],"answer_text":"First"}'
    second = '{"selected_fact_ids":["F3","F4"],"answer_text":"Second"}'
    assert not recover_exact_budget_selection(first + "\n" + second, 2, valid).selection_usable
    assert extract_exact_budget_answer_text(first + "\n" + second) is None
    assert recover_exact_budget_selection("F3\n" + first, 2, valid).selection_usable


def test_exact_budget_recovery_accepts_unambiguous_labelled_fields() -> None:
    """Recover explicit labelled IDs and answer text while preserving format non-adherence."""
    valid = [f"F{index}" for index in range(1, 7)]
    raw = '### Selected Fact IDs:\n["F1", "F2"]\n\n### Answer Text:\nThe answer stays unchanged.'
    recovered = recover_exact_budget_selection(raw, 2, valid)
    assert recovered.selection_usable and not recovered.adherent
    assert recovered.selected_fact_ids == ["F1", "F2"]
    assert recovered.answer_text == "The answer stays unchanged."
    assert extract_exact_budget_answer_text(raw) == "The answer stays unchanged."


def test_exact_budget_recovery_accepts_invalid_multiline_json_string_and_partial_answer() -> None:
    """Recover explicit IDs and unchanged answer substrings from common incomplete JSON renderings."""
    valid = [f"F{index}" for index in range(1, 7)]
    multiline = '{\n"selected_fact_ids":["F1","F2"],\n"answer_text":"First line.\n\nSecond line."\n}'
    recovered = recover_exact_budget_selection(multiline, 2, valid)
    assert recovered.selection_usable and recovered.answer_text == "First line.\n\nSecond line."
    partial = '"selected_fact_ids":["F1","F2"],\n"answer_text":"An incomplete answer'
    recovered_partial = recover_exact_budget_selection(partial, 2, valid)
    assert recovered_partial.selection_usable and recovered_partial.answer_text == "An incomplete answer"


def test_exact_budget_recovery_uses_shared_ids_but_not_ambiguous_answers() -> None:
    """Recover a repeated selection while leaving its competing answer representations unchosen."""
    valid = [f"F{index}" for index in range(1, 7)]
    first = '{"selected_fact_ids":["F1","F2"],"answer_text":"First"}'
    second = '{"selected_fact_ids":["F1","F2"],"answer_text":"Second"}'
    recovered = recover_exact_budget_selection(first + "\n" + second, 2, valid)
    assert recovered.selection_usable and recovered.selected_fact_ids == ["F1", "F2"]
    assert recovered.answer_text is None
    assert extract_exact_budget_answer_text(first + "\n" + second) is None


def test_exact_budget_recovery_accepts_one_valid_correction_after_wrong_count() -> None:
    """Use the sole exact-k correction when an earlier JSON draft visibly selected the wrong count."""
    valid = [f"F{index}" for index in range(1, 7)]
    draft = '{"selected_fact_ids":["F1","F2","F3"],"answer_text":"Wrong count"}'
    correction = '{"selected_fact_ids":["F1","F2"],"answer_text":"Corrected answer"}'
    recovered = recover_exact_budget_selection(draft + "\nCorrection:\n" + correction, 2, valid)
    assert recovered.selection_usable
    assert recovered.selected_fact_ids == ["F1", "F2"]
    assert recovered.answer_text == "Corrected answer"


def test_word_budget_and_truncation_are_separate() -> None:
    """Score natural cap adherence independently from provider truncation."""
    assert check_word_budget("one two three", 3, "stop").adherent
    over = check_word_budget("one two three four", 3, "length")
    assert not over.adherent
    assert over.truncated


def test_commercial_exact_budget_requires_valid_ids_and_at_most_160_words() -> None:
    """Combine exact-k structure and answer-text length in one adherence result."""
    valid_ids = [f"F{index}" for index in range(1, 7)]
    assignment = MatrixAssignment(
        assignment_id="run_commercial_exact_test",
        scenario_id="CF101_R1",
        model_slug="test/model",
        cell=CommercialInterestCell(
            affect=Affect.NEUTRAL,
            instruction=CommercialInterestInstruction.PROTECT_COMMERCIAL_INTERESTS,
            task=CommercialInterestTask.EXACT_BUDGET,
            exact_fact_budget=ExactFactBudget.FACTS_2,
        ),
        fact_order=1,
        execution_status=ExecutionStatus.ACTIVE,
    )
    answer_text = " ".join(["word"] * 161)
    reply = ProviderReply(
        text=json.dumps({"selected_fact_ids": valid_ids[:2], "answer_text": answer_text}, separators=(",", ":")),
        provider_request_id="request_1",
        returned_model_version="test/model",
        finish_reason="stop",
        input_tokens=10,
        output_tokens=170,
        billed_cost=Decimal("0.01"),
        received_at=datetime.now(UTC),
        attempts=1,
    )
    metadata = _response_metadata(reply, assignment, valid_ids)
    assert metadata.structurally_valid
    assert metadata.selected_fact_ids == valid_ids[:2]
    assert not metadata.adherent


def test_run_unit_rejects_retry_after_semantic_response() -> None:
    """Permit retries only after transport failures with no semantic response."""
    timestamp = datetime.now(UTC)
    invalid_attempts = [
        AttemptMetadata(
            attempt_number=1,
            started_at=timestamp,
            completed_at=timestamp,
            transport_failure=False,
            semantic_response_received=True,
        ),
        AttemptMetadata(
            attempt_number=2,
            started_at=timestamp,
            completed_at=timestamp,
            transport_failure=False,
            semantic_response_received=True,
        ),
    ]
    with pytest.raises(ValidationError):
        RunUnit.model_validate(
            {
                "run_unit_id": "run_1234567890123456",
                "experiment": "single_fact_priority_v1",
                "cell": {"kind": "single_fact_priority_v1"},
                "scenario_id": "CF101_R1",
                "query_variant_id": "query_1",
                "prompt_sha256": "0" * 64,
                "response_contract_sha256": "1" * 64,
                "model": {
                    "model_slug": "test/model",
                    "model_access": "closed",
                    "licence_category": "proprietary",
                    "provider_name": "test",
                    "provider_endpoint": "test",
                    "routing_policy": "one_provider_only_no_fallback",
                    "metadata_snapshot_sha256": "2" * 64,
                },
                "generation_controls": {"max_output_tokens": 100},
                "attempts": [attempt.model_dump(mode="json") for attempt in invalid_attempts],
            }
        )


def test_provider_completion_without_text_retains_usage_and_finish_reason() -> None:
    """Preserve a completed truncated request as an invalid semantic output instead of retrying it."""
    reply = OpenRouterClient._reply(
        {
            "id": "request_1",
            "model": "google/gemini-3.1-flash-lite",
            "provider": "OpenAI",
            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 1024, "cost": "0.004623"},
        },
        attempt=1,
    )
    assert reply.text == ""
    assert reply.finish_reason == "length"
    assert reply.input_tokens == 20 and reply.output_tokens == 1024
    assert reply.billed_cost == Decimal("0.004623")
    assert reply.attempts == 1


def test_only_openrouter_routed_provider_400_is_retryable() -> None:
    """Retry the provider wrapper while rejecting an ordinary invalid-request response."""
    response = httpx.Response(400, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    routed_failure = BadRequestError(
        "Provider returned error",
        response=response,
        body={"error": {"message": "Provider returned error", "code": 400}},
    )
    invalid_request = BadRequestError(
        "Invalid parameter",
        response=response,
        body={"error": {"message": "Invalid parameter", "code": 400}},
    )
    sdk_normalised_failure = BadRequestError(
        "Provider returned error",
        response=response,
        body={"message": "Provider returned error", "code": 400},
    )
    assert OpenRouterClient._is_routed_provider_failure(routed_failure)
    assert OpenRouterClient._is_routed_provider_failure(sdk_normalised_failure)
    assert not OpenRouterClient._is_routed_provider_failure(invalid_request)


def test_completion_choice_distinguishes_semantic_response_from_empty_envelope() -> None:
    """Retry an empty provider envelope while preserving a choice whose content is empty."""
    assert not OpenRouterClient._has_completion_choice({})
    assert not OpenRouterClient._has_completion_choice({"choices": []})
    assert OpenRouterClient._has_completion_choice({"choices": [{"message": {"content": None}, "finish_reason": "length"}]})
