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
    ProviderRouting,
    RetryPolicy,
    RunOutcomeStatus,
    RunUnit,
    TokenUsage,
    TranscriptTurn,
    provider_compatible_seed,
    provider_request_sha256,
)
from src.data_models.manifests import C1EvaluationConfig, EvaluatedModelSnapshot, ResponseGenerationConfig, ResponseScenarioScope, WordBudgetManifest
from src.data_models.prompt_controls import group_run_units_by_block, validate_condition_query, validate_prompt_factor_isolation
from src.data_models.scenarios import AcceptedScenario
from src.data_models.study import (
    DEFAULT_MAX_RESPONSE_TOKENS,
    ExperimentCell,
    ExperimentName,
    brevity_locus_cells,
    material_priority_cells,
    primary_experiment_cells,
)
from src.llm.openrouter import ProviderTextResponse
from src.prompts.experiment import compile_experiment_prompt
from src.scenarios.fact_rendering import visible_facts_sha256
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


def _build_run_unit(
    scenario: AcceptedScenario,
    model: EvaluatedModelSnapshot,
    cell: ExperimentCell,
    global_randomisation_seed: int,
    block_id: str,
    block_randomisation_seed: int,
    randomised_position: int,
    created_at: datetime,
    provider_routing: Optional[ProviderRouting] = None,
) -> RunUnit:
    """Build one direct-fact run unit with authenticated prompt and follow-up bytes."""
    initial_messages, follow_up, initial_hash, follow_up_hash = compile_experiment_prompt(
        scenario,
        cell,
        None,
    )
    return RunUnit(
        schema_version="3.0.0",
        run_unit_id=_short_identifier("RUN", block_id, cell.cell_id),
        block_id=block_id,
        scenario_id=scenario.scenario_id,
        use_case_id=scenario.use_case_id,
        model_id=model.model_id,
        expected_model_version=model.returned_model_version,
        model_snapshot_sha256=artifact_sha256(model),
        provider_routing=provider_routing,
        cell=cell,
        assigned_word_limit=None,
        global_randomisation_seed=global_randomisation_seed,
        block_randomisation_seed=block_randomisation_seed,
        randomised_position=randomised_position,
        visible_facts_sha256=visible_facts_sha256(scenario),
        initial_request_messages=initial_messages,
        initial_request_sha256=initial_hash,
        follow_up_message=follow_up,
        follow_up_sha256=follow_up_hash,
        created_at=created_at,
    )


