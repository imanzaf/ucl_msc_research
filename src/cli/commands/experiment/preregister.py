"""Build the preregistration package before any paid main execution."""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.analysis.provenance import analysis_code_sha256
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.experiments import ExperimentConfig, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AnnotationSampleManifest,
    EvaluatedModelManifest,
    ExperimentManifest,
    FreezeStatus,
    PowerSimulationReport,
    PreregistrationManifest,
    SmallestEffectManifest,
    WordBudgetManifest,
)
from src.data_models.scenarios import ScenarioStage
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.scenario_runner import validate_run_plan_against_frozen_inputs
from src.paths import REPO_ROOT
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def main() -> None:
    """Validate all gate-seven inputs and write one backward-only preregistration manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--experiment-config", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    parser.add_argument("--calibration-annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--power-report", type=Path, required=True)
    parser.add_argument("--smallest-effect-manifest", type=Path, required=True)
    parser.add_argument("--analysis-plan", type=Path, required=True)
    parser.add_argument("--protocol-deviation-policy", type=Path, required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = read_model_json(args.experiment_manifest, ExperimentManifest)
    config = read_model_json(args.experiment_config, ExperimentConfig)
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    budget = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    models = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    annotation_sample = read_model_json(args.calibration_annotation_sample_manifest, AnnotationSampleManifest)
    power = read_model_json(args.power_report, PowerSimulationReport)
    smallest = read_model_json(args.smallest_effect_manifest, SmallestEffectManifest)
    for manifest, hash_field in [
        (experiment, "manifest_sha256"),
        (accepted, "manifest_sha256"),
        (budget, "manifest_sha256"),
        (models, "manifest_sha256"),
        (annotation_sample, "manifest_sha256"),
        (power, "report_sha256"),
        (smallest, "manifest_sha256"),
    ]:
        validate_model_self_hash(manifest, hash_field)
    if experiment.freeze_status != FreezeStatus.FROZEN or budget.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("preregistration requires frozen experiment and word-budget manifests")
    if smallest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("preregistration requires frozen smallest effects")
    if config.experiment_manifest_sha256 != experiment.manifest_sha256:
        raise ValueError("experiment config does not bind the supplied experiment manifest")
    if experiment.accepted_scenario_manifest_sha256 != accepted.manifest_sha256:
        raise ValueError("experiment does not bind the accepted scenario set")
    if experiment.word_budget_manifest_sha256 != budget.manifest_sha256:
        raise ValueError("experiment does not bind the word-budget manifest")
    if experiment.evaluated_model_manifest_sha256 != models.manifest_sha256 or experiment.evaluated_models != models.evaluated_models:
        raise ValueError("experiment does not bind the supplied evaluated-model snapshots")
    if annotation_sample.sample_stage != ScenarioStage.CALIBRATION:
        raise ValueError("gate-seven preregistration must bind the calibration annotation sample")
    if annotation_sample.scoring_execution_manifest_sha256 != experiment.scoring_execution_manifest_sha256:
        raise ValueError("calibration annotation sample does not bind the experiment's frozen scoring package")
    if power.smallest_effect_manifest_sha256 != smallest.manifest_sha256:
        raise ValueError("power report does not bind the supplied smallest-effect manifest")
    if experiment.retry_policy != config.retry_policy:
        raise ValueError("experiment manifest and config disagree on the frozen retry policy")
    if experiment.randomisation_seed != config.randomisation_seed:
        raise ValueError("experiment manifest and config disagree on randomisation seed")
    validate_run_plan_against_frozen_inputs(
        read_model_jsonl(args.run_plan, RunUnit),
        load_accepted_evaluation_scenarios(args.accepted_root, accepted),
        models.evaluated_models,
        budget,
        config.randomisation_seed,
    )
    analysis_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    payload = {
        "schema_version": "2.0.0",
        "experiment_manifest_sha256": experiment.manifest_sha256,
        "experiment_config_sha256": artifact_sha256(config),
        "run_plan_sha256": file_sha256(args.run_plan),
        "accepted_scenario_manifest_sha256": accepted.manifest_sha256,
        "word_budget_manifest_sha256": budget.manifest_sha256,
        "calibration_annotation_sample_manifest_sha256": annotation_sample.manifest_sha256,
        "analysis_commit": analysis_commit,
        "analysis_code_sha256": analysis_code_sha256(REPO_ROOT),
        "power_report_sha256": power.report_sha256,
        "smallest_effects_sha256": smallest.manifest_sha256,
        "retry_policy_sha256": artifact_sha256(config.retry_policy),
        "analysis_plan_sha256": file_sha256(args.analysis_plan),
        "protocol_deviation_policy_sha256": file_sha256(args.protocol_deviation_policy),
        "frozen_at": datetime.now(timezone.utc),
        "frozen_by": args.frozen_by,
    }
    preregistration = PreregistrationManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, preregistration)
    print(f"Wrote pre-paid-execution preregistration manifest to {args.output}")


if __name__ == "__main__":
    main()
