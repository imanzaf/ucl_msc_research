"""Build, validate, randomise, resume, and execute all experiment cells."""

from __future__ import annotations

import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from src.data_models.common import artifact_sha256, canonical_json_bytes, sha256_bytes, utc_now
from src.data_models.experiments import (
    EXPECTED_CONVERSATION_COUNT,
    CalibrationExperimentConfig,
    ConversationTranscript,
    ExperimentConfig,
    FailureReason,
    MessageRole,
    PromptMessage,
    ProviderAttempt,
    RetryPolicy,
    RunOutcomeStatus,
    RunUnit,
    TokenUsage,
    TranscriptTurn,
    provider_request_sha256,
)
from src.data_models.manifests import EvaluatedModelSnapshot, FreezeStatus, WordBudgetManifest
from src.data_models.prompt_controls import group_run_units_by_block, validate_prompt_factor_isolation
from src.data_models.scenarios import AcceptedScenario
from src.data_models.study import AMPLE_WORD_LIMIT, SourceOrderVariant, WordBudgetCondition, primary_experiment_cells
from src.llm.openrouter import ProviderTextResponse
from src.prompts.experiment import compile_experiment_prompt
from src.scenarios.word_count import count_words
from src.storage import append_model_jsonl_atomic


class TextCompletionProvider(Protocol):
    """Define the one-attempt provider interface required by the experiment runner."""

    def complete_text(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        seed: int,
    ) -> ProviderTextResponse:
        """Return one provider response or raise an exception."""
        ...


def _short_identifier(prefix: str, *parts: str) -> str:
    """Derive a stable uppercase sixteen-hex identifier from canonical parts."""
    digest = sha256_bytes(canonical_json_bytes(list(parts))).upper()[:16]
    return f"{prefix}_{digest}"


def _block_seed(global_seed: int, block_id: str) -> int:
    """Derive a reproducible per-block integer randomisation seed."""
    return int(sha256_bytes(f"{global_seed}:{block_id}".encode("utf-8"))[:16], 16)


def _tight_limit_by_use_case(manifest: WordBudgetManifest) -> Dict[str, int]:
    """Return frozen tight limits only after the budget manifest is valid."""
    if manifest.freeze_status != FreezeStatus.FROZEN or not manifest.ample_pilot.passes():
        raise ValueError("run planning requires a frozen word-budget manifest and passing ample-limit pilot")
    return {budget.use_case_id: budget.tight_word_limit for budget in manifest.use_case_budgets}