def build_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Construct and randomise four primary prompt cells per scenario–model block."""
    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(models, key=lambda item: item.model_id):
            block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id)
            block_randomisation_seed = _block_seed(randomisation_seed, block_id)
            cells = primary_experiment_cells()
            random.Random(block_randomisation_seed).shuffle(cells)
            block_units: List[RunUnit] = []
            for position, cell in enumerate(cells):
                block_units.append(
                    _build_run_unit(
                        scenario,
                        model,
                        cell,
                        randomisation_seed,
                        block_id,
                        block_randomisation_seed,
                        position,
                        created_at,
                    )
                )
            validate_prompt_factor_isolation(block_units)
            run_units.extend(sorted(block_units, key=lambda item: item.randomised_position))
    if len(run_units) != EXPECTED_CONVERSATION_COUNT:
        raise ValueError(f"risk_comm_v1 requires exactly {EXPECTED_CONVERSATION_COUNT} run units; built {len(run_units)}")
    if len({run_unit.run_unit_id for run_unit in run_units}) != len(run_units):
        raise ValueError("run-unit identifiers must be globally unique")
    return run_units


def _scenario_ids_for_response_scope(scope: ResponseScenarioScope) -> set[str]:
    """Return the exact published scenario identifiers selected by one response scope."""
    calibration_ids = {f"CF{use_case:03d}_C1" for use_case in range(1, 11)}
    evaluation_ids = {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 3)}
    if scope == ResponseScenarioScope.C:
        return calibration_ids
    if scope == ResponseScenarioScope.R:
        return evaluation_ids
    return calibration_ids | evaluation_ids


def build_response_generation_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    scenario_scope: ResponseScenarioScope,
    randomisation_seed: int,
    created_at: datetime,
    provider_routing_by_model: Optional[Dict[str, ProviderRouting]] = None,
    provider_routing_by_run_unit: Optional[Dict[str, ProviderRouting]] = None,
) -> List[RunUnit]:
    """Build a four-cell response matrix for the selected published scenarios and models."""
    routing_by_model = provider_routing_by_model or {}
    routing_by_run_unit = provider_routing_by_run_unit or {}
    expected_scenario_ids = _scenario_ids_for_response_scope(scenario_scope)
    if {scenario.scenario_id for scenario in scenarios} != expected_scenario_ids or len(scenarios) != len(expected_scenario_ids):
        raise ValueError(f"response scope {scenario_scope.value} requires exactly its published scenario set")
    if not 1 <= len(models) <= 3 or len({model.model_id for model in models}) != len(models):
        raise ValueError("response generation requires one to three unique evaluated models")
    unknown_routing = sorted(set(routing_by_model) - {model.model_id for model in models})
    if unknown_routing:
        raise ValueError("provider routing names unselected models: " + ", ".join(unknown_routing))

    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(models, key=lambda item: item.model_id):
            block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id)
            block_randomisation_seed = _block_seed(randomisation_seed, block_id)
            cells = primary_experiment_cells()
            random.Random(block_randomisation_seed).shuffle(cells)
            block_units = [
                _build_run_unit(
                    scenario=scenario,
                    model=model,
                    cell=cell,
                    global_randomisation_seed=randomisation_seed,
                    block_id=block_id,
                    block_randomisation_seed=block_randomisation_seed,
                    randomised_position=position,
                    created_at=created_at,
                    provider_routing=routing_by_run_unit.get(
                        _short_identifier("RUN", block_id, cell.cell_id),
                        routing_by_model.get(model.model_id),
                    ),
                )
                for position, cell in enumerate(cells)
            ]
            validate_prompt_factor_isolation(block_units)
            run_units.extend(sorted(block_units, key=lambda item: item.randomised_position))
    _validate_response_generation_matrix(
        run_units,
        scenario_scope,
        models,
        routing_by_model,
        routing_by_run_unit,
        randomisation_seed,
    )
    return run_units


def _validate_response_generation_matrix(
    run_units: Iterable[RunUnit],
    scenario_scope: ResponseScenarioScope,
    models: Sequence[EvaluatedModelSnapshot],
    provider_routing_by_model: Dict[str, ProviderRouting],
    provider_routing_by_run_unit: Dict[str, ProviderRouting],
    global_randomisation_seed: int,
) -> None:
    """Validate identities, routing, seeded order, and prompt isolation for a response matrix."""
    units = list(run_units)
    expected_scenario_ids = _scenario_ids_for_response_scope(scenario_scope)
    expected_models = {model.model_id: (model.returned_model_version, artifact_sha256(model)) for model in models}
    expected_count = len(expected_scenario_ids) * len(expected_models) * len(primary_experiment_cells())
    if len(units) != expected_count:
        raise ValueError(f"response-generation plan must contain exactly {expected_count} conversations")
    if {unit.scenario_id for unit in units} != expected_scenario_ids:
        raise ValueError("response-generation plan scenario IDs differ from its selected scope")
    if {unit.model_id for unit in units} != set(expected_models):
        raise ValueError("response-generation plan model IDs differ from its selected snapshots")
    if len({unit.run_unit_id for unit in units}) != len(units):
        raise ValueError("response-generation run-unit identifiers must be unique")
    unknown_routing_units = sorted(set(provider_routing_by_run_unit) - {unit.run_unit_id for unit in units})
    if unknown_routing_units:
        raise ValueError("provider routing names unknown run units: " + ", ".join(unknown_routing_units))
    if {unit.global_randomisation_seed for unit in units} != {global_randomisation_seed}:
        raise ValueError("response-generation run units must share the configured randomisation seed")
    grouped = group_run_units_by_block(units)
    if len(grouped) != len(expected_scenario_ids) * len(expected_models):
        raise ValueError("response-generation plan has an invalid scenario-model block count")

    for block_id, block_units in grouped.items():
        if len(block_units) != 4 or {unit.randomised_position for unit in block_units} != set(range(4)):
            raise ValueError("every response-generation block requires four randomised cells")
        assignments = {(unit.scenario_id, unit.model_id) for unit in block_units}
        if len(assignments) != 1:
            raise ValueError("response-generation block must share one scenario and model")
        scenario_id, model_id = next(iter(assignments))
        expected_block_id = _short_identifier("BLOCK", scenario_id, model_id)
        expected_seed = _block_seed(global_randomisation_seed, expected_block_id)
        if block_id != expected_block_id or {unit.block_randomisation_seed for unit in block_units} != {expected_seed}:
            raise ValueError("response-generation block id or seed does not derive from its assignment")
        expected_version, expected_snapshot_sha256 = expected_models[model_id]
        if {(unit.expected_model_version, unit.model_snapshot_sha256) for unit in block_units} != {(expected_version, expected_snapshot_sha256)}:
            raise ValueError("response-generation block differs from its evaluated-model snapshot")
        for unit in block_units:
            expected_routing = provider_routing_by_run_unit.get(unit.run_unit_id, provider_routing_by_model.get(model_id))
            if unit.provider_routing != expected_routing:
                raise ValueError("response-generation run unit differs from its configured provider routing")
        expected_cells = primary_experiment_cells()
        random.Random(expected_seed).shuffle(expected_cells)
        cell_by_position = {unit.randomised_position: unit.cell for unit in block_units}
        if [cell_by_position[position] for position in range(4)] != expected_cells:
            raise ValueError("response-generation cell order does not reproduce the seeded permutation")
        if len({unit.visible_facts_sha256 for unit in block_units}) != 1:
            raise ValueError("response-generation block cells must share one exact visible fact list")
        for unit in block_units:
            if unit.run_unit_id != _short_identifier("RUN", block_id, unit.cell.cell_id):
                raise ValueError("response-generation run-unit id does not derive from its block and cell")
        validate_prompt_factor_isolation(block_units)


def validate_response_generation_plan(
    run_units: Iterable[RunUnit],
    config: ResponseGenerationConfig,
    provider_routing_by_run_unit: Optional[Dict[str, ProviderRouting]] = None,
) -> None:
    """Validate one response-generation plan against its immutable configuration."""
    _validate_response_generation_matrix(
        run_units,
        config.scenario_scope,
        config.evaluated_models,
        config.provider_routing_by_model,
        provider_routing_by_run_unit or {},
        config.randomisation_seed,
    )


def validate_response_generation_plan_against_inputs(
    run_units: Iterable[RunUnit],
    scenarios: Sequence[AcceptedScenario],
    config: ResponseGenerationConfig,
    provider_routing_by_run_unit: Optional[Dict[str, ProviderRouting]] = None,
) -> None:
    """Rebuild a response-generation plan and require exact byte-equivalent assignments."""
    units = list(run_units)
    routing_by_run_unit = provider_routing_by_run_unit or {}
    validate_response_generation_plan(units, config, routing_by_run_unit)
    if {unit.created_at for unit in units} != {config.created_at}:
        raise ValueError("response-generation plan creation time differs from its config")
    rebuilt = build_response_generation_run_plan(
        scenarios=scenarios,
        models=config.evaluated_models,
        scenario_scope=config.scenario_scope,
        randomisation_seed=config.randomisation_seed,
        created_at=config.created_at,
        provider_routing_by_model=config.provider_routing_by_model,
        provider_routing_by_run_unit=routing_by_run_unit,
    )
    if [unit.model_dump(mode="json") for unit in units] != [unit.model_dump(mode="json") for unit in rebuilt]:
        raise ValueError("response-generation plan is not the exact product of its frozen inputs")


def _build_exploratory_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    cells: Sequence[ExperimentCell],
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Build a separately identified exploratory plan without paid execution."""
    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(models, key=lambda item: item.model_id):
            block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id, cells[0].stage.value)
            block_randomisation_seed = _block_seed(randomisation_seed, block_id)
            ordered_cells = list(cells)
            random.Random(block_randomisation_seed).shuffle(ordered_cells)
            for position, cell in enumerate(ordered_cells):
                run_unit = _build_run_unit(
                    scenario,
                    model,
                    cell,
                    randomisation_seed,
                    block_id,
                    block_randomisation_seed,
                    position,
                    created_at,
                )
                validate_condition_query(run_unit)
                run_units.append(run_unit)
    return run_units


