"""Build the immutable 240-conversation risk_comm_v1 primary run plan offline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import validate_model_self_hash
from src.data_models.experiments import ExperimentConfig
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    CueReviewDecision,
    EvaluatedModelManifest,
    ExperimentManifest,
    FreezeStatus,
    PromptReviewManifest,
    ScoringExecutionManifest,
    WordBudgetManifest,
)
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import build_run_plan, validate_complete_run_plan
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, REPO_ROOT
from src.prompts.experiment import prompt_package_sha256, validate_complete_request_reviews
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import read_model_json, write_model_json_atomic, write_models_jsonl_atomic


def parse_args() -> argparse.Namespace:
    """Parse frozen manifest and output paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, default=ACTIVE_SCENARIO_ACCEPTED_ROOT)
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    parser.add_argument("--config-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Validate all frozen inputs and write a deterministic JSONL run plan."""
    args = parse_args()
    validate_experiment_path(args.output, REPO_ROOT, "checkpoint")
    validate_experiment_path(args.config_output, REPO_ROOT, "config")
    experiment_manifest = read_model_json(args.experiment_manifest, ExperimentManifest)
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    model_manifest = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, PromptReviewManifest)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    budget_manifest = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    for manifest, hash_field in [
        (experiment_manifest, "manifest_sha256"),
        (accepted_manifest, "manifest_sha256"),
        (model_manifest, "manifest_sha256"),
        (prompt_review, "manifest_sha256"),
        (scoring_manifest, "manifest_sha256"),
        (budget_manifest, "manifest_sha256"),
    ]:
        validate_model_self_hash(manifest, hash_field)
    if experiment_manifest.freeze_status != FreezeStatus.FROZEN or budget_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("run-plan construction requires frozen experiment and word-budget manifests")
    if model_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("run-plan construction requires a frozen evaluated-model manifest")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("run-plan construction requires a frozen scoring-execution manifest")
    if prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("run-plan construction requires an approved cue review")
    if prompt_review.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("cue review does not bind the supplied accepted scenarios")
    if experiment_manifest.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the supplied accepted-scenario manifest")
    if experiment_manifest.evaluated_model_manifest_sha256 != model_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the supplied evaluated-model manifest")
    if experiment_manifest.prompt_review_manifest_sha256 != prompt_review.manifest_sha256:
        raise ValueError("experiment manifest does not bind the supplied cue-review manifest")
    if experiment_manifest.word_budget_manifest_sha256 != budget_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the supplied word-budget manifest")
    if experiment_manifest.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the supplied scoring-execution manifest")
    if experiment_manifest.prompt_package_sha256 != prompt_package_sha256():
        raise ValueError("experiment manifest does not bind the active code-owned prompt package")
    if experiment_manifest.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("experiment manifest does not bind the active condition-blind scoring contracts")
    if scoring_manifest.scoring_contract_sha256 != experiment_manifest.scoring_contract_sha256:
        raise ValueError("scoring-execution and experiment manifests bind different scoring contracts")
    if experiment_manifest.evaluated_models != model_manifest.evaluated_models:
        raise ValueError("experiment evaluated models differ from the frozen model manifest")
    if experiment_manifest.scoring_judge_model_ids != model_manifest.scoring_judge_model_ids:
        raise ValueError("experiment scoring judges differ from the frozen model manifest")
    if experiment_manifest.scoring_judge_model_ids != scoring_manifest.judge_model_ids:
        raise ValueError("experiment scoring judges differ from the scoring-execution manifest")
    scenarios = load_accepted_evaluation_scenarios(args.accepted_root, accepted_manifest)
    evaluation_entries = {entry.scenario_id: entry for entry in accepted_manifest.entries if entry.study_stage.value == "evaluation"}
    if set(evaluation_entries) != {scenario.scenario_id for scenario in scenarios}:
        raise ValueError("accepted-scenario manifest does not match loaded evaluation scenarios")
    if any(evaluation_entries[scenario.scenario_id].artifact_sha256 != scenario.artifact_sha256 for scenario in scenarios):
        raise ValueError("accepted-scenario manifest contains an artifact hash mismatch")
    validate_complete_request_reviews(prompt_review.request_reviews, scenarios)
    created_at = datetime.now(timezone.utc)
    config = ExperimentConfig(
        schema_version="2.0.0",
        experiment_name="risk_comm_v1",
        experiment_manifest_sha256=experiment_manifest.manifest_sha256,
        randomisation_seed=experiment_manifest.randomisation_seed,
        retry_policy=experiment_manifest.retry_policy,
        created_at=created_at,
    )
    write_model_json_atomic(args.config_output, config)
    run_units = build_run_plan(
        scenarios=scenarios,
        models=experiment_manifest.evaluated_models,
        randomisation_seed=experiment_manifest.randomisation_seed,
        created_at=created_at,
    )
    validate_complete_run_plan(run_units)
    write_models_jsonl_atomic(args.output, run_units)
    print(f"Wrote {len(run_units)} immutable run units to {args.output}")


if __name__ == "__main__":
    main()
