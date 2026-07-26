"""Finalize R1-R2 feasibility without changing the previously frozen tight limits."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import AcceptedScenarioManifest, FreezeStatus, TightLimitManifest, UseCaseBudget, WordBudgetManifest
from src.experiments.io import load_all_accepted_scenarios
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_CHECKPOINT_ROOT, ACTIVE_SCENARIO_INPUT_ROOT, WORD_BUDGET_MANIFEST_PATH
from src.scenarios.budgets import material_fact_word_count, validate_evaluation_headroom
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Bind accepted R1-R2 responses to immutable C1-derived limits and freeze feasibility."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--tight-limit-manifest", type=Path, required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_paths = [
        (args.accepted_root, ACTIVE_SCENARIO_ACCEPTED_ROOT),
        (args.accepted_scenario_manifest, ACTIVE_SCENARIO_INPUT_ROOT / "accepted_scenario_manifest.json"),
        (args.tight_limit_manifest, ACTIVE_SCENARIO_CHECKPOINT_ROOT / "tight_limit_manifest.json"),
        (args.output, WORD_BUDGET_MANIFEST_PATH),
    ]
    if any(supplied.resolve() != expected.resolve() for supplied, expected in expected_paths):
        raise ValueError("word-budget finalization must use the active scenario lifecycle paths")
    if args.output.exists():
        raise FileExistsError("the frozen word-budget manifest already exists and cannot be replaced")

    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    tight_manifest = read_model_json(args.tight_limit_manifest, TightLimitManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(tight_manifest, "manifest_sha256")
    if tight_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("final budget validation requires a previously frozen tight-limit manifest")
    scenarios = load_all_accepted_scenarios(args.accepted_root, accepted_manifest)
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    budgets = []
    for frozen_budget in tight_manifest.use_case_budgets:
        calibration = scenario_by_id[frozen_budget.calibration_scenario_id]
        if material_fact_word_count(calibration.material_facts) != frozen_budget.calibration_fact_word_count:
            raise ValueError("accepted C1 material fact count changed after tight-limit freeze")
        if artifact_sha256(calibration.material_facts) != frozen_budget.calibration_material_facts_sha256:
            raise ValueError("accepted C1 material facts changed after tight-limit freeze")
        evaluations = [scenario_by_id[f"{frozen_budget.use_case_id}_R{replication}"] for replication in range(1, 3)]
        evaluation_counts = {scenario.scenario_id: material_fact_word_count(scenario.material_facts) for scenario in evaluations}
        validate_evaluation_headroom(frozen_budget.tight_word_limit, evaluation_counts)
        use_case_scenarios = [calibration, *evaluations]
        budgets.append(
            UseCaseBudget(
                use_case_id=frozen_budget.use_case_id,
                calibration_scenario_id=calibration.scenario_id,
                calibration_fact_word_count=frozen_budget.calibration_fact_word_count,
                tight_word_limit=frozen_budget.tight_word_limit,
                evaluation_fact_word_counts=evaluation_counts,
                material_facts_sha256={scenario.scenario_id: artifact_sha256(scenario.material_facts) for scenario in use_case_scenarios},
            )
        )
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "counter_version": tight_manifest.counter_version,
        "tight_limit_manifest_sha256": tight_manifest.manifest_sha256,
        "evaluated_model_manifest_sha256": tight_manifest.evaluated_model_manifest_sha256,
        "use_case_budgets": budgets,
        "ample_pilot": tight_manifest.ample_pilot,
        "frozen_at": datetime.now(timezone.utc),
        "frozen_by": args.frozen_by,
    }
    manifest = WordBudgetManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote final ten-use-case word-budget feasibility manifest to {args.output}")


if __name__ == "__main__":
    main()