def build_material_priority_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Build all 120 concise-instruction scenario–model–cue conversations."""
    units = _build_exploratory_run_plan(
        scenarios,
        models,
        material_priority_cells(),
        randomisation_seed,
        created_at,
    )
    validate_exploratory_run_plan(units, expected_count=120, expected_cells=2)
    return units


def build_brevity_locus_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Build all 60 neutral, user-requested-brevity conversations without a system cap."""
    units = _build_exploratory_run_plan(
        scenarios,
        models,
        brevity_locus_cells(),
        randomisation_seed,
        created_at,
    )
    validate_exploratory_run_plan(units, expected_count=60, expected_cells=1)
    return units


def validate_exploratory_run_plan(run_units: Iterable[RunUnit], expected_count: int, expected_cells: int) -> None:
    """Enforce exact exploratory dimensions and prompt isolation."""
    units = list(run_units)
    if len(units) != expected_count:
        raise ValueError(f"exploratory plan must contain exactly {expected_count} conversations")
    if len({unit.scenario_id for unit in units}) != 20 or len({unit.model_id for unit in units}) != 3:
        raise ValueError("exploratory plan requires 20 scenarios and three models")
    grouped = group_run_units_by_block(units)
    if len(grouped) != 60 or any(len(block) != expected_cells for block in grouped.values()):
        raise ValueError("exploratory plan has an invalid scenario–model cell matrix")
    if len({unit.run_unit_id for unit in units}) != expected_count:
        raise ValueError("exploratory run-unit ids must be unique")
    for unit in units:
        validate_condition_query(unit)


