"""Build frozen calibration and main experiment manifests from authenticated inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import RetryPolicy
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    CalibrationExperimentManifest,
    CueReviewDecision,
    EvaluatedModelManifest,
    ExperimentManifest,
    FreezeStatus,
    PromptReviewManifest,
    ScoringExecutionManifest,
    WordBudgetManifest,
)
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.prompts.v9 import prompt_package_sha256
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Authenticate protocol inputs and freeze both paid conversation matrices."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    parser.add_argument("--randomisation-seed", type=int, default=7)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--backoff-seconds", type=float, action="append", default=[])
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--calibration-output", type=Path, required=True)
    parser.add_argument("--experiment-output", type=Path, required=True)
    args = parser.parse_args()
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    models = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, PromptReviewManifest)
    scoring = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    budget = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    for manifest in [accepted, models, prompt_review, scoring, budget]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if models.freeze_status != FreezeStatus.FROZEN or scoring.freeze_status != FreezeStatus.FROZEN or budget.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("experiment manifests require frozen model, scoring, and budget inputs")
    if prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("experiment manifests require an approved prompt self-review")
    if scoring.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("scoring manifest does not bind the active contracts")
    retry = RetryPolicy(max_retries=args.max_retries, backoff_seconds=args.backoff_seconds, reuse_identical_prompt_bytes=True)
    frozen_at = datetime.now(timezone.utc)
    calibration_payload = {
        "schema_version": "1.0.0",
        "experiment_name": "risk_comm_calibration_v1",
        "freeze_status": FreezeStatus.FROZEN,
        "evaluated_models": models.evaluated_models,
        "evaluated_model_manifest_sha256": models.manifest_sha256,
        "accepted_scenario_manifest_sha256": accepted.manifest_sha256,
        "word_budget_manifest_sha256": budget.manifest_sha256,
        "prompt_review_manifest_sha256": prompt_review.manifest_sha256,
        "prompt_package_sha256": prompt_package_sha256(),
        "decoding_temperature": 0.0,
        "randomisation_seed": args.randomisation_seed,
        "retry_policy": retry,
        "frozen_at": frozen_at,
        "frozen_by": args.frozen_by,
    }
    calibration = CalibrationExperimentManifest.model_validate({**calibration_payload, "manifest_sha256": artifact_sha256(calibration_payload)})
    experiment_payload = {
        "schema_version": "1.0.0",
        "experiment_name": "risk_comm_v1",
        "freeze_status": FreezeStatus.FROZEN,
        "evaluated_models": models.evaluated_models,
        "scoring_judge_model_ids": scoring.judge_model_ids,
        "evaluated_model_manifest_sha256": models.manifest_sha256,
        "accepted_scenario_manifest_sha256": accepted.manifest_sha256,
        "word_budget_manifest_sha256": budget.manifest_sha256,
        "prompt_review_manifest_sha256": prompt_review.manifest_sha256,
        "prompt_package_sha256": prompt_package_sha256(),
        "scoring_execution_manifest_sha256": scoring.manifest_sha256,
        "scoring_contract_sha256": scoring.scoring_contract_sha256,
        "decoding_temperature": 0.0,
        "randomisation_seed": args.randomisation_seed,
        "retry_policy": retry,
        "frozen_at": frozen_at,
    }
    experiment = ExperimentManifest.model_validate({**experiment_payload, "manifest_sha256": artifact_sha256(experiment_payload)})
    write_model_json_atomic(args.calibration_output, calibration)
    write_model_json_atomic(args.experiment_output, experiment)
    print(f"Wrote frozen calibration and main experiment manifests to {args.calibration_output} and {args.experiment_output}")


if __name__ == "__main__":
    main()
