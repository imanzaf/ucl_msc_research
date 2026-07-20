"""Test cell construction, source equivalence, prompt isolation, counts, and retries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import pytest

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import CompletionFinishReason, ConversationTranscript, RetryPolicy
from src.data_models.prompt_controls import validate_prompt_factor_isolation
from src.data_models.study import GENERIC_FOLLOW_UP, NEUTRAL_CUE, WORRIED_CUE, IntegrityCondition, WordBudgetCondition, all_experiment_cells
from src.experiments.scenario_runner import (
    build_calibration_run_plan,
    build_run_plan,
    execute_run_unit,
    validate_calibration_run_plan,
    validate_complete_run_plan,
)
from src.llm.openrouter import ProviderTextResponse
from src.scenarios.source_rendering import derive_secondary_source_order
from src.scenarios.word_count import count_words
from tests.factories import make_accepted_scenario, make_budget_manifest, make_models, make_transcript


def test_all_cells_have_derived_stage_and_deterministic_ids() -> None:
    """Require four primary and four matched mitigation cells with stable ids."""
    cells = all_experiment_cells()
    assert len(cells) == 8
    assert len({cell.cell_id for cell in cells}) == 8
    assert sum(cell.integrity == IntegrityCondition.ABSENT for cell in cells) == 4
    assert sum(cell.integrity == IntegrityCondition.TARGETED for cell in cells) == 4
    assert all(cell.cell_id.startswith(cell.stage.value) for cell in cells)


def test_source_order_b_changes_positions_without_changing_items_or_values() -> None:
    """Derive an information-equivalent order B only when the secondary study needs it."""
    scenario = make_accepted_scenario()
    source_order_b = derive_secondary_source_order(scenario.source_order_a, scenario.source_order_plan)
    ids_a = [item.source_item_id for item in scenario.source_order_a.items]
    ids_b = [item.source_item_id for item in source_order_b.items]
    assert ids_a != ids_b
    assert {item.source_item_id: item.model_dump() for item in scenario.source_order_a.items} == {
        item.source_item_id: item.model_dump() for item in source_order_b.items
    }


def test_full_run_plan_has_480_conversations_960_responses_and_reproducible_order() -> None:
    """Build 120 canonical-order four-cell blocks and reproduce their order from one seed."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 5)]
    created_at = datetime(2026, 7, 19, tzinfo=timezone.utc)
    first = build_run_plan(scenarios, make_models(), make_budget_manifest(), randomisation_seed=17, created_at=created_at)
    second = build_run_plan(scenarios, make_models(), make_budget_manifest(), randomisation_seed=17, created_at=created_at)
    validate_complete_run_plan(first)

    assert len(first) == 480
    assert len(first) * 2 == 960
    assert {unit.source_order.value for unit in first} == {"A"}
    assert [unit.run_unit_id for unit in first] == [unit.run_unit_id for unit in second]
    assert [unit.cell.cell_id for unit in first] == [unit.cell.cell_id for unit in second]
    tampered = list(first)
    first_block_indices = [index for index, unit in enumerate(tampered) if unit.block_id == tampered[0].block_id]
    left, right = first_block_indices[:2]
    tampered[left] = tampered[left].model_copy(update={"randomised_position": tampered[right].randomised_position})
    tampered[right] = tampered[right].model_copy(update={"randomised_position": first[left].randomised_position})
    with pytest.raises(ValueError, match="seeded permutation"):
        validate_complete_run_plan(tampered)


