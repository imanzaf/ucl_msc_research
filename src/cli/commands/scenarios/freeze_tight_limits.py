"""Freeze C1-derived tight limits after the 60-output adequacy pilot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AmplePilotRecord,
    CalibrationPromptReviewManifest,
    CalibrationUseCaseBudget,
    CueReviewDecision,
    EvaluatedModelManifest,
    FreezeStatus,
    TightLimitManifest,
)
from src.data_models.scenario_review import ScenarioAcceptanceRecord
from src.experiments.io import load_accepted_calibration_scenarios
from src.paths import (
    ACTIVE_SCENARIO_ACCEPTED_ROOT,
    ACTIVE_SCENARIO_CHECKPOINT_ROOT,
    ACTIVE_SCENARIO_INPUT_ROOT,
    AMPLE_PILOT_RECORDS_PATH,
    EVALUATED_MODEL_MANIFEST_PATH,
)
from src.scenarios.budgets import build_ample_pilot_summary, calculate_tight_word_limit
from src.scenarios.word_count import WORD_COUNTER_VERSION
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def main() -> None:
    """Authenticate ten C1 artifacts and freeze formula-derived limits before R1-R4 generation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--calibration-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--pilot-records", type=Path, required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_calibration_manifest = ACTIVE_SCENARIO_INPUT_ROOT / "calibration_accepted_scenario_manifest.json"
    expected_prompt_review = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "calibration_prompt_review.json"
    expected_output = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "tight_limit_manifest.json"
    fixed_paths = [
        (args.accepted_root, ACTIVE_SCENARIO_ACCEPTED_ROOT),
        (args.calibration_scenario_manifest, expected_calibration_manifest),
        (args.evaluated_model_manifest, EVALUATED_MODEL_MANIFEST_PATH),
        (args.prompt_review_manifest, expected_prompt_review),
        (args.pilot_records, AMPLE_PILOT_RECORDS_PATH),
        (args.output, expected_output),
    ]
    if any(supplied.resolve() != expected.resolve() for supplied, expected in fixed_paths):
        raise ValueError("tight-limit freezing must use the fixed V0.8.0 lifecycle paths")
    if args.output.exists():
        raise FileExistsError("the frozen tight-limit manifest already exists and cannot be replaced")

    accepted_manifest = read_model_json(args.calibration_scenario_manifest, AcceptedScenarioManifest)
    model_manifest = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, CalibrationPromptReviewManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(model_manifest, "manifest_sha256")
    validate_model_self_hash(prompt_review, "manifest_sha256")
    if model_manifest.freeze_status != FreezeStatus.FROZEN or prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("tight limits require frozen evaluated-model snapshots and an approved C1 prompt review")
    if prompt_review.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("C1 prompt review does not bind the supplied calibration scenario manifest")
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted_manifest)
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    candidate_hash_by_id = {
        entry.scenario_id: read_model_json(
            args.accepted_root / Path(entry.artifact_path).parent / "acceptance_record.json",
            ScenarioAcceptanceRecord,
        ).candidate_sha256
        for entry in accepted_manifest.entries
    }
    model_hash_by_id = {snapshot.model_id: artifact_sha256(snapshot) for snapshot in model_manifest.evaluated_models}
    pilot_records = read_model_jsonl(args.pilot_records, AmplePilotRecord)
    for record in pilot_records:
        if record.model_id not in model_hash_by_id or record.model_snapshot_sha256 != model_hash_by_id[record.model_id]:
            raise ValueError("pilot record does not bind a frozen evaluated-model snapshot")
        if record.prompt_review_manifest_sha256 != prompt_review.manifest_sha256:
            raise ValueError("pilot record does not bind the supplied prompt-review manifest")
        scenario = scenario_by_id.get(record.scenario_id)
        if scenario is None or record.scenario_artifact_sha256 != scenario.artifact_sha256:
            raise ValueError("pilot record does not bind its accepted C1 scenario")
    all_complete_fit = all(
        scenario.minimal_complete_response.approved and scenario.minimal_complete_response.word_count <= 240 for scenario in scenarios
    )
    pilot_summary = build_ample_pilot_summary(pilot_records, all_complete_fit)
    budgets = [
        CalibrationUseCaseBudget(
            use_case_id=scenario.use_case_id,
            calibration_scenario_id=scenario.scenario_id,
            calibration_minimal_word_count=scenario.minimal_complete_response.word_count,
            tight_word_limit=calculate_tight_word_limit(scenario.minimal_complete_response.word_count),
            calibration_candidate_sha256=candidate_hash_by_id[scenario.scenario_id],
            calibration_minimal_response_sha256=artifact_sha256(scenario.minimal_complete_response),
            calibration_response_text_sha256=scenario.minimal_complete_response.text_sha256,
        )
        for scenario in sorted(scenarios, key=lambda item: item.use_case_id)
    ]
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "counter_version": WORD_COUNTER_VERSION,
        "prompt_review_manifest_sha256": prompt_review.manifest_sha256,
        "evaluated_model_manifest_sha256": model_manifest.manifest_sha256,
        "use_case_budgets": budgets,
        "ample_pilot": pilot_summary,
        "frozen_at": datetime.now(timezone.utc),
        "frozen_by": args.frozen_by,
    }
    manifest = TightLimitManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote frozen pre-R1-R4 tight-limit manifest to {args.output}")


if __name__ == "__main__":
    main()
