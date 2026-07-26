"""Create explicit researcher cost approval for the ample pilot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import AmplePilotApproval, AmplePilotCostReport
from src.paths import AMPLE_PILOT_APPROVAL_PATH, AMPLE_PILOT_COST_REPORT_PATH
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Write an immutable approval only when its maximum covers the pilot report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost-report", type=Path, required=True)
    parser.add_argument("--approved-maximum-cost-usd", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if not args.approve:
        raise PermissionError("ample-pilot approval creation requires --approve")
    if args.cost_report.resolve() != AMPLE_PILOT_COST_REPORT_PATH.resolve():
        raise ValueError("ample-pilot approval requires the fixed cost-report path")
    if args.output.resolve() != AMPLE_PILOT_APPROVAL_PATH.resolve():
        raise ValueError("ample-pilot approval must use the active scenario checkpoint path")
    if args.output.exists():
        raise FileExistsError("the ample-pilot approval already exists and cannot be replaced")
    report = read_model_json(args.cost_report, AmplePilotCostReport)
    validate_model_self_hash(report, "report_sha256")
    if args.approved_maximum_cost_usd < report.worst_case_cost_usd:
        raise ValueError("approved maximum is below the ample-pilot worst-case cost")
    payload = {
        "schema_version": "2.0.0",
        "cost_report_sha256": report.report_sha256,
        "approved": True,
        "approved_maximum_cost_usd": args.approved_maximum_cost_usd,
        "approved_by": args.approved_by,
        "approved_at": datetime.now(timezone.utc),
    }
    approval = AmplePilotApproval.model_validate({**payload, "approval_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, approval)
    print(f"Wrote explicit ample-pilot cost approval to {args.output}")


if __name__ == "__main__":
    main()
