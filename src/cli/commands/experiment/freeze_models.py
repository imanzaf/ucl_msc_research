"""Freeze three exact evaluated snapshots and approved independent judge aliases."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256
from src.data_models.manifests import EvaluatedModelManifest, EvaluatedModelSnapshot, FreezeStatus
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Validate supplied provider-returned snapshots and write the model freeze."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluated-snapshot", type=Path, action="append", required=True)
    parser.add_argument("--scoring-judge-model-id", action="append", required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshots = [read_model_json(path, EvaluatedModelSnapshot) for path in args.evaluated_snapshot]
    payload = {
        "schema_version": "1.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "evaluated_models": snapshots,
        "scoring_judge_model_ids": args.scoring_judge_model_id,
        "frozen_at": datetime.now(timezone.utc),
        "frozen_by": args.frozen_by,
    }
    manifest = EvaluatedModelManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote frozen evaluated-model manifest to {args.output}")


if __name__ == "__main__":
    main()
