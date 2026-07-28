"""Freeze researcher-selected construct validation thresholds from calibration."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.scoring import ConstructValidationGate, ConstructValidationGateManifest, ScoringConstruct
from src.storage import write_model_json_atomic


def main() -> None:
    """Bind all six construct gates and rationales to exact calibration bytes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates-json", type=Path, required=True)
    parser.add_argument("--calibration-source", type=Path, required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.gates_json.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"gates", "rationale"}:
        raise ValueError("gate input requires exactly gates and rationale mappings")
    if set(raw["gates"]) != {construct.value for construct in ScoringConstruct}:
        raise ValueError("gate input requires all six scoring constructs")
    gates = {ScoringConstruct(name): ConstructValidationGate.model_validate(value) for name, value in raw["gates"].items()}
    rationale = {ScoringConstruct(name): str(value) for name, value in raw["rationale"].items()}
    payload = {
        "schema_version": "3.0.0",
        "freeze_status": "frozen",
        "gates": gates,
        "rationale": rationale,
        "calibration_source_sha256": file_sha256(args.calibration_source),
        "frozen_by": args.frozen_by,
        "frozen_at": datetime.now(timezone.utc),
    }
    manifest = ConstructValidationGateManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Froze validation gates for all six constructs to {args.output}")


if __name__ == "__main__":
    main()
