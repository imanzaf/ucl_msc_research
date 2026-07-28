"""Freeze exact scoring-judge snapshots, contracts, ordering, and retries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import RetryPolicy
from src.data_models.manifests import EvaluatedModelManifest, EvaluatedModelSnapshot, FreezeStatus, ScoringExecutionManifest
from src.data_models.scoring import C1ScoringDiagnosticReport
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Validate independent returned judge versions and write a frozen scoring manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--judge-snapshot", type=Path, action="append", required=True)
    parser.add_argument("--c1-diagnostic-report", type=Path, required=True)
    parser.add_argument("--fact-order-seed", type=int, default=7)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--backoff-seconds", type=float, action="append", default=[])
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluated = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    diagnostic = read_model_json(
        args.c1_diagnostic_report,
        C1ScoringDiagnosticReport,
    )
    validate_model_self_hash(evaluated, "manifest_sha256")
    validate_model_self_hash(diagnostic, "report_sha256")
    if evaluated.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("scoring freeze requires frozen evaluated-model snapshots")
    if diagnostic.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("C1 diagnostic does not validate the active scoring contract")
    snapshots = [read_model_json(path, EvaluatedModelSnapshot) for path in args.judge_snapshot]
    judge_ids = [snapshot.model_id for snapshot in snapshots]
    if set(judge_ids) != set(evaluated.scoring_judge_model_ids):
        raise ValueError("judge snapshots must exactly cover the judge aliases approved with the evaluated-model freeze")
    if not set(judge_ids).isdisjoint({snapshot.model_id for snapshot in evaluated.evaluated_models}):
        raise ValueError("the frozen scoring judge must be independent of every evaluated model")
    retry_policy = RetryPolicy(
        max_retries=args.max_retries,
        backoff_seconds=args.backoff_seconds,
        reuse_identical_prompt_bytes=True,
    )
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "judge_model_ids": judge_ids,
        "judge_snapshots": snapshots,
        "scoring_contract_sha256": scoring_contract_sha256(),
        "fact_order_seed": args.fact_order_seed,
        "retry_policy": retry_policy,
        "frozen_at": datetime.now(timezone.utc),
        "frozen_by": args.frozen_by,
    }
    manifest = ScoringExecutionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote frozen scoring execution manifest to {args.output}")


if __name__ == "__main__":
    main()