def build_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    budget_manifest: WordBudgetManifest,
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Construct and randomise four canonical-order primary cells per scenario–model block."""
    tight_limits = _tight_limit_by_use_case(budget_manifest)
    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        if scenario.use_case_id not in tight_limits:
            raise ValueError(f"missing frozen tight limit for {scenario.use_case_id}")
        for model in sorted(models, key=lambda item: item.model_id):
            source_order = SourceOrderVariant.A
            packet = scenario.source_order_a
            block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id, source_order.value)
            block_randomisation_seed = _block_seed(randomisation_seed, block_id)
            cells = primary_experiment_cells()
            random.Random(block_randomisation_seed).shuffle(cells)
            block_units: List[RunUnit] = []
            for position, cell in enumerate(cells):
                assigned_limit = AMPLE_WORD_LIMIT if cell.word_budget == WordBudgetCondition.AMPLE else tight_limits[scenario.use_case_id]
                initial_messages, follow_up, initial_hash, follow_up_hash = compile_experiment_prompt(
                    scenario=scenario,
                    source_packet=packet,
                    cell=cell,
                    assigned_word_limit=assigned_limit,
                )
                block_units.append(
                    RunUnit(
                        schema_version="1.0.0",
                        run_unit_id=_short_identifier("RUN", block_id, cell.cell_id),
                        block_id=block_id,
                        scenario_id=scenario.scenario_id,
                        use_case_id=scenario.use_case_id,
                        model_id=model.model_id,
                        expected_model_version=model.returned_model_version,
                        model_snapshot_sha256=artifact_sha256(model),
                        source_order=source_order,
                        cell=cell,
                        assigned_word_limit=assigned_limit,
                        global_randomisation_seed=randomisation_seed,
                        block_randomisation_seed=block_randomisation_seed,
                        randomised_position=position,
                        source_packet_sha256=packet.rendered_sha256,
                        initial_request_messages=initial_messages,
                        initial_request_sha256=initial_hash,
                        follow_up_message=follow_up,
                        follow_up_sha256=follow_up_hash,
                        created_at=created_at,
                    )
                )
            validate_prompt_factor_isolation(block_units)
            run_units.extend(sorted(block_units, key=lambda item: item.randomised_position))
    if len(run_units) != EXPECTED_CONVERSATION_COUNT:
        raise ValueError(f"risk_comm_v1 requires exactly {EXPECTED_CONVERSATION_COUNT} run units; built {len(run_units)}")
    if len({run_unit.run_unit_id for run_unit in run_units}) != len(run_units):
        raise ValueError("run-unit identifiers must be globally unique")
    return run_units


def build_calibration_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    budget_manifest: WordBudgetManifest,
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Construct the 120 canonical-order calibration conversations across four primary cells."""
    tight_limits = _tight_limit_by_use_case(budget_manifest)
    if len(scenarios) != 10 or any(not scenario.scenario_id.endswith("_C1") for scenario in scenarios):
        raise ValueError("calibration plan requires exactly the ten accepted C1 scenarios")
    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(models, key=lambda item: item.model_id):
            block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id, SourceOrderVariant.A.value)
            block_randomisation_seed = _block_seed(randomisation_seed, block_id)
            cells = primary_experiment_cells()
            random.Random(block_randomisation_seed).shuffle(cells)
            block_units: List[RunUnit] = []
            for position, cell in enumerate(cells):
                assigned_limit = AMPLE_WORD_LIMIT if cell.word_budget == WordBudgetCondition.AMPLE else tight_limits[scenario.use_case_id]
                initial_messages, follow_up, initial_hash, follow_up_hash = compile_experiment_prompt(
                    scenario, scenario.source_order_a, cell, assigned_limit
                )
                block_units.append(
                    RunUnit(
                        schema_version="1.0.0",
                        run_unit_id=_short_identifier("RUN", block_id, cell.cell_id),
                        block_id=block_id,
                        scenario_id=scenario.scenario_id,
                        use_case_id=scenario.use_case_id,
                        model_id=model.model_id,
                        expected_model_version=model.returned_model_version,
                        model_snapshot_sha256=artifact_sha256(model),
                        source_order=SourceOrderVariant.A,
                        cell=cell,
                        assigned_word_limit=assigned_limit,
                        global_randomisation_seed=randomisation_seed,
                        block_randomisation_seed=block_randomisation_seed,
                        randomised_position=position,
                        source_packet_sha256=scenario.source_order_a.rendered_sha256,
                        initial_request_messages=initial_messages,
                        initial_request_sha256=initial_hash,
                        follow_up_message=follow_up,
                        follow_up_sha256=follow_up_hash,
                        created_at=created_at,
                    )
                )
            validate_prompt_factor_isolation(block_units)
            run_units.extend(sorted(block_units, key=lambda item: item.randomised_position))
    validate_calibration_run_plan(run_units, randomisation_seed)
    return run_units


