"""Freeze researcher review of the twenty C1 requests before the ample pilot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    CalibrationPromptReviewManifest,
    CalibrationRenderedRequestReview,
    PromptReviewDecision,
    ScenarioManifestScope,
)
from src.data_models.study import PROMPT_PACKAGE_VERSION
from src.experiments.io import load_accepted_calibration_scenarios
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_CHECKPOINT_ROOT, ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.experiment import validate_complete_request_reviews
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Validate all C1 request reviews and write the pre-R1-R2 prompt gate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-reviews", type=Path, required=True, help="JSON array containing all twenty C1 review records")
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--calibration-scenario-manifest", type=Path, required=True)
    parser.add_argument("--researcher-notes", required=True)
    parser.add_argument("--decision", choices=[PromptReviewDecision.APPROVE.value], required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_manifest = ACTIVE_SCENARIO_INPUT_ROOT / "calibration_accepted_scenario_manifest.json"
    expected_output = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "calibration_prompt_review.json"
    if args.accepted_root.resolve() != ACTIVE_SCENARIO_ACCEPTED_ROOT.resolve():
        raise ValueError("calibration prompt review must use the active V1.0.0 accepted root")
    if args.calibration_scenario_manifest.resolve() != expected_manifest.resolve():
        raise ValueError("calibration prompt review must use the fixed calibration accepted-set manifest")
    if args.output.resolve() != expected_output.resolve():
        raise ValueError("calibration prompt review must use the active scenario checkpoint path")
    if args.output.exists():
        raise FileExistsError("the frozen calibration prompt-review manifest already exists and cannot be replaced")
    raw = json.loads(args.request_reviews.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("calibration request-review input must be a JSON array")
    reviews = [CalibrationRenderedRequestReview.model_validate(item) for item in raw]
    accepted = read_model_json(args.calibration_scenario_manifest, AcceptedScenarioManifest)
    validate_model_self_hash(accepted, "manifest_sha256")
    if accepted.manifest_scope != ScenarioManifestScope.CALIBRATION:
        raise ValueError("calibration prompt review requires a calibration-scope accepted manifest")
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted)
    validate_complete_request_reviews(reviews, scenarios)
    payload = {
        "schema_version": "3.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "accepted_scenario_manifest_sha256": accepted.manifest_sha256,
        "request_reviews": reviews,
        "researcher_notes": args.researcher_notes,
        "decision": PromptReviewDecision(args.decision),
        "reviewed_by": args.reviewed_by,
        "reviewed_at": datetime.now(timezone.utc),
    }
    manifest = CalibrationPromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote reviewed V3 calibration prompt manifest for {len(reviews)} complete requests")


if __name__ == "__main__":
    main()
