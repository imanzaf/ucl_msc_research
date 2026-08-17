"""Structured adherence, word-limit, truncation, and retry-policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from srcv2.experiments.responses import check_word_budget, extract_exact_budget_answer_text, parse_exact_budget_output, recover_exact_budget_selection
from srcv2.llm.openrouter import OpenRouterClient
from srcv2.models.experiments import AttemptMetadata, RunUnit


def test_exact_budget_requires_distinct_valid_ids_and_field_order() -> None:
    """Treat malformed, reordered, duplicate, wrong-k, and unknown IDs as non-adherence."""
    valid = [f"F{index}" for index in range(1, 7)]
    assert parse_exact_budget_output('{"selected_fact_ids":["F1","F2"],"answer_text":"Answer"}', 2, valid).adherent
    assert not parse_exact_budget_output('{"answer_text":"Answer","selected_fact_ids":["F1","F2"]}', 2, valid).structurally_valid
    assert not parse_exact_budget_output('{"selected_fact_ids":["F1","F1"],"answer_text":"Answer"}', 2, valid).structurally_valid
    assert not parse_exact_budget_output('{"selected_fact_ids":["F1"],"answer_text":"Answer"}', 2, valid).adherent
    assert not parse_exact_budget_output('{"selected_fact_ids":["F1","F9"],"answer_text":"Answer"}', 2, valid).adherent
    assert not parse_exact_budget_output("not json", 2, valid).structurally_valid


def test_fenced_exact_budget_selection_is_usable_but_format_nonadherent() -> None:
    """Recover only a complete unambiguous JSON fence without changing its adherence label."""
    valid = [f"F{index}" for index in range(1, 7)]
    fenced = '```json\n{"selected_fact_ids":["F1","F2"],"answer_text":"Answer"}\n```'
    recovered = recover_exact_budget_selection(fenced, 2, valid)
    assert recovered.structurally_valid and recovered.selection_usable
    assert not recovered.adherent and not recovered.format_adherent
    assert recovered.selected_fact_ids == ["F1", "F2"]
    assert not recover_exact_budget_selection('Prose before {"selected_fact_ids":["F1","F2"]}', 2, valid).selection_usable
    assert extract_exact_budget_answer_text(fenced) == "Answer"
    assert extract_exact_budget_answer_text("Prose before " + fenced) is None


def test_word_budget_and_truncation_are_separate() -> None:
    """Score natural cap adherence independently from provider truncation."""
    assert check_word_budget("one two three", 3, "stop").adherent
    over = check_word_budget("one two three four", 3, "length")
    assert not over.adherent
    assert over.truncated


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
            "model": "openai/gpt-5.4-mini",
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
