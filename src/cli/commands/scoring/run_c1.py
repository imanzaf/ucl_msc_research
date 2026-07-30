"""Score the resumable single-model C1 2×2 diagnostic."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from src.cli.commands.calibration.run_c1 import ACCEPTED_MANIFEST_PATH, DEFAULT_AGENT_MODEL_ID, DEFAULT_EXPERIMENT_NAME
from src.cli.commands.scoring.run import execute_scoring_transcripts
from src.data_models.common import artifact_sha256, file_sha256, utc_now, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus, RunUnit
from src.data_models.manifests import AcceptedScenarioManifest, C1EvaluationConfig, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import C1ScoringRerunSourceManifest, ManualScoringQueueRecord, ScoredConversationBundle
from src.experiments.c1_assets import generate_c1_paper_assets
from src.experiments.io import load_accepted_calibration_scenarios, prepare_experiment_dir
from src.experiments.openrouter_scoring import OpenRouterScoringBackend
from src.experiments.scenario_runner import validate_c1_single_model_plan_against_inputs
from src.llm.openrouter import OpenRouterClient
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, REPO_ROOT
from src.prompts.experiment import prompt_package_sha256
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import atomic_write_bytes, read_model_json, read_model_jsonl, write_model_json_atomic

DEFAULT_SOURCE_EXPERIMENT_NAME = "c1_llama_2x2_v3"


def _validate_source_outputs(
    source_dir: Path,
    accepted_manifest: AcceptedScenarioManifest,
    scenarios: List[AcceptedScenario],
) -> tuple[C1EvaluationConfig, ScoringExecutionManifest, List[RunUnit], List[ConversationTranscript], Path]:
    """Load and authenticate one complete Llama C1 evaluated-model run."""
    source_config_path = source_dir / "config.json"
    source_config = read_model_json(source_config_path, C1EvaluationConfig)
    source_scoring_manifest = read_model_json(
        source_dir / "checkpoints/scoring_execution_manifest.json",
        ScoringExecutionManifest,
    )
    validate_model_self_hash(source_scoring_manifest, "manifest_sha256")
    if source_config.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("source C1 config binds a different accepted-scenario manifest")
    if source_config.prompt_package_sha256 != prompt_package_sha256():
        raise ValueError("source C1 config binds a different evaluated-model prompt package")
    if source_config.scoring_execution_manifest_sha256 != source_scoring_manifest.manifest_sha256:
        raise ValueError("source C1 config does not bind its scoring-execution manifest")
    if source_config.evaluated_model.model_id != DEFAULT_AGENT_MODEL_ID:
        raise ValueError("source C1 evaluated-model outputs are not the frozen Llama model")
    run_plan_path = source_dir / "checkpoints/run_plan.jsonl"
    run_units = read_model_jsonl(run_plan_path, RunUnit)
    validate_c1_single_model_plan_against_inputs(run_units, scenarios, source_config)
    transcript_path = source_dir / "results" / source_config.results_filename
    transcripts = read_model_jsonl(transcript_path, ConversationTranscript)
    if len(transcripts) != 40 or any(transcript.outcome_status != RunOutcomeStatus.COMPLETED for transcript in transcripts):
        raise ValueError("source C1 scoring rerun requires exactly 40 completed transcripts")
    run_units_by_id = {run_unit.run_unit_id: run_unit for run_unit in run_units}
    if set(run_units_by_id) != {transcript.run_unit.run_unit_id for transcript in transcripts}:
        raise ValueError("source C1 transcripts do not cover the complete immutable run plan")
    if any(
        transcript.run_unit.model_dump(mode="json") != run_units_by_id[transcript.run_unit.run_unit_id].model_dump(mode="json")
        for transcript in transcripts
    ):
        raise ValueError("source C1 transcripts do not embed their exact immutable run units")
    return source_config, source_scoring_manifest, run_units, transcripts, transcript_path


def _fresh_scoring_manifest(
    source_manifest: ScoringExecutionManifest,
    frozen_by: str,
) -> ScoringExecutionManifest:
    """Freeze the active six-call contract around the source judge snapshot."""
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "judge_model_ids": source_manifest.judge_model_ids,
        "judge_snapshots": source_manifest.judge_snapshots,
        "scoring_contract_sha256": scoring_contract_sha256(),
        "fact_order_seed": source_manifest.fact_order_seed,
        "retry_policy": source_manifest.retry_policy,
        "frozen_at": utc_now(),
        "frozen_by": frozen_by,
    }
    return ScoringExecutionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})


def _validate_existing_rerun(
    target_dir: Path,
    source_dir: Path,
    source_config: C1EvaluationConfig,
    source_transcript_path: Path,
) -> None:
    """Require an existing scoring-only target to retain its exact source bytes."""
    source_manifest = read_model_json(
        target_dir / "checkpoints/scoring_rerun_source_manifest.json",
        C1ScoringRerunSourceManifest,
    )
    validate_model_self_hash(source_manifest, "manifest_sha256")
    target_config = read_model_json(target_dir / "config.json", C1EvaluationConfig)
    target_scoring_manifest = read_model_json(
        target_dir / "checkpoints/scoring_execution_manifest.json",
        ScoringExecutionManifest,
    )
    validate_model_self_hash(target_scoring_manifest, "manifest_sha256")
    expected = {
        "source_experiment_name": source_config.experiment_name,
        "target_experiment_name": target_config.experiment_name,
        "source_config_sha256": file_sha256(source_dir / "config.json"),
        "source_run_plan_sha256": file_sha256(source_dir / "checkpoints/run_plan.jsonl"),
        "source_transcripts_sha256": file_sha256(source_transcript_path),
        "target_scoring_execution_manifest_sha256": target_scoring_manifest.manifest_sha256,
    }
    if any(getattr(source_manifest, field) != value for field, value in expected.items()):
        raise ValueError("existing C1 scoring-only target no longer matches its source manifest")
    if file_sha256(target_dir / "checkpoints/run_plan.jsonl") != source_manifest.source_run_plan_sha256:
        raise ValueError("existing C1 scoring-only target run plan differs from its source")
    if file_sha256(target_dir / "results" / target_config.results_filename) != source_manifest.source_transcripts_sha256:
        raise ValueError("existing C1 scoring-only target transcripts differ from its source")


def prepare_scoring_rerun(
    experiment_name: str,
    source_experiment_name: str,
    frozen_by: str | None,
    accepted_manifest: AcceptedScenarioManifest,
    scenarios: List[AcceptedScenario],
) -> Path:
    """Create or validate a new C1 version that reuses only immutable Llama transcripts."""
    if experiment_name == source_experiment_name:
        raise ValueError("C1 scoring rerun target must be a new experiment version")
    experiment_root = REPO_ROOT / "data/outputs/experiments"
    source_dir = experiment_root / source_experiment_name
    source_config, source_scoring_manifest, _run_units, _transcripts, source_transcript_path = _validate_source_outputs(
        source_dir,
        accepted_manifest,
        scenarios,
    )
    target_dir = prepare_experiment_dir(experiment_root, experiment_name)
    target_config_path = target_dir / "config.json"
    if target_config_path.exists():
        _validate_existing_rerun(target_dir, source_dir, source_config, source_transcript_path)
        return target_dir
    if frozen_by is None:
        raise ValueError("--frozen-by is required when preparing a new C1 scoring-only version")
    scoring_manifest = _fresh_scoring_manifest(source_scoring_manifest, frozen_by)
    target_config = C1EvaluationConfig.model_validate(
        {
            **source_config.model_dump(mode="json"),
            "experiment_name": experiment_name,
            "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
        }
    )
    target_plan_path = target_dir / "checkpoints/run_plan.jsonl"
    target_transcript_path = target_dir / "results" / target_config.results_filename
    atomic_write_bytes(target_plan_path, (source_dir / "checkpoints/run_plan.jsonl").read_bytes())
    atomic_write_bytes(target_transcript_path, source_transcript_path.read_bytes())
    write_model_json_atomic(target_dir / "checkpoints/scoring_execution_manifest.json", scoring_manifest)
    write_model_json_atomic(target_config_path, target_config)
    payload = {
        "schema_version": "3.0.0",
        "source_experiment_name": source_experiment_name,
        "target_experiment_name": experiment_name,
        "source_config_sha256": file_sha256(source_dir / "config.json"),
        "source_run_plan_sha256": file_sha256(source_dir / "checkpoints/run_plan.jsonl"),
        "source_transcripts_sha256": file_sha256(source_transcript_path),
        "target_scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
        "prepared_by": frozen_by,
        "prepared_at": utc_now(),
    }
    source_manifest = C1ScoringRerunSourceManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(target_dir / "checkpoints/scoring_rerun_source_manifest.json", source_manifest)
    return target_dir


def main() -> None:
    """Resume automated scoring for every completed C1 conversation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-name", default=DEFAULT_EXPERIMENT_NAME)
    parser.add_argument("--source-experiment-name", default=DEFAULT_SOURCE_EXPERIMENT_NAME)
    parser.add_argument("--frozen-by")
    parser.add_argument("--accepted-root", type=Path, default=ACTIVE_SCENARIO_ACCEPTED_ROOT)
    parser.add_argument("--accepted-scenario-manifest", type=Path, default=ACCEPTED_MANIFEST_PATH)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("C1 automated scoring may call paid APIs and requires --execute-paid")
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted_manifest)
    experiment_dir = prepare_scoring_rerun(
        experiment_name=args.experiment_name,
        source_experiment_name=args.source_experiment_name,
        frozen_by=args.frozen_by,
        accepted_manifest=accepted_manifest,
        scenarios=scenarios,
    )
    config = read_model_json(experiment_dir / "config.json", C1EvaluationConfig)
    scoring_manifest = read_model_json(
        experiment_dir / "checkpoints/scoring_execution_manifest.json",
        ScoringExecutionManifest,
    )
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("C1 scoring requires a frozen scoring-execution manifest")
    if config.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("C1 config binds a different accepted-scenario manifest")
    if config.prompt_package_sha256 != prompt_package_sha256():
        raise ValueError("C1 config binds a different prompt package")
    if config.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
        raise ValueError("C1 config binds a different scoring-execution manifest")
    if scoring_manifest.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("C1 scoring manifest binds a different scoring contract")
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    run_units = read_model_jsonl(experiment_dir / "checkpoints/run_plan.jsonl", RunUnit)
    validate_c1_single_model_plan_against_inputs(run_units, scenarios, config)
    transcript_path = experiment_dir / "results" / config.results_filename
    transcripts = read_model_jsonl(transcript_path, ConversationTranscript)
    if len(transcripts) != 40:
        raise ValueError(f"C1 scoring requires all 40 terminal transcripts; found {len(transcripts)}")
    judge = scoring_manifest.judge_snapshots[0]
    client = OpenRouterClient.from_settings(
        get_api_settings(),
        get_model_settings(),
        OpenRouterCredentialRole.SCORING,
        structured_log_dir=experiment_dir / "cache/scoring",
    )
    backend = OpenRouterScoringBackend(client=client, judge_snapshot=judge)
    results_dir = experiment_dir / "results"
    execute_scoring_transcripts(
        transcripts=transcripts,
        scenarios=scenario_by_id,
        scoring_manifest=scoring_manifest,
        results_dir=results_dir,
        backend=backend,
    )
    bundles = read_model_jsonl(results_dir / "scored_conversations.jsonl", ScoredConversationBundle)
    queued = read_model_jsonl(results_dir / "manual_scoring_queue.jsonl", ManualScoringQueueRecord)
    generate_c1_paper_assets(transcripts, bundles, experiment_dir / "assets", config.experiment_name)
    print(f"C1 scoring terminal: {len(bundles)} automated, {len(queued)} queued, {40 - len(bundles) - len(queued)} pending")


if __name__ == "__main__":
    main()
