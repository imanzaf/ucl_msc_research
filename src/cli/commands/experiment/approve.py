"""Create an explicit researcher approval bound to one immutable dry-run report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import DryRunCostReport, PaidExecutionApproval
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Refuse implicit approval and write a self-hashed maximum-cost authorization."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run-report", type=Path, required=True)
    parser.add_argument("--approved-maximum-cost-usd", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if not args.approve:
        raise PermissionError("approval creation requires the researcher to pass --approve explicitly")
    report = read_model_json(args.dry_run_report, DryRunCostReport)
    validate_model_self_hash(report, "report_sha256")
    if args.approved_maximum_cost_usd < report.worst_case_cost_usd:
        raise ValueError("approved maximum cost is below the dry-run worst-case estimate")
    payload = {
        "schema_version": "1.0.0",
        "experiment_name": "risk_comm_v1",
        "dry_run_report_sha256": report.report_sha256,
        "approved": True,
        "approved_maximum_cost_usd": args.approved_maximum_cost_usd,
        "approved_by": args.approved_by,
        "approved_at": datetime.now(timezone.utc),
    }
    approval = PaidExecutionApproval.model_validate({**payload, "approval_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, approval)
    print(f"Wrote explicit paid-execution approval to {args.output}")


if __name__ == "__main__":
    main()