def validate_calibration_run_plan(run_units: Iterable[RunUnit], global_randomisation_seed: int | None = None) -> None:
    """Validate all 30 four-cell C1/model blocks at canonical source order A."""
    units = list(run_units)
    if len(units) != 120:
        raise ValueError("calibration run plan must contain exactly 120 conversations")
    grouped = group_run_units_by_block(units)
    expected_scenarios = {f"CF{use_case:03d}_C1" for use_case in range(1, 11)}
    if {unit.scenario_id for unit in units} != expected_scenarios or len({unit.model_id for unit in units}) != 3:
        raise ValueError("calibration plan requires ten C1 scenarios and three evaluated models")
    if {unit.source_order for unit in units} != {SourceOrderVariant.A} or len(grouped) != 30:
        raise ValueError("calibration plan requires 30 canonical-order four-cell blocks")
    stored_seeds = {unit.global_randomisation_seed for unit in units}
    if len(stored_seeds) != 1:
        raise ValueError("calibration run units must share one global randomisation seed")
    stored_seed = next(iter(stored_seeds))
    if global_randomisation_seed is not None and stored_seed != global_randomisation_seed:
        raise ValueError("calibration run plan seed differs from its frozen config")
    if len({unit.run_unit_id for unit in units}) != 120:
        raise ValueError("calibration run-unit identifiers must be unique")
    for block_id, block_units in grouped.items():
        if len(block_units) != 4 or {unit.randomised_position for unit in block_units} != set(range(4)):
            raise ValueError("every calibration block requires all four randomised positions")
        scenario_model = {(unit.scenario_id, unit.model_id) for unit in block_units}
        if len(scenario_model) != 1:
            raise ValueError("calibration block must share one scenario and model")
        scenario_id, model_id = next(iter(scenario_model))
        expected_block_id = _short_identifier("BLOCK", scenario_id, model_id, SourceOrderVariant.A.value)
        if block_id != expected_block_id or {unit.block_randomisation_seed for unit in block_units} != {_block_seed(stored_seed, block_id)}:
            raise ValueError("calibration block id or seed does not derive from its assignment")
        if len({unit.source_packet_sha256 for unit in block_units}) != 1:
            raise ValueError("calibration block cells must share one exact source packet")
        expected_cells = primary_experiment_cells()
        random.Random(_block_seed(stored_seed, block_id)).shuffle(expected_cells)
        cell_by_position = {unit.randomised_position: unit.cell for unit in block_units}
        if [cell_by_position[position] for position in range(4)] != expected_cells:
            raise ValueError("calibration cell order does not reproduce the frozen seeded permutation")
        for unit in block_units:
            if unit.run_unit_id != _short_identifier("RUN", block_id, unit.cell.cell_id):
                raise ValueError("calibration run-unit id does not derive from block and cell")
        validate_prompt_factor_isolation(block_units)


def validate_calibration_plan_against_frozen_inputs(
    run_units: Iterable[RunUnit],
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    budget_manifest: WordBudgetManifest,
    global_randomisation_seed: int,
) -> None:
    """Rebuild the calibration plan from frozen inputs and require exact records."""
    units = list(run_units)
    validate_calibration_run_plan(units, global_randomisation_seed)
    created_at_values = {unit.created_at for unit in units}
    if len(created_at_values) != 1:
        raise ValueError("all calibration units must share one plan-creation timestamp")
    rebuilt = build_calibration_run_plan(
        scenarios,
        models,
        budget_manifest,
        global_randomisation_seed,
        next(iter(created_at_values)),
    )
    if [unit.model_dump(mode="json") for unit in units] != [unit.model_dump(mode="json") for unit in rebuilt]:
        raise ValueError("calibration plan is not the exact product of its frozen scenarios, models, budgets, prompts, and seed")


