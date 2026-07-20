"""Execute an approved risk_comm_v1 run plan with immediate resumable persistence."""

from __future__ import annotations

import argparse
import logging
import subprocess
import time
from pathlib import Path

from src.analysis.provenance import analysis_code_sha256
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.experiments import ExperimentConfig, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    DryRunCostReport,
    EvaluatedModelManifest,
    ExperimentManifest,
    PaidExecutionApproval,
    PreregistrationManifest,
    WordBudgetManifest,
)
from src.experiments.io import load_accepted_evaluation_scenarios, read_transcript_results
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import execute_run_plan, validate_run_plan_against_frozen_inputs
from src.llm.openrouter import OpenRouterClient
from src.paths import REPO_ROOT
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import read_model_json, read_model_jsonl


def parse_args() -> argparse.Namespace:
    """Parse immutable inputs and the explicit paid-execution approval gate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    parser.add_argument("--preregistration-manifest", type=Path, required=True)
    parser.add_argument("--dry-run-report", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--execute-paid", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Verify approval linkage, resume terminal units, and execute remaining calls."""
    args = parse_args()
    if not args.execute_paid:
        raise PermissionError("refusing paid execution without --execute-paid and a linked approval record")
    validate_experiment_path(args.config, REPO_ROOT, "config")
    validate_experiment_path(args.run_plan, REPO_ROOT, "checkpoint")
    validate_experiment_path(args.results, REPO_ROOT, "result")
    validate_experiment_path(args.cache_dir, REPO_ROOT, "cache")
    validate_experiment_path(args.log, REPO_ROOT, "log")
    if args.results.name.split("_", 1)[0] != args.log.name.split("_", 1)[0]:
        raise ValueError("result and run-log filenames must share one UTC run timestamp")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(filename=args.log, level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    logging.info("Starting immutable risk_comm_v1 execution gate validation")
    config = read_model_json(args.config, ExperimentConfig)
    experiment_manifest = read_model_json(args.experiment_manifest, ExperimentManifest)
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    model_manifest = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    budget_manifest = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    preregistration = read_model_json(args.preregistration_manifest, PreregistrationManifest)
    dry_run = read_model_json(args.dry_run_report, DryRunCostReport)
    approval = read_model_json(args.approval, PaidExecutionApproval)
    validate_model_self_hash(dry_run, "report_sha256")
    validate_model_self_hash(approval, "approval_sha256")
    validate_model_self_hash(experiment_manifest, "manifest_sha256")
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(model_manifest, "manifest_sha256")
    validate_model_self_hash(budget_manifest, "manifest_sha256")
    validate_model_self_hash(preregistration, "manifest_sha256")
    if approval.dry_run_report_sha256 != dry_run.report_sha256:
        raise ValueError("paid approval does not bind the supplied dry-run report")
    if dry_run.run_plan_sha256 != file_sha256(args.run_plan):
        raise ValueError("dry-run report does not bind the supplied run plan bytes")
    if dry_run.experiment_config_sha256 != artifact_sha256(config):
        raise ValueError("dry-run report does not bind the supplied experiment config")
    if dry_run.worst_case_cost_usd > approval.approved_maximum_cost_usd:
        raise ValueError("dry-run worst-case cost exceeds the approved maximum")
    if config.experiment_manifest_sha256 != experiment_manifest.manifest_sha256:
        raise ValueError("experiment config does not bind the supplied frozen manifest")
    if preregistration.experiment_manifest_sha256 != experiment_manifest.manifest_sha256:
        raise ValueError("preregistration does not bind the supplied experiment manifest")
    if preregistration.experiment_config_sha256 != artifact_sha256(config):
        raise ValueError("preregistration does not bind the supplied experiment config")
    if preregistration.run_plan_sha256 != file_sha256(args.run_plan):
        raise ValueError("preregistration does not bind the supplied run plan")
    if preregistration.accepted_scenario_manifest_sha256 != experiment_manifest.accepted_scenario_manifest_sha256:
        raise ValueError("preregistration and experiment bind different accepted scenario sets")
    if preregistration.word_budget_manifest_sha256 != experiment_manifest.word_budget_manifest_sha256:
        raise ValueError("preregistration and experiment bind different word-budget manifests")
    if experiment_manifest.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("experiment does not bind the supplied accepted scenarios")
    if experiment_manifest.evaluated_model_manifest_sha256 != model_manifest.manifest_sha256:
        raise ValueError("experiment does not bind the supplied evaluated-model manifest")
    if experiment_manifest.evaluated_models != model_manifest.evaluated_models:
        raise ValueError("experiment evaluated snapshots differ from the supplied model manifest")
    if experiment_manifest.word_budget_manifest_sha256 != budget_manifest.manifest_sha256:
        raise ValueError("experiment does not bind the supplied word-budget manifest")
    if preregistration.retry_policy_sha256 != artifact_sha256(config.retry_policy):
        raise ValueError("preregistration does not bind the configured retry policy")
    analysis_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if analysis_head != preregistration.analysis_commit:
        raise ValueError("current analysis commit differs from the preregistered commit")
    if preregistration.analysis_code_sha256 != analysis_code_sha256(REPO_ROOT):
        raise ValueError("current analysis source bytes differ from the preregistered analysis bundle")
    run_units = read_model_jsonl(args.run_plan, RunUnit)
    validate_run_plan_against_frozen_inputs(
        run_units,
        load_accepted_evaluation_scenarios(args.accepted_root, accepted_manifest),
        model_manifest.evaluated_models,
        budget_manifest,
        config.randomisation_seed,
    )
    if dry_run.conversations != len(run_units) or dry_run.agent_responses != len(run_units) * 2:
        raise ValueError("dry-run report counts do not match the supplied run plan")
    existing = read_transcript_results(args.results)
    provider = OpenRouterClient.from_settings(
        api_settings=get_api_settings(),
        model_settings=get_model_settings(),
        credential_role=OpenRouterCredentialRole.AGENT,
        cache_dir=args.cache_dir,
    )
    completed = execute_run_plan(
        run_units=run_units,
        provider=provider,
        config=config,
        results_path=args.results,
        existing_transcripts=existing,
        paid_execution_approved=approval.approved,
    )
    logging.info("Persisted %s new terminal conversations", len(completed))
    print(f"Persisted {len(completed)} new terminal conversations to {args.results}")


if __name__ == "__main__":
    main()
