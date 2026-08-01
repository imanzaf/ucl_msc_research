"""Generate initial C1 or C1-example-guided R1/R2 scenario candidates."""

from __future__ import annotations

import argparse
import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, cast

from src.data_models.common import artifact_sha256, utc_now
from src.data_models.scenario_review import ScenarioPipelineFailureRecord
from src.data_models.scenarios import (
    AcceptedScenario,
    ScenarioGenerationInvocationConfig,
    ScenarioGenerationRunConfig,
    ScenarioReplicationSeed,
    ScenarioStage,
    ScenarioUseCaseSeed,
)
from src.paths import (
    ACTIVE_SCENARIO_ACCEPTED_ROOT,
    ACTIVE_SCENARIO_GENERATION_ROOT,
    ACTIVE_SCENARIO_GENERATION_VERSION,
    ACTIVE_SCENARIO_INPUT_ROOT,
    ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
    ACTIVE_SCENARIO_QUERY_SHA256,
    ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
    ACTIVE_SCENARIO_SEED_SHA256,
    ACTIVE_SCENARIO_SEED_VERSION,
    ACTIVE_SCENARIO_SET_ID,
    scenario_generation_round_id,
    scenario_generation_run_root,
)
from src.scenarios.acceptance import validate_accepted_scenario_hash
from src.scenarios.pipeline import ScenarioGenerationBackend, generate_initial_candidates
from src.scenarios.run_resolution import current_scenario_artifacts
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, write_model_json_atomic