def validate_complete_run_plan(run_units: Iterable[RunUnit], global_randomisation_seed: int | None = None) -> None:
    """Recompute IDs, hashes, dimensions, seeds, positions, and four-cell isolation for the complete plan."""
    units = list(run_units)
    if len(units) != EXPECTED_CONVERSATION_COUNT:
        raise ValueError("complete run plan must contain exactly 480 conversations")
    grouped = group_run_units_by_block(units)
    if len(grouped) != EXPECTED_CONVERSATION_COUNT // 4:
        raise ValueError("complete run plan must contain exactly 120 four-cell blocks")
    if len({unit.run_unit_id for unit in units}) != len(units):
        raise ValueError("complete run plan contains duplicate run-unit IDs")
    scenario_ids = {unit.scenario_id for unit in units}
    model_ids = {unit.model_id for unit in units}
    if len(scenario_ids) != 40 or len(model_ids) != 3:
        raise ValueError("complete run plan requires exactly 40 scenarios and three evaluated models")
    if {unit.source_order for unit in units} != {SourceOrderVariant.A}:
        raise ValueError("complete run plan requires canonical source order A only")
    expected_scenario_ids = {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 5)}
    if scenario_ids != expected_scenario_ids:
        raise ValueError("complete run plan scenario IDs must be CF001-CF010 R1-R4")
    stored_global_seeds = {unit.global_randomisation_seed for unit in units}
    if len(stored_global_seeds) != 1:
        raise ValueError("all run units must bind one global randomisation seed")
    stored_global_seed = next(iter(stored_global_seeds))
    if global_randomisation_seed is not None and stored_global_seed != global_randomisation_seed:
        raise ValueError("run plan global randomisation seed differs from the frozen config")
    model_snapshots = {(unit.model_id, unit.expected_model_version, unit.model_snapshot_sha256) for unit in units}
    if len(model_snapshots) != 3:
        raise ValueError("each evaluated model must bind one exact snapshot/version")
    for block_id, block_units in grouped.items():
        if len(block_units) != 4:
            raise ValueError("each run-plan block must contain exactly four units")
        scenario_model_orders = {(unit.scenario_id, unit.model_id, unit.source_order) for unit in block_units}
        if len(scenario_model_orders) != 1:
            raise ValueError("block units must share scenario, model, and source order")
        scenario_id, model_id, source_order = next(iter(scenario_model_orders))
        expected_block_id = _short_identifier("BLOCK", scenario_id, model_id, source_order.value)
        if block_id != expected_block_id:
            raise ValueError("block ID does not match its immutable assignment")
        expected_block_seed = _block_seed(stored_global_seed, block_id)
        if {unit.block_randomisation_seed for unit in block_units} != {expected_block_seed}:
            raise ValueError("block randomisation seed does not derive from the global seed")
        if {unit.randomised_position for unit in block_units} != set(range(4)):
            raise ValueError("block randomised positions must be exactly 0-3")
        expected_cells = primary_experiment_cells()
        random.Random(expected_block_seed).shuffle(expected_cells)
        cell_by_position = {unit.randomised_position: unit.cell for unit in block_units}
        if [cell_by_position[position] for position in range(4)] != expected_cells:
            raise ValueError("block cell order does not reproduce the frozen seeded permutation")
        if len({unit.source_packet_sha256 for unit in block_units}) != 1:
            raise ValueError("all cells in a block must use one exact source packet")
        for unit in block_units:
            if unit.run_unit_id != _short_identifier("RUN", block_id, unit.cell.cell_id):
                raise ValueError("run-unit ID does not derive from block and cell")
        validate_prompt_factor_isolation(block_units)


def validate_run_plan_against_frozen_inputs(
    run_units: Iterable[RunUnit],
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    budget_manifest: WordBudgetManifest,
    global_randomisation_seed: int,
) -> None:
    """Rebuild a main run plan from frozen inputs and require byte-equivalent records."""
    units = list(run_units)
    validate_complete_run_plan(units, global_randomisation_seed)
    created_at_values = {unit.created_at for unit in units}
    if len(created_at_values) != 1:
        raise ValueError("all run units must share the one frozen plan-creation timestamp")
    rebuilt = build_run_plan(
        scenarios=scenarios,
        models=models,
        budget_manifest=budget_manifest,
        randomisation_seed=global_randomisation_seed,
        created_at=next(iter(created_at_values)),
    )
    observed_payload = [unit.model_dump(mode="json") for unit in units]
    rebuilt_payload = [unit.model_dump(mode="json") for unit in rebuilt]
    if observed_payload != rebuilt_payload:
        raise ValueError("run plan is not the exact deterministic product of its frozen scenarios, models, budgets, prompts, and seed")