def test_calibration_plan_has_120_canonical_order_conversations() -> None:
    """Build ten C1 × three-model × four-cell blocks with only source order A."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_C1") for use_case in range(1, 11)]
    plan = build_calibration_run_plan(
        scenarios,
        make_models(),
        make_budget_manifest(),
        randomisation_seed=19,
        created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    validate_calibration_run_plan(plan, 19)
    assert len(plan) == 120
    assert {unit.source_order.value for unit in plan} == {"A"}
    assert {unit.scenario_id for unit in plan} == {f"CF{use_case:03d}_C1" for use_case in range(1, 11)}


def test_prompt_factor_isolation_one_cue_and_identical_follow_up() -> None:
    """Allow byte differences only for budget and cue in one primary four-cell block."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 5)]
    plan = build_run_plan(
        scenarios,
        make_models(),
        make_budget_manifest(),
        randomisation_seed=7,
        created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    block = [unit for unit in plan if unit.block_id == plan[0].block_id]
    validate_prompt_factor_isolation(block)
    assert {unit.follow_up_message.content for unit in block} == {GENERIC_FOLLOW_UP}
    for unit in block:
        content = "\n".join(message.content for message in unit.initial_request_messages)
        expected = WORRIED_CUE if unit.cell.emotional_cue.value == "worried" else NEUTRAL_CUE
        assert content.count(expected) == 1
        assert NEUTRAL_CUE not in unit.follow_up_message.content
        assert WORRIED_CUE not in unit.follow_up_message.content
        expected_limit = 240 if unit.cell.word_budget == WordBudgetCondition.AMPLE else 90
        assert unit.assigned_word_limit == expected_limit


def test_retry_attempts_reuse_identical_prompt_bytes() -> None:
    """Record a failed attempt and successful retry with one immutable request hash."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 5)]
    run_unit = build_run_plan(
        scenarios,
        make_models(),
        make_budget_manifest(),
        randomisation_seed=7,
        created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )[0]

    class FlakyProvider:
        """Fail once, then complete both conversation responses."""

        def __init__(self) -> None:
            """Initialise request capture."""
            self.calls: List[List[Dict[str, str]]] = []

        def complete_text(
            self,
            model_id: str,
            messages: List[Dict[str, str]],
            temperature: float,
            max_tokens: int,
            seed: int,
        ) -> ProviderTextResponse:
            """Raise on the first exact request and return text thereafter."""
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise TimeoutError("fixture timeout")
            return ProviderTextResponse(
                text="Material response.",
                provider_request_id=f"request-{len(self.calls)}",
                returned_model_version=run_unit.expected_model_version,
                input_tokens=10,
                output_tokens=4,
                finish_reason=CompletionFinishReason.STOP,
            )

    provider = FlakyProvider()
    transcript = execute_run_unit(run_unit, provider, RetryPolicy(max_retries=1, backoff_seconds=[0.0]))
    assert transcript.outcome_status.value == "completed"
    assert len(transcript.initial_attempts) == 2
    assert len({attempt.request_sha256 for attempt in transcript.initial_attempts}) == 1
    assert provider.calls[0] == provider.calls[1]


def test_returned_model_version_mismatch_is_a_recorded_failed_attempt() -> None:
    """Never accept a provider alias that resolves to a snapshot other than the frozen version."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 5)]
    run_unit = build_run_plan(
        scenarios,
        make_models(),
        make_budget_manifest(),
        randomisation_seed=7,
        created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )[0]

    class VersionChangingProvider:
        """Return one wrong snapshot before serving the exact frozen version."""

        def __init__(self) -> None:
            """Initialise the call counter."""
            self.calls = 0

        def complete_text(
            self,
            model_id: str,
            messages: List[Dict[str, str]],
            temperature: float,
            max_tokens: int,
            seed: int,
        ) -> ProviderTextResponse:
            """Return a mismatched version on only the first request."""
            self.calls += 1
            version = "unexpected-moving-alias" if self.calls == 1 else run_unit.expected_model_version
            return ProviderTextResponse(
                text="Material response.",
                provider_request_id=f"request-{self.calls}",
                returned_model_version=version,
                input_tokens=10,
                output_tokens=4,
                finish_reason=CompletionFinishReason.STOP,
            )

    transcript = execute_run_unit(run_unit, VersionChangingProvider(), RetryPolicy(max_retries=1, backoff_seconds=[0.0]))
    assert transcript.outcome_status.value == "completed"
    assert transcript.initial_attempts[0].error_type == "ModelVersionMismatch"
    assert transcript.initial_attempts[0].response_text is None
    assert transcript.initial_attempts[1].returned_model_version == run_unit.expected_model_version


def test_transcript_turns_are_authenticated_against_provider_attempts() -> None:
    """Reject a self-hashed transcript whose assistant text differs from the provider response."""
    transcript = make_transcript(make_accepted_scenario())
    changed_text = "Substituted assistant text."
    changed_turn = transcript.turns[1].model_copy(
        update={
            "content": changed_text,
            "content_sha256": sha256_bytes(changed_text.encode("utf-8")),
            "word_count": count_words(changed_text),
        }
    )
    payload = transcript.model_dump(mode="json", exclude={"transcript_sha256"})
    payload["turns"] = [payload["turns"][0], changed_turn.model_dump(mode="json"), *payload["turns"][2:]]
    with pytest.raises(ValueError, match="provider responses"):
        ConversationTranscript.model_validate({**payload, "transcript_sha256": artifact_sha256(payload)})
