"""Build the frozen 120-conversation canonical-order calibration plan and config."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import validate_model_self_hash
from src.data_models.experiments import CalibrationExperimentConfig
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    CalibrationExperimentManifest,
    CueReviewDecision,
    EvaluatedModelManifest,
    FreezeStatus,
    PromptReviewManifest,
    WordBudgetManifest,
)
from src.data_models.scenarios import ScenarioStage
from src.experiments.io import load_all_accepted_scenarios, prepare_experiment_dir
from src.experiments.scenario_runner import build_calibration_run_plan
from src.paths import REPO_ROOT
from src.prompts.experiment import prompt_package_sha256
from src.storage import read_model_json, write_model_json_atomic, write_models_jsonl_atomic


def main() -> None:
    """Authenticate calibration inputs and write config before the immutable plan."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    args = parser.parse_args()
    calibration = read_model_json(args.calibration_manifest, CalibrationExperimentManifest)
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    models = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, PromptReviewManifest)
    budget = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    for manifest in [calibration, accepted, models, prompt_review, budget]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if calibration.freeze_status != FreezeStatus.FROZEN or models.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("calibration planning requires frozen calibration and evaluated-model manifests")
    if budget.freeze_status != FreezeStatus.FROZEN or prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("calibration planning requires frozen budgets and an approved cue review")
    if prompt_review.accepted_scenario_manifest_sha256 != accepted.manifest_sha256:
        raise ValueError("prompt review does not bind the accepted scenarios used by calibration")
    links = [
        (calibration.accepted_scenario_manifest_sha256, accepted.manifest_sha256),
        (calibration.evaluated_model_manifest_sha256, models.manifest_sha256),
        (calibration.prompt_review_manifest_sha256, prompt_review.manifest_sha256),
        (calibration.word_budget_manifest_sha256, budget.manifest_sha256),
    ]
    if any(expected != actual for expected, actual in links):
        raise ValueError("calibration manifest does not bind every supplied frozen input")
    if calibration.prompt_package_sha256 != prompt_package_sha256():
        raise ValueError("calibration manifest does not bind the active prompt package")
    if calibration.evaluated_models != models.evaluated_models:
        raise ValueError("calibration manifest evaluated models differ from the frozen model manifest")
    scenarios = [
        scenario for scenario in load_all_accepted_scenarios(args.accepted_root, accepted) if scenario.study_stage == ScenarioStage.CALIBRATION
    ]
    experiment_dir = prepare_experiment_dir(REPO_ROOT / "data/outputs/experiments", "risk_comm_calibration_v1")
    created_at = datetime.now(timezone.utc)
    config = CalibrationExperimentConfig(
        schema_version="2.0.0",
        experiment_name="risk_comm_calibration_v1",
        experiment_manifest_sha256=calibration.manifest_sha256,
        randomisation_seed=calibration.randomisation_seed,
        retry_policy=calibration.retry_policy,
        created_at=created_at,
    )
    write_model_json_atomic(experiment_dir / "config.json", config)
    run_units = build_calibration_run_plan(scenarios, calibration.evaluated_models, budget, calibration.randomisation_seed, created_at)
    output = experiment_dir / "checkpoints/run_plan.jsonl"
    write_models_jsonl_atomic(output, run_units)
    print(f"Wrote calibration config then {len(run_units)} immutable run units to {output}")


if __name__ == "__main__":
    main()