def _provider_messages(messages: Sequence[PromptMessage]) -> List[Dict[str, str]]:
    """Convert immutable prompt messages into exact provider dictionaries."""
    return [{"role": message.role.value, "content": message.content} for message in messages]


def _call_with_retries(
    provider: TextCompletionProvider,
    run_unit: RunUnit,
    messages: List[Dict[str, str]],
    retry_policy: RetryPolicy,
    seed: int,
    max_tokens: int,
) -> Tuple[Optional[ProviderTextResponse], List[ProviderAttempt]]:
    """Call a provider under the frozen retry policy and record every attempt."""
    exact_request_sha256 = provider_request_sha256(messages, run_unit.model_id, 0.0, max_tokens, seed)
    attempts: List[ProviderAttempt] = []
    for attempt_index in range(retry_policy.max_retries + 1):
        started_at = utc_now()
        monotonic_start = time.monotonic()
        try:
            response = provider.complete_text(
                model_id=run_unit.model_id,
                messages=messages,
                temperature=0.0,
                max_tokens=max_tokens,
                seed=seed,
            )
        except Exception as error:
            completed_at = utc_now()
            attempts.append(
                ProviderAttempt(
                    attempt_number=attempt_index + 1,
                    request_sha256=exact_request_sha256,
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=max(0, int((time.monotonic() - monotonic_start) * 1000)),
                    error_type=type(error).__name__,
                    error_message=str(error) or type(error).__name__,
                )
            )
            if attempt_index < retry_policy.max_retries:
                delay = retry_policy.backoff_seconds[attempt_index]
                if delay:
                    time.sleep(delay)
            continue
        completed_at = utc_now()
        if response.returned_model_version != run_unit.expected_model_version:
            attempts.append(
                ProviderAttempt(
                    attempt_number=attempt_index + 1,
                    request_sha256=exact_request_sha256,
                    started_at=started_at,
                    completed_at=completed_at,
                    provider_request_id=response.provider_request_id,
                    returned_model_version=response.returned_model_version,
                    latency_ms=max(0, int((time.monotonic() - monotonic_start) * 1000)),
                    error_type="ModelVersionMismatch",
                    error_message=f"expected {run_unit.expected_model_version}, received {response.returned_model_version}",
                )
            )
            if attempt_index < retry_policy.max_retries:
                delay = retry_policy.backoff_seconds[attempt_index]
                if delay:
                    time.sleep(delay)
            continue
        attempts.append(
            ProviderAttempt(
                attempt_number=attempt_index + 1,
                request_sha256=exact_request_sha256,
                started_at=started_at,
                completed_at=completed_at,
                provider_request_id=response.provider_request_id,
                returned_model_version=response.returned_model_version,
                response_text=response.text,
                response_sha256=sha256_bytes(response.text.encode("utf-8")),
                finish_reason=response.finish_reason,
                latency_ms=max(0, int((time.monotonic() - monotonic_start) * 1000)),
                usage=TokenUsage(
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    total_tokens=response.input_tokens + response.output_tokens,
                ),
            )
        )
        return response, attempts
    return None, attempts


def _turn(turn_index: int, role: MessageRole, content: str) -> TranscriptTurn:
    """Build one transcript turn with exact text hash and frozen word count."""
    return TranscriptTurn(
        turn_index=turn_index,
        role=role,
        content=content,
        content_sha256=sha256_bytes(content.encode("utf-8")),
        word_count=count_words(content),
    )


def _transcript(**payload: object) -> ConversationTranscript:
    """Build one transcript whose digest covers every persisted field except itself."""
    payload.setdefault("failure_reason", None)
    return ConversationTranscript.model_validate({**payload, "transcript_sha256": artifact_sha256(payload)})


