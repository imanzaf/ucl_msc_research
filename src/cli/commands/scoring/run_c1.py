"""Score the resumable single-model C1 2×2 diagnostic."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.cli.commands.calibration.run_c1 import ACCEPTED_MANIFEST_PATH, DEFAULT_EXPERIMENT_NAME
from src.cli.commands.scoring.run import execute_scoring_transcripts
from src.data_models.common import validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunUnit
from src.data_models.manifests import AcceptedScenarioManifest, C1EvaluationConfig, FreezeStatus, ScoringExecutionManifest
from src.data_models.scoring import ManualScoringQueueRecord, ScoredConversationBundle
from src.experiments.c1_assets import generate_c1_paper_assets
from src.experiments.io import load_accepted_calibration_scenarios
from src.experiments.openrouter_scoring import OpenRouterScoringBackend
from src.experiments.scenario_runner import validate_c1_single_model_plan_against_inputs
from src.llm.openrouter import OpenRouterClient
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, REPO_ROOT
from src.prompts.experiment import prompt_package_sha256
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import read_model_json, read_model_jsonl


def main() -> None:
    """Resume automated scoring for every completed C1 conversation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-name", default=DEFAULT_EXPERIMENT_NAME)
    parser.add_argument("--accepted-root", type=Path, default=ACTIVE_SCENARIO_ACCEPTED_ROOT)
    parser.add_argument("--accepted-scenario-manifest", type=Path, default=ACCEPTED_MANIFEST_PATH)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("C1 automated scoring may call paid APIs and requires --execute-paid")
    experiment_dir = REPO_ROOT / "data/outputs/experiments" / args.experiment_name
    config = read_model_json(experiment_dir / "config.json", C1EvaluationConfig)
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    scoring_manifest = read_model_json(
        experiment_dir / "checkpoints/scoring_execution_manifest.json",
        ScoringExecutionManifest,
    )
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
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
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted_manifest)
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
