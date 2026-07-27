"""Freeze smallest effects and calibration-derived power variance assumptions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.manifests import AnalysisAssumptionInput, FreezeStatus, PowerAssumptionManifest, SmallestEffectManifest
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Validate researcher-authored assumptions and bind them to calibration bytes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--assumptions-json", type=Path, required=True)
    parser.add_argument("--calibration-source", type=Path, required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--smallest-output", type=Path, required=True)
    parser.add_argument("--power-output", type=Path, required=True)
    args = parser.parse_args()
    assumptions = read_model_json(args.assumptions_json, AnalysisAssumptionInput)
    frozen_at = datetime.now(timezone.utc)
    smallest_payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "absolute_bounds": assumptions.absolute_bounds,
        "rationale": assumptions.rationales,
        "frozen_at": frozen_at,
        "frozen_by": args.frozen_by,
    }
    smallest = SmallestEffectManifest.model_validate({**smallest_payload, "manifest_sha256": artifact_sha256(smallest_payload)})
    power_payload = {
        "schema_version": "3.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "smallest_effect_manifest_sha256": smallest.manifest_sha256,
        "variance_components": assumptions.variance_components,
        "calibration_source_sha256": file_sha256(args.calibration_source),
        "frozen_at": frozen_at,
        "frozen_by": args.frozen_by,
    }
    power = PowerAssumptionManifest.model_validate({**power_payload, "manifest_sha256": artifact_sha256(power_payload)})
    write_model_json_atomic(args.smallest_output, smallest)
    write_model_json_atomic(args.power_output, power)
    print(f"Wrote frozen smallest-effect and power-assumption manifests to {args.smallest_output} and {args.power_output}")


if __name__ == "__main__":
    main()