def validate_exploratory_plan_against_frozen_inputs(
    run_units: Iterable[RunUnit],
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    budget_manifest: WordBudgetManifest,
    config: ExperimentConfig,
) -> None:
    """Rebuild one exploratory plan and require exact byte-equivalent assignments."""
    units = list(run_units)
    if config.experiment_name == ExperimentName.RISK_COMM_V1:
        raise ValueError("primary plans use validate_run_plan_against_frozen_inputs")
    validate_exploratory_run_plan(units, config.expected_conversation_count, config.cell_count)
    created_at_values = {unit.created_at for unit in units}
    if len(created_at_values) != 1:
        raise ValueError("exploratory run units must share one plan-creation timestamp")
    created_at = next(iter(created_at_values))
    if config.experiment_name == ExperimentName.MATERIAL_PRIORITY_V1:
        rebuilt = build_material_priority_run_plan(scenarios, models, config.randomisation_seed, created_at)
    else:
        rebuilt = build_brevity_locus_run_plan(scenarios, models, config.randomisation_seed, created_at)
    if [unit.model_dump(mode="json") for unit in units] != [unit.model_dump(mode="json") for unit in rebuilt]:
        raise ValueError("exploratory plan is not the exact product of its frozen inputs")


def build_calibration_run_plan(
    scenarios: Sequence[AcceptedScenario],
    models: Sequence[EvaluatedModelSnapshot],
    randomisation_seed: int,
    created_at: datetime,
) -> List[RunUnit]:
    """Construct the 120 calibration conversations across four primary cells."""
    if len(scenarios) != 10 or any(not scenario.scenario_id.endswith("_C1") for scenario in scenarios):
        raise ValueError("calibration plan requires exactly the ten accepted C1 scenarios")
    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(models, key=lambda item: item.model_id):
            block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id)
            block_randomisation_seed = _block_seed(randomisation_seed, block_id)
            cells = primary_experiment_cells()
            random.Random(block_randomisation_seed).shuffle(cells)
            block_units: List[RunUnit] = []
            for position, cell in enumerate(cells):
                block_units.append(
                    _build_run_unit(
                        scenario,
                        model,
                        cell,
                        randomisation_seed,
                        block_id,
                        block_randomisation_seed,
                        position,
                        created_at,
                    )
                )
            validate_prompt_factor_isolation(block_units)
            run_units.extend(sorted(block_units, key=lambda item: item.randomised_position))
    validate_calibration_run_plan(run_units, randomisation_seed)
    return run_units


