"""Freeze researcher-selected domain validation thresholds from calibration."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.scoring import CompositeDomain, DomainValidationGate, DomainValidationGateManifest
from src.storage import write_model_json_atomic


def main() -> None:
    """Bind all five domain gates and rationales to exact calibration bytes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates-json", type=Path, required=True)
    parser.add_argument("--calibration-source", type=Path, required=True)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.gates_json.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"gates", "rationale"}:
        raise ValueError("gate input requires exactly gates and rationale mappings")
    if set(raw["gates"]) != {domain.value for domain in CompositeDomain}:
        raise ValueError("gate input requires all five composite domains")
    gates = {CompositeDomain(name): DomainValidationGate.model_validate(value) for name, value in raw["gates"].items()}
    rationale = {CompositeDomain(name): str(value) for name, value in raw["rationale"].items()}
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": "frozen",
        "gates": gates,
        "rationale": rationale,
        "calibration_source_sha256": file_sha256(args.calibration_source),
        "frozen_by": args.frozen_by,
        "frozen_at": datetime.now(timezone.utc),
    }
    manifest = DomainValidationGateManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Froze validation gates for all five domains to {args.output}")


if __name__ == "__main__":
    main()
