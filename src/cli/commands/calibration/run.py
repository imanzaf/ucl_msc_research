"""Execute the frozen 120-conversation rubric-calibration matrix with resume."""

from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

from src.data_models.common import validate_model_self_hash
from src.data_models.experiments import CalibrationExperimentConfig, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    CalibrationExperimentManifest,
    EvaluatedModelManifest,
    FreezeStatus,
    PromptReviewDecision,
    PromptReviewManifest,
    WordBudgetManifest,
)
from src.experiments.io import load_all_accepted_scenarios, read_transcript_results
from src.experiments.scenario_runner import execute_run_plan, validate_calibration_plan_against_frozen_inputs
from src.llm.openrouter import OpenRouterClient
from src.paths import REPO_ROOT
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import read_model_json, read_model_jsonl

CALIBRATION_RESULT_PATTERN = re.compile(r"^\d{8}T\d{6}_results\.jsonl$")
CALIBRATION_LOG_PATTERN = re.compile(r"^\d{8}T\d{6}_run\.log$")


def main() -> None:
    """Validate fixed calibration paths and execute only with an explicit paid-call flag."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("calibration may call paid APIs and requires --execute-paid")
    experiment_dir = (REPO_ROOT / "data/outputs/experiments/risk_comm_calibration_v1").resolve()
    config_path = experiment_dir / "config.json"
    plan_path = experiment_dir / "checkpoints/run_plan.jsonl"
    if args.results.resolve().parent != experiment_dir / "results" or args.log.resolve().parent != experiment_dir / "logs":
        raise ValueError("calibration results and logs must remain inside risk_comm_calibration_v1")
    if CALIBRATION_RESULT_PATTERN.fullmatch(args.results.name) is None or CALIBRATION_LOG_PATTERN.fullmatch(args.log.name) is None:
        raise ValueError("calibration result/log filenames must use their timestamped suffixes")
    if args.results.name.split("_", 1)[0] != args.log.name.split("_", 1)[0]:
        raise ValueError("calibration result and log files must share one timestamp")
    calibration = read_model_json(args.calibration_manifest, CalibrationExperimentManifest)
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    models = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, PromptReviewManifest)
    budget = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    config = read_model_json(config_path, CalibrationExperimentConfig)
    for manifest in [calibration, accepted, models, prompt_review, budget]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if calibration.freeze_status != FreezeStatus.FROZEN or config.experiment_manifest_sha256 != calibration.manifest_sha256:
        raise ValueError("calibration config does not bind the frozen calibration manifest")
    links = [
        (calibration.accepted_scenario_manifest_sha256, accepted.manifest_sha256),
        (calibration.evaluated_model_manifest_sha256, models.manifest_sha256),
        (calibration.prompt_review_manifest_sha256, prompt_review.manifest_sha256),
        (calibration.word_budget_manifest_sha256, budget.manifest_sha256),
    ]
    if any(expected != actual for expected, actual in links):
        raise ValueError("calibration manifest does not bind every supplied frozen input")
    if prompt_review.decision != PromptReviewDecision.APPROVE or calibration.evaluated_models != models.evaluated_models:
        raise ValueError("calibration inputs differ from the approved prompt or evaluated snapshots")
    run_units = read_model_jsonl(plan_path, RunUnit)
    scenarios = [scenario for scenario in load_all_accepted_scenarios(args.accepted_root, accepted) if scenario.scenario_id.endswith("_C1")]
    validate_calibration_plan_against_frozen_inputs(
        run_units,
        scenarios,
        models.evaluated_models,
        budget,
        config.randomisation_seed,
    )
    args.log.parent.mkdir(parents=True, exist_ok=True)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(filename=args.log, level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    existing = read_transcript_results(args.results)
    provider = OpenRouterClient.from_settings(
        get_api_settings(), get_model_settings(), OpenRouterCredentialRole.AGENT, cache_dir=experiment_dir / "cache"
    )
    completed = execute_run_plan(run_units, provider, config, args.results, existing, paid_execution_approved=True)
    logging.info("Persisted %s new terminal calibration conversations", len(completed))
    print(f"Persisted {len(completed)} new terminal calibration conversations to {args.results}")


if __name__ == "__main__":
    main()