def validate_calibration_run_plan(run_units: Iterable[RunUnit], global_randomisation_seed: int | None = None) -> None:
    """Validate all 30 four-cell C1/model blocks."""
    units = list(run_units)
    if len(units) != 120:
        raise ValueError("calibration run plan must contain exactly 120 conversations")
    grouped = group_run_units_by_block(units)
    expected_scenarios = {f"CF{use_case:03d}_C1" for use_case in range(1, 11)}
    if {unit.scenario_id for unit in units} != expected_scenarios or len({unit.model_id for unit in units}) != 3:
        raise ValueError("calibration plan requires ten C1 scenarios and three evaluated models")
    if len(grouped) != 30:
        raise ValueError("calibration plan requires 30 four-cell blocks")
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
        expected_block_id = _short_identifier("BLOCK", scenario_id, model_id)
        if block_id != expected_block_id or {unit.block_randomisation_seed for unit in block_units} != {_block_seed(stored_seed, block_id)}:
            raise ValueError("calibration block id or seed does not derive from its assignment")
        if len({unit.visible_facts_sha256 for unit in block_units}) != 1:
            raise ValueError("calibration block cells must share one exact visible fact list")
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
        global_randomisation_seed,
        next(iter(created_at_values)),
    )
    if [unit.model_dump(mode="json") for unit in units] != [unit.model_dump(mode="json") for unit in rebuilt]:
        raise ValueError("calibration plan is not the exact product of its frozen scenarios, models, budgets, prompts, and seed")


def build_c1_single_model_run_plan(
    scenarios: Sequence[AcceptedScenario],
    model: EvaluatedModelSnapshot,
    randomisation_seed: int,
    created_at: datetime,
    provider_routing: Optional[ProviderRouting] = None,
) -> List[RunUnit]:
    """Build one diagnostic four-cell block for each accepted C1 scenario."""
    if len(scenarios) != 10 or {scenario.scenario_id for scenario in scenarios} != {f"CF{index:03d}_C1" for index in range(1, 11)}:
        raise ValueError("single-model C1 planning requires exactly CF001_C1-CF010_C1")
    run_units: List[RunUnit] = []
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        block_id = _short_identifier("BLOCK", scenario.scenario_id, model.model_id)
        block_randomisation_seed = _block_seed(randomisation_seed, block_id)
        cells = primary_experiment_cells()
        random.Random(block_randomisation_seed).shuffle(cells)
        block_units = [
            _build_run_unit(
                scenario=scenario,
                model=model,
                cell=cell,
                global_randomisation_seed=randomisation_seed,
                block_id=block_id,
                block_randomisation_seed=block_randomisation_seed,
                randomised_position=position,
                created_at=created_at,
                provider_routing=provider_routing,
            )
            for position, cell in enumerate(cells)
        ]
        validate_prompt_factor_isolation(block_units)
        run_units.extend(sorted(block_units, key=lambda item: item.randomised_position))
    validate_c1_single_model_run_plan(run_units, randomisation_seed)
    return run_units


