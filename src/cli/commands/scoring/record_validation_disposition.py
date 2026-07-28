"""Record the blinded protocol contingency for failed scoring constructs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import validate_model_self_hash
from src.data_models.scoring import FailedConstructAction, ScoringConstruct, ScoringValidationReport
from src.scoring.disposition import build_validation_disposition_manifest
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Hash one allowed disposition per failed construct before treatment unblinding."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--actions-json", type=Path, required=True)
    parser.add_argument("--researcher-id", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = read_model_json(args.validation_report, ScoringValidationReport)
    validate_model_self_hash(report, "report_sha256")
    raw = json.loads(args.actions_json.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("validation actions input must be a JSON object")
    actions = {ScoringConstruct(name): FailedConstructAction(value) for name, value in raw.items()}
    manifest = build_validation_disposition_manifest(
        report,
        actions,
        report.report_sha256,
        args.researcher_id,
        args.rationale,
        datetime.now(timezone.utc),
    )
    write_model_json_atomic(args.output, manifest)
    print(f"Recorded blinded validation disposition to {args.output}")


if __name__ == "__main__":
    main()