def execute_run_unit(
    run_unit: RunUnit,
    provider: TextCompletionProvider,
    retry_policy: RetryPolicy,
) -> ConversationTranscript:
    """Execute initial and cue-free follow-up turns for one immutable run unit."""
    initial_messages = _provider_messages(run_unit.initial_request_messages)
    max_tokens = max(512, run_unit.assigned_word_limit * 4)
    initial_response, initial_attempts = _call_with_retries(
        provider=provider,
        run_unit=run_unit,
        messages=initial_messages,
        retry_policy=retry_policy,
        seed=run_unit.block_randomisation_seed,
        max_tokens=max_tokens,
    )
    if initial_response is None:
        return _transcript(
            schema_version="1.0.0",
            run_unit=run_unit,
            outcome_status=RunOutcomeStatus.FAILED,
            turns=[],
            initial_attempts=initial_attempts,
            follow_up_attempts=[],
            failure_reason=FailureReason.RETRIES_EXHAUSTED,
            completed_at=utc_now(),
        )
    follow_up_messages = [
        *initial_messages,
        {"role": MessageRole.ASSISTANT.value, "content": initial_response.text},
        {"role": run_unit.follow_up_message.role.value, "content": run_unit.follow_up_message.content},
    ]
    follow_up_response, follow_up_attempts = _call_with_retries(
        provider=provider,
        run_unit=run_unit,
        messages=follow_up_messages,
        retry_policy=retry_policy,
        seed=run_unit.block_randomisation_seed,
        max_tokens=max_tokens,
    )
    turns = [
        _turn(0, MessageRole.USER, next(message.content for message in run_unit.initial_request_messages if message.role == MessageRole.USER)),
        _turn(1, MessageRole.ASSISTANT, initial_response.text),
        _turn(2, MessageRole.USER, run_unit.follow_up_message.content),
    ]
    if follow_up_response is None:
        return _transcript(
            schema_version="1.0.0",
            run_unit=run_unit,
            outcome_status=RunOutcomeStatus.FAILED,
            turns=turns,
            initial_attempts=initial_attempts,
            follow_up_attempts=follow_up_attempts,
            failure_reason=FailureReason.RETRIES_EXHAUSTED,
            completed_at=utc_now(),
        )
    turns.append(_turn(3, MessageRole.ASSISTANT, follow_up_response.text))
    return _transcript(
        schema_version="1.0.0",
        run_unit=run_unit,
        outcome_status=RunOutcomeStatus.COMPLETED,
        turns=turns,
        initial_attempts=initial_attempts,
        follow_up_attempts=follow_up_attempts,
        completed_at=utc_now(),
    )


def execute_run_plan(
    run_units: Sequence[RunUnit],
    provider: TextCompletionProvider,
    config: ExperimentConfig | CalibrationExperimentConfig,
    results_path: Path,
    existing_transcripts: Sequence[ConversationTranscript],
    paid_execution_approved: bool,
) -> List[ConversationTranscript]:
    """Resume a plan, persist every outcome immediately, and require the paid-run gate."""
    if not paid_execution_approved:
        raise PermissionError("paid execution requires an explicit approved dry-run/cost gate")
    if isinstance(config, CalibrationExperimentConfig):
        validate_calibration_run_plan(run_units, config.randomisation_seed)
    else:
        validate_complete_run_plan(run_units, config.randomisation_seed)
    planned_by_id = {run_unit.run_unit_id: run_unit for run_unit in run_units}
    existing_ids = [transcript.run_unit.run_unit_id for transcript in existing_transcripts]
    if len(existing_ids) != len(set(existing_ids)):
        raise ValueError("resume transcript file contains duplicate run-unit IDs")
    for transcript in existing_transcripts:
        planned = planned_by_id.get(transcript.run_unit.run_unit_id)
        if planned is None or transcript.run_unit != planned:
            raise ValueError("resume transcript does not match the supplied immutable run plan")
    completed_ids = set(existing_ids)
    new_transcripts: List[ConversationTranscript] = []
    for run_unit in run_units:
        if run_unit.run_unit_id in completed_ids:
            continue
        transcript = execute_run_unit(run_unit=run_unit, provider=provider, retry_policy=config.retry_policy)
        append_model_jsonl_atomic(results_path, transcript)
        new_transcripts.append(transcript)
        completed_ids.add(run_unit.run_unit_id)
    return new_transcripts