def validate_c1_single_model_run_plan(run_units: Iterable[RunUnit], global_randomisation_seed: int | None = None) -> None:
    """Validate the exact ten-block, one-model, four-cell C1 diagnostic matrix."""
    units = list(run_units)
    if len(units) != 40:
        raise ValueError("single-model C1 plan must contain exactly 40 conversations")
    if {unit.scenario_id for unit in units} != {f"CF{index:03d}_C1" for index in range(1, 11)}:
        raise ValueError("single-model C1 plan must contain exactly CF001_C1-CF010_C1")
    if len({unit.model_id for unit in units}) != 1 or len({unit.model_snapshot_sha256 for unit in units}) != 1:
        raise ValueError("single-model C1 plan must bind one evaluated-model snapshot")
    stored_seeds = {unit.global_randomisation_seed for unit in units}
    if len(stored_seeds) != 1:
        raise ValueError("single-model C1 run units must share one global randomisation seed")
    stored_seed = next(iter(stored_seeds))
    if global_randomisation_seed is not None and stored_seed != global_randomisation_seed:
        raise ValueError("single-model C1 run plan seed differs from its config")
    grouped = group_run_units_by_block(units)
    if len(grouped) != 10 or any(len(block) != 4 for block in grouped.values()):
        raise ValueError("single-model C1 plan requires ten four-cell blocks")
    if len({unit.run_unit_id for unit in units}) != 40:
        raise ValueError("single-model C1 run-unit identifiers must be unique")
    for block_id, block_units in grouped.items():
        scenario_models = {(unit.scenario_id, unit.model_id) for unit in block_units}
        if len(scenario_models) != 1:
            raise ValueError("single-model C1 block must share one scenario and model")
        scenario_id, model_id = next(iter(scenario_models))
        expected_block_id = _short_identifier("BLOCK", scenario_id, model_id)
        expected_seed = _block_seed(stored_seed, expected_block_id)
        if block_id != expected_block_id or {unit.block_randomisation_seed for unit in block_units} != {expected_seed}:
            raise ValueError("single-model C1 block id or seed does not derive from its assignment")
        if {unit.randomised_position for unit in block_units} != set(range(4)):
            raise ValueError("single-model C1 block positions must be exactly 0-3")
        expected_cells = primary_experiment_cells()
        random.Random(expected_seed).shuffle(expected_cells)
        cell_by_position = {unit.randomised_position: unit.cell for unit in block_units}
        if [cell_by_position[position] for position in range(4)] != expected_cells:
            raise ValueError("single-model C1 cell order does not reproduce its seeded permutation")
        validate_prompt_factor_isolation(block_units)


def validate_c1_single_model_plan_against_inputs(
    run_units: Iterable[RunUnit],
    scenarios: Sequence[AcceptedScenario],
    config: C1EvaluationConfig,
) -> None:
    """Rebuild a C1 diagnostic plan and require exact byte-equivalent assignments."""
    units = list(run_units)
    validate_c1_single_model_run_plan(units, config.randomisation_seed)
    created_at_values = {unit.created_at for unit in units}
    if created_at_values != {config.created_at}:
        raise ValueError("single-model C1 plan creation time differs from its config")
    rebuilt = build_c1_single_model_run_plan(
        scenarios=scenarios,
        model=config.evaluated_model,
        randomisation_seed=config.randomisation_seed,
        created_at=config.created_at,
        provider_routing=config.provider_routing,
    )
    if [unit.model_dump(mode="json") for unit in units] != [unit.model_dump(mode="json") for unit in rebuilt]:
        raise ValueError("single-model C1 plan is not the exact product of its frozen inputs")