def _load_backend(specification: str, invocation_root: Path) -> ScenarioGenerationBackend:
    """Load a generator factory and scope its provider logs to this invocation."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator:
        raise ValueError("backend must use module:attribute syntax")
    return cast(ScenarioGenerationBackend, getattr(importlib.import_module(module_name), attribute_name)(invocation_root))


def _select_stage_seeds(
    use_cases: List[ScenarioUseCaseSeed],
    stage: ScenarioStage,
    use_case_id: Optional[str],
    scenario_id: Optional[str],
) -> List[Tuple[ScenarioUseCaseSeed, ScenarioReplicationSeed]]:
    """Select a calibration batch, one use case, or one exact scenario."""
    stage_seeds = [
        (use_case, replication)
        for use_case in use_cases
        for replication in use_case.replications
        if (replication.scenario_id.endswith("_C1")) == (stage == ScenarioStage.CALIBRATION)
    ]
    if scenario_id is not None:
        exact = [item for item in stage_seeds if item[1].scenario_id == scenario_id]
        if len(exact) != 1:
            raise ValueError(f"scenario id is unknown or does not belong to the {stage.value} stage: {scenario_id}")
        if use_case_id is not None and exact[0][0].use_case_id != use_case_id:
            raise ValueError("--use-case-id and --scenario-id refer to different task families")
        return exact
    if stage == ScenarioStage.CALIBRATION:
        if use_case_id is not None:
            raise ValueError("calibration batch generation operates across all ten use cases; omit --use-case-id")
        return stage_seeds
    if use_case_id is None:
        return stage_seeds
    selected = [item for item in stage_seeds if item[0].use_case_id == use_case_id]
    if not selected:
        raise ValueError(f"unknown use case id: {use_case_id}")
    return selected


def _timestamp_from_round_id(round_id: str) -> datetime:
    """Parse one validated round identifier as UTC."""
    return datetime.strptime(round_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)


def _run_config(run_id: str, created_at: Optional[datetime] = None) -> ScenarioGenerationRunConfig:
    """Build the active input identity recorded when a logical run starts."""
    return ScenarioGenerationRunConfig(
        schema_version="2.0.0",
        run_id=run_id,
        seed_version=ACTIVE_SCENARIO_SEED_VERSION,
        generation_protocol_version=ACTIVE_SCENARIO_GENERATION_VERSION,
        scenario_set_id=ACTIVE_SCENARIO_SET_ID,
        seed_sha256=ACTIVE_SCENARIO_SEED_SHA256,
        seed_schema_sha256=ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
        query_sha256=ACTIVE_SCENARIO_QUERY_SHA256,
        query_schema_sha256=ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
        created_at=created_at or utc_now(),
    )


def _authenticated_run_root(run_id: str) -> Path:
    """Load one existing run without blocking later edits when active inputs change."""
    run_root = scenario_generation_run_root(run_id)
    config_path = run_root / "run_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"unknown scenario generation run: {run_id}")
    config = read_model_json(config_path, ScenarioGenerationRunConfig)
    if config.run_id != run_id:
        raise ValueError("scenario generation run config does not match its directory name")
    return run_root


def _prepare_run_root(run_id: str) -> Tuple[str, Path]:
    """Create or reopen one named logical run."""
    run_root = scenario_generation_run_root(run_id)
    if run_root.exists():
        return run_id, _authenticated_run_root(run_id)
    run_root.mkdir(parents=True, exist_ok=False)
    write_model_json_atomic(run_root / "run_config.json", _run_config(run_id))
    return run_id, run_root


def _create_invocation_root(
    run_root: Path,
    run_id: str,
    stage: ScenarioStage,
    selected: List[Tuple[ScenarioUseCaseSeed, ScenarioReplicationSeed]],
    backend_specification: str,
) -> Path:
    """Create one timestamped initial-generation round."""
    invocation_id = scenario_generation_round_id()
    invocation_root = run_root / invocation_id
    invocation_root.mkdir(parents=True, exist_ok=False)
    config = ScenarioGenerationInvocationConfig(
        schema_version="1.0.0",
        run_id=run_id,
        invocation_id=invocation_id,
        stage=stage,
        scenario_ids=[replication.scenario_id for _, replication in selected],
        backend=backend_specification,
        created_at=_timestamp_from_round_id(invocation_id),
    )
    write_model_json_atomic(invocation_root / "invocation_config.json", config)
    return invocation_root


def _load_evaluation_example(use_case_id: str) -> AcceptedScenario:
    """Load the matching C1 exclusively from the current published records."""
    scenario_id = f"{use_case_id}_C1"
    path = ACTIVE_SCENARIO_ACCEPTED_ROOT / scenario_id / "accepted_scenario.json"
    if not path.is_file():
        raise ValueError(f"R1/R2 generation requires published scenario {scenario_id}")
    accepted = read_model_json(path, AcceptedScenario)
    validate_accepted_scenario_hash(accepted)
    if accepted.scenario_id != scenario_id or accepted.use_case_id != use_case_id:
        raise ValueError("published C1 record does not match the selected use case")
    return accepted


def _write_generation_failure(output_root: Path, scenario_id: str, error: Exception) -> None:
    """Persist one generation failure while leaving the scenario eligible for retry."""
    recorded_at = utc_now()
    payload = {
        "schema_version": "3.0.0",
        "scenario_id": scenario_id,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "recorded_at": recorded_at,
    }
    record = ScenarioPipelineFailureRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)})
    timestamp = recorded_at.strftime("%Y%m%dT%H%M%S%fZ")
    write_model_json_atomic(output_root / scenario_id / "failures" / f"{timestamp}.json", record)


def main() -> None:
    """Generate initial candidates without review, revision, or publication gates."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--stage", choices=[stage.value for stage in ScenarioStage], required=True)
    parser.add_argument("--use-case-id")
    parser.add_argument("--scenario-id")
    parser.add_argument("--run-id", required=True, help="Create or resume a named run such as scenario_set_v1")
    parser.add_argument("--output-root", type=Path, default=ACTIVE_SCENARIO_GENERATION_ROOT)
    args = parser.parse_args()

    if args.output_root.resolve() != ACTIVE_SCENARIO_GENERATION_ROOT.resolve():
        raise ValueError(f"scenario output must remain under the active {ACTIVE_SCENARIO_SEED_VERSION} root")
    seed = load_and_validate_seed(
        seed_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        schema_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        query_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        query_schema_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    stage = ScenarioStage(args.stage)
    selected = _select_stage_seeds(seed.use_cases, stage, args.use_case_id, args.scenario_id)
    run_id, run_root = _prepare_run_root(args.run_id)
    current = current_scenario_artifacts(run_root)
    selected = [item for item in selected if item[1].scenario_id not in current]
    if not selected:
        print(f"Run {run_id} already contains every selected initial candidate")
        return

    round_root = _create_invocation_root(run_root, run_id, stage, selected, args.backend)
    backend = _load_backend(args.backend, round_root)
    generated_ids: List[str] = []
    for use_case, replication in selected:
        scenario_id = replication.scenario_id
        try:
            fixed_example = _load_evaluation_example(use_case.use_case_id) if stage == ScenarioStage.EVALUATION else None
            examples = {use_case.use_case_id: fixed_example} if fixed_example is not None else None
            candidate = generate_initial_candidates([(use_case, replication)], backend, examples)[scenario_id]
            write_model_json_atomic(round_root / "scenarios" / scenario_id / "candidate.json", candidate)
        except Exception as error:
            _write_generation_failure(round_root / "scenarios", scenario_id, error)
            raise
        generated_ids.append(scenario_id)
    print(f"Generated {len(generated_ids)} initial candidate(s): {', '.join(generated_ids)}")
    print(f"Round root: {round_root}")


if __name__ == "__main__":
    main()
