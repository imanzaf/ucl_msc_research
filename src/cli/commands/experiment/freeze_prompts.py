"""Freeze the four cue pairs after review of all 80 complete requests."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import AcceptedScenarioManifest, CueReviewDecision, EvaluationRenderedRequestReview, PromptReviewManifest
from src.data_models.study import CUE_PAIRS, PROMPT_PACKAGE_VERSION
from src.experiments.io import load_accepted_evaluation_scenarios
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_INPUT_ROOT, RISK_COMM_V1_MANIFEST_ROOT
from src.prompts.experiment import validate_complete_request_reviews
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Validate researcher-completed request reviews and write a self-hashed manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-reviews", type=Path, required=True, help="JSON array containing all 80 review records")
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--researcher-notes", required=True)
    parser.add_argument("--decision", choices=[CueReviewDecision.APPROVE.value], required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_manifest = ACTIVE_SCENARIO_INPUT_ROOT / "accepted_scenario_manifest.json"
    expected_output = RISK_COMM_V1_MANIFEST_ROOT / "prompt_review.json"
    if args.accepted_root.resolve() != ACTIVE_SCENARIO_ACCEPTED_ROOT.resolve():
        raise ValueError("prompt review must use the active V0.8.0 accepted root")
    if args.accepted_scenario_manifest.resolve() != expected_manifest.resolve():
        raise ValueError("prompt review must use the fixed complete accepted-set manifest")
    if args.output.resolve() != expected_output.resolve():
        raise ValueError("prompt review must use the fixed risk_comm_v1 manifest path")
    if args.output.exists():
        raise FileExistsError("the frozen prompt-review manifest already exists and cannot be replaced")
    raw = json.loads(args.request_reviews.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("request-review input must be a JSON array")
    reviews = [EvaluationRenderedRequestReview.model_validate(item) for item in raw]
    accepted = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    validate_model_self_hash(accepted, "manifest_sha256")
    scenarios = load_accepted_evaluation_scenarios(args.accepted_root, accepted)
    validate_complete_request_reviews(reviews, scenarios)
    payload = {
        "schema_version": "2.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "accepted_scenario_manifest_sha256": accepted.manifest_sha256,
        "cue_pairs": {index: list(pair) for index, pair in CUE_PAIRS.items()},
        "request_reviews": reviews,
        "researcher_notes": args.researcher_notes,
        "decision": CueReviewDecision(args.decision),
        "reviewed_by": args.reviewed_by,
        "reviewed_at": datetime.now(timezone.utc),
    }
    manifest = PromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote reviewed {PROMPT_PACKAGE_VERSION.upper()} cue manifest for {len(reviews)} complete requests")


if __name__ == "__main__":
    main()
