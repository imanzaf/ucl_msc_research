"""Build separate offline run plans for the two exploratory experiments."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import validate_model_self_hash
from src.data_models.experiments import ExperimentConfig
from src.data_models.manifests import AcceptedScenarioManifest, ExperimentManifest, FreezeStatus, WordBudgetManifest
from src.data_models.study import ExperimentName
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import build_brevity_locus_run_plan, build_material_priority_run_plan
from src.paths import REPO_ROOT
from src.prompts.experiment import prompt_package_sha256
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import read_model_json, write_model_json_atomic, write_models_jsonl_atomic


def _write_plan(
    experiment_name: ExperimentName,
    manifest: ExperimentManifest,
    accepted_manifest: AcceptedScenarioManifest,
    accepted_root: Path,
    budget_manifest: WordBudgetManifest,
    config_output: Path,
    plan_output: Path,
) -> None:
    """Authenticate one manifest and write its exact offline plan and config."""
    if manifest.experiment_name != experiment_name:
        raise ValueError("exploratory manifest name does not match requested run plan")
    scenarios = load_accepted_evaluation_scenarios(accepted_root, accepted_manifest)
    created_at = datetime.now(timezone.utc)
    if experiment_name == ExperimentName.MATERIAL_PRIORITY_V1:
        units = build_material_priority_run_plan(scenarios, manifest.evaluated_models, budget_manifest, manifest.randomisation_seed, created_at)
        cell_count = 2
    else:
        units = build_brevity_locus_run_plan(scenarios, manifest.evaluated_models, manifest.randomisation_seed, created_at)
        cell_count = 1
    config = ExperimentConfig(
        schema_version="2.0.0",
        experiment_name=experiment_name,
        experiment_manifest_sha256=manifest.manifest_sha256,
        scenario_count=40,
        evaluated_model_count=3,
        source_order_count=1,
        cell_count=cell_count,
        expected_conversation_count=len(units),
        expected_agent_response_count=len(units) * 2,
        randomisation_seed=manifest.randomisation_seed,
        retry_policy=manifest.retry_policy,
        created_at=created_at,
    )
    validate_experiment_path(config_output, REPO_ROOT, "config", experiment_name.value)
    validate_experiment_path(plan_output, REPO_ROOT, "checkpoint", experiment_name.value)
    write_model_json_atomic(config_output, config)
    write_models_jsonl_atomic(plan_output, units)


def main() -> None:
    """Build both exploratory matrices without making provider calls."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, default=REPO_ROOT / "data/inputs/scenarios/v0.5.2/accepted")
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--word-budget-manifest", type=Path, required=True)
    parser.add_argument("--material-priority-manifest", type=Path, required=True)
    parser.add_argument("--material-priority-config", type=Path, required=True)
    parser.add_argument("--material-priority-plan", type=Path, required=True)
    parser.add_argument("--brevity-locus-manifest", type=Path, required=True)
    parser.add_argument("--brevity-locus-config", type=Path, required=True)
    parser.add_argument("--brevity-locus-plan", type=Path, required=True)
    args = parser.parse_args()
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    budget = read_model_json(args.word_budget_manifest, WordBudgetManifest)
    material = read_model_json(args.material_priority_manifest, ExperimentManifest)
    brevity = read_model_json(args.brevity_locus_manifest, ExperimentManifest)
    for manifest in [accepted, budget, material, brevity]:
        validate_model_self_hash(manifest, "manifest_sha256")
    for manifest in [material, brevity]:
        if manifest.freeze_status != FreezeStatus.FROZEN:
            raise ValueError("exploratory plan construction requires frozen experiment manifests")
        if manifest.accepted_scenario_manifest_sha256 != accepted.manifest_sha256:
            raise ValueError("exploratory manifest does not bind the supplied accepted scenarios")
        if manifest.word_budget_manifest_sha256 != budget.manifest_sha256:
            raise ValueError("exploratory manifest does not bind the supplied word budgets")
        if manifest.prompt_package_sha256 != prompt_package_sha256():
            raise ValueError("exploratory manifest does not bind the active prompt package")
        if manifest.scoring_contract_sha256 != scoring_contract_sha256():
            raise ValueError("exploratory manifest does not bind the active scoring contract")
    _write_plan(
        ExperimentName.MATERIAL_PRIORITY_V1,
        material,
        accepted,
        args.accepted_root,
        budget,
        args.material_priority_config,
        args.material_priority_plan,
    )
    _write_plan(
        ExperimentName.BREVITY_LOCUS_V1,
        brevity,
        accepted,
        args.accepted_root,
        budget,
        args.brevity_locus_config,
        args.brevity_locus_plan,
    )
    print("Wrote 240 material-priority and 120 brevity-locus offline run units")


if __name__ == "__main__":
    main()
