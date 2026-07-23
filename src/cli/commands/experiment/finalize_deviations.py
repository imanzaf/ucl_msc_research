"""Finalise an empty or populated post-preregistration protocol-deviation register."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import ExperimentManifest, PreregistrationManifest, ProtocolDeviation, ProtocolDeviationManifest
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def main() -> None:
    """Bind all recorded deviations backward to the frozen experiment and preregistration."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--preregistration-manifest", type=Path, required=True)
    parser.add_argument("--deviations", type=Path, required=True)
    parser.add_argument("--finalised-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = read_model_json(args.experiment_manifest, ExperimentManifest)
    preregistration = read_model_json(args.preregistration_manifest, PreregistrationManifest)
    validate_model_self_hash(experiment, "manifest_sha256")
    validate_model_self_hash(preregistration, "manifest_sha256")
    if preregistration.experiment_manifest_sha256 != experiment.manifest_sha256:
        raise ValueError("preregistration does not bind the supplied experiment")
    payload = {
        "schema_version": "2.0.0",
        "preregistration_manifest_sha256": preregistration.manifest_sha256,
        "experiment_manifest_sha256": experiment.manifest_sha256,
        "deviations": read_model_jsonl(args.deviations, ProtocolDeviation),
        "finalised_at": datetime.now(timezone.utc),
        "finalised_by": args.finalised_by,
    }
    manifest = ProtocolDeviationManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Finalised {len(manifest.deviations)} protocol deviations at {args.output}")


if __name__ == "__main__":
    main()
