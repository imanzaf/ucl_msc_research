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
    EvaluatedModelManifest,
    ExperimentManifest,
    FreezeStatus,
    PromptReviewDecision,
    PromptReviewManifest,
    ScoringExecutionManifest,
    WordBudgetManifest,
)
from src.data_models.study import EXPERIMENT_DIMENSIONS, ExperimentName
from src.experiments.layout import validate_experiment_path
from src.paths import EVALUATED_MODEL_MANIFEST_PATH, REPO_ROOT, WORD_BUDGET_MANIFEST_PATH
from src.prompts.experiment import prompt_package_sha256
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Authenticate protocol inputs and freeze calibration plus three experiment manifests."""
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
    parser.add_argument("--material-priority-output", type=Path, required=True)
    parser.add_argument("--brevity-locus-output", type=Path, required=True)
    args = parser.parse_args()
    if args.evaluated_model_manifest.resolve() != EVALUATED_MODEL_MANIFEST_PATH.resolve():
        raise ValueError("experiment manifests must use the canonical frozen evaluated-model manifest")
    if args.word_budget_manifest.resolve() != WORD_BUDGET_MANIFEST_PATH.resolve():
        raise ValueError("experiment manifests must use the canonical V1.0.0 word-budget manifest")
    calibration_path = REPO_ROOT / "data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json"
    if args.calibration_output.resolve() != calibration_path.resolve():
        raise ValueError("calibration manifest must use the fixed risk_comm_calibration_v1 checkpoint path")
    validate_experiment_path(args.experiment_output, REPO_ROOT, "manifest", "risk_comm_v1")
    validate_experiment_path(args.material_priority_output, REPO_ROOT, "manifest", "material_priority_v1")
    validate_experiment_path(args.brevity_locus_output, REPO_ROOT, "manifest", "brevity_locus_v1")
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    models = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, PromptReviewManifest)
    scoring = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    budget = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    for manifest in [accepted, models, prompt_review, scoring, budget]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if models.freeze_status != FreezeStatus.FROZEN or scoring.freeze_status != FreezeStatus.FROZEN or budget.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("experiment manifests require frozen model, scoring, and budget inputs")
    if prompt_review.decision != PromptReviewDecision.APPROVE:
        raise ValueError("experiment manifests require an approved prompt self-review")
    if prompt_review.accepted_scenario_manifest_sha256 != accepted.manifest_sha256:
        raise ValueError("prompt review does not bind the accepted scenarios used by the experiment")
    if budget.evaluated_model_manifest_sha256 != models.manifest_sha256:
        raise ValueError("word-budget feasibility was not established with the evaluated models used by the experiment")
    if scoring.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("scoring manifest does not bind the active contracts")
    retry = RetryPolicy(max_retries=args.max_retries, backoff_seconds=args.backoff_seconds, reuse_identical_prompt_bytes=True)
    frozen_at = datetime.now(timezone.utc)
    calibration_payload = {
        "schema_version": "2.0.0",
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
        "schema_version": "2.0.0",
        "experiment_name": "risk_comm_v1",
        "expected_conversation_count": EXPERIMENT_DIMENSIONS[ExperimentName.RISK_COMM_V1].conversation_count,
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
    material_payload = {
        **experiment_payload,
        "experiment_name": "material_priority_v1",
        "expected_conversation_count": EXPERIMENT_DIMENSIONS[ExperimentName.MATERIAL_PRIORITY_V1].conversation_count,
    }
    material = ExperimentManifest.model_validate({**material_payload, "manifest_sha256": artifact_sha256(material_payload)})
    brevity_payload = {
        **experiment_payload,
        "experiment_name": "brevity_locus_v1",
        "expected_conversation_count": EXPERIMENT_DIMENSIONS[ExperimentName.BREVITY_LOCUS_V1].conversation_count,
    }
    brevity = ExperimentManifest.model_validate({**brevity_payload, "manifest_sha256": artifact_sha256(brevity_payload)})
    write_model_json_atomic(args.calibration_output, calibration)
    write_model_json_atomic(args.experiment_output, experiment)
    write_model_json_atomic(args.material_priority_output, material)
    write_model_json_atomic(args.brevity_locus_output, brevity)
    print("Wrote separate frozen calibration, primary, material-priority, and brevity-locus manifests")


if __name__ == "__main__":
    main()