def validate_complete_run_plan(run_units: Iterable[RunUnit], global_randomisation_seed: int | None = None) -> None:
    """Recompute IDs, hashes, dimensions, seeds, positions, and four-cell isolation for the complete plan."""
    units = list(run_units)
    if len(units) != EXPECTED_CONVERSATION_COUNT:
        raise ValueError(f"complete run plan must contain exactly {EXPECTED_CONVERSATION_COUNT} conversations")
    grouped = group_run_units_by_block(units)
    if len(grouped) != EXPECTED_CONVERSATION_COUNT // 4:
        raise ValueError("complete run plan must contain exactly 60 four-cell blocks")
    if len({unit.run_unit_id for unit in units}) != len(units):
        raise ValueError("complete run plan contains duplicate run-unit IDs")
    scenario_ids = {unit.scenario_id for unit in units}
    model_ids = {unit.model_id for unit in units}
    if len(scenario_ids) != 20 or len(model_ids) != 3:
        raise ValueError("complete run plan requires exactly 20 scenarios and three evaluated models")
    expected_scenario_ids = {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 3)}
    if scenario_ids != expected_scenario_ids:
        raise ValueError("complete run plan scenario IDs must be CF001-CF010 R1-R2")
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
        scenario_models = {(unit.scenario_id, unit.model_id) for unit in block_units}
        if len(scenario_models) != 1:
            raise ValueError("block units must share one scenario and model")
        scenario_id, model_id = next(iter(scenario_models))
        expected_block_id = _short_identifier("BLOCK", scenario_id, model_id)
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
        if len({unit.visible_facts_sha256 for unit in block_units}) != 1:
            raise ValueError("all cells in a block must use one exact visible fact list")
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
        randomisation_seed=global_randomisation_seed,
        created_at=next(iter(created_at_values)),
    )
    observed_payload = [unit.model_dump(mode="json") for unit in units]
    rebuilt_payload = [unit.model_dump(mode="json") for unit in rebuilt]
    if observed_payload != rebuilt_payload:
        raise ValueError("run plan is not the exact deterministic product of its frozen scenarios, models, prompts, and seed")


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
    exact_request_sha256 = provider_request_sha256(messages, run_unit.model_id, 0.0, max_tokens, seed, run_unit.provider_routing)
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
                    cost_credits=response.cost_credits,
                    upstream_inference_cost=response.upstream_inference_cost,
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
    """Execute initial and shared follow-up turns for one immutable run unit."""
    initial_messages = _provider_messages(run_unit.initial_request_messages)
    max_tokens = DEFAULT_MAX_RESPONSE_TOKENS
    provider_seed = provider_compatible_seed(run_unit.block_randomisation_seed)
    initial_response, initial_attempts = _call_with_retries(
        provider=provider,
        run_unit=run_unit,
        messages=initial_messages,
        retry_policy=retry_policy,
        seed=provider_seed,
        max_tokens=max_tokens,
    )
    if initial_response is None:
        return _transcript(
            schema_version="2.0.0",
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
        seed=provider_seed,
        max_tokens=max_tokens,
    )
    turns = [
        _turn(0, MessageRole.USER, next(message.content for message in run_unit.initial_request_messages if message.role == MessageRole.USER)),
        _turn(1, MessageRole.ASSISTANT, initial_response.text),
        _turn(2, MessageRole.USER, run_unit.follow_up_message.content),
    ]
    if follow_up_response is None:
        return _transcript(
            schema_version="2.0.0",
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
        schema_version="2.0.0",
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
    config: ExperimentConfig | CalibrationExperimentConfig | C1EvaluationConfig | ResponseGenerationConfig,
    results_path: Path,
    existing_transcripts: Sequence[ConversationTranscript],
    paid_execution_approved: bool,
    provider_routing_by_run_unit: Optional[Dict[str, ProviderRouting]] = None,
) -> List[ConversationTranscript]:
    """Resume a plan, persist every outcome immediately, and require the paid-run gate."""
    if not paid_execution_approved:
        raise PermissionError("paid execution requires an explicit approved dry-run/cost gate")
    if isinstance(config, ResponseGenerationConfig):
        validate_response_generation_plan(run_units, config, provider_routing_by_run_unit)
    elif isinstance(config, C1EvaluationConfig):
        validate_c1_single_model_run_plan(run_units, config.randomisation_seed)
    elif isinstance(config, CalibrationExperimentConfig):
        validate_calibration_run_plan(run_units, config.randomisation_seed)
    else:
        if config.experiment_name.value == "risk_comm_v1":
            validate_complete_run_plan(run_units, config.randomisation_seed)
        else:
            validate_exploratory_run_plan(run_units, config.expected_conversation_count, config.cell_count)
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
