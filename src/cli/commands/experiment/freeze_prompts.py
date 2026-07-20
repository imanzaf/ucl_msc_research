"""Persist the required researcher self-review of the exact active cue wording."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256
from src.data_models.manifests import CueReviewDecision, PromptReviewManifest
from src.data_models.study import NEUTRAL_CUE, PROMPT_PACKAGE_VERSION, WORRIED_CUE
from src.storage import write_model_json_atomic


def main() -> None:
    """Build a strict cue review; model calibration remains blocked unless it approves."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--neutral-natural", action="store_true")
    parser.add_argument("--worried-natural", action="store_true")
    parser.add_argument("--semantic-request-equivalent", action="store_true")
    parser.add_argument("--urgency-confounded", action="store_true")
    parser.add_argument("--desired-detail-confounded", action="store_true")
    parser.add_argument("--decision-preference-confounded", action="store_true")
    parser.add_argument("--risk-appetite-confounded", action="store_true")
    parser.add_argument("--decision", type=CueReviewDecision, choices=list(CueReviewDecision), required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = {
        "schema_version": "1.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "neutral_cue": NEUTRAL_CUE,
        "worried_cue": WORRIED_CUE,
        "neutral_natural": args.neutral_natural,
        "worried_natural": args.worried_natural,
        "semantic_request_equivalent": args.semantic_request_equivalent,
        "urgency_confounded": args.urgency_confounded,
        "desired_detail_confounded": args.desired_detail_confounded,
        "decision_preference_confounded": args.decision_preference_confounded,
        "risk_appetite_confounded": args.risk_appetite_confounded,
        "researcher_notes": args.notes,
        "decision": args.decision,
        "reviewed_by": args.reviewed_by,
        "reviewed_at": datetime.now(timezone.utc),
    }
    manifest = PromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote cue self-review manifest to {args.output}")


if __name__ == "__main__":
    main()
