"""Build the self-hashed 30-scenario V0.11.0 accepted-set manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.manifests import AcceptedScenarioEntry, AcceptedScenarioManifest, ScenarioManifestScope
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_INPUT_ROOT, ACTIVE_SCENARIO_SET_ID
from src.scenarios.acceptance import validate_accepted_bundle
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, write_model_json_atomic


def accepted_manifest_output_path(scope: ScenarioManifestScope) -> Path:
    """Return the fixed active output path for one accepted-set scope."""
    output_name = "calibration_accepted_scenario_manifest.json" if scope == ScenarioManifestScope.CALIBRATION else "accepted_scenario_manifest.json"
    return ACTIVE_SCENARIO_INPUT_ROOT / output_name


def build_accepted_scenario_manifest(
    accepted_root: Path,
    scope: ScenarioManifestScope,
    published_by: str,
    published_at: Optional[datetime] = None,
) -> AcceptedScenarioManifest:
    """Authenticate accepted bundles and build their immutable set manifest."""
    seed_root = ACTIVE_SCENARIO_INPUT_ROOT
    load_and_validate_seed(
        seed_path=seed_root / "scenario_generation_seeds.json",
        schema_path=seed_root / "scenario_generation_seed_schema.json",
    )
    entries = []
    for artifact_path in sorted(accepted_root.glob("CF???_*/accepted_scenario.json")):
        accepted = read_model_json(artifact_path, AcceptedScenario)
        if scope == ScenarioManifestScope.CALIBRATION and not accepted.scenario_id.endswith("_C1"):
            continue
        history = read_model_json(artifact_path.parent / "review_history.json", ScenarioReviewHistory)
        acceptance = read_model_json(artifact_path.parent / "acceptance_record.json", ScenarioAcceptanceRecord)
        validate_accepted_bundle(accepted, history, acceptance)
        entries.append(
            AcceptedScenarioEntry(
                scenario_id=accepted.scenario_id,
                study_stage=accepted.study_stage,
                artifact_path=str(artifact_path.relative_to(accepted_root)),
                artifact_sha256=accepted.artifact_sha256,
                review_history_sha256=artifact_sha256(history),
                acceptance_record_sha256=acceptance.record_sha256,
            )
        )
    payload = {
        "schema_version": "2.0.0",
        "scenario_set_id": ACTIVE_SCENARIO_SET_ID,
        "manifest_scope": scope,
        "seed_sha256": file_sha256(seed_root / "scenario_generation_seeds.json"),
        "seed_schema_sha256": file_sha256(seed_root / "scenario_generation_seed_schema.json"),
        "entries": entries,
        "published_at": published_at or datetime.now(timezone.utc),
        "published_by": published_by,
    }
    return AcceptedScenarioManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})


def main() -> None:
    """Authenticate every published bundle and write the immutable accepted-set manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--scope", choices=[scope.value for scope in ScenarioManifestScope], required=True)
    parser.add_argument("--published-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scope = ScenarioManifestScope(args.scope)
    if args.accepted_root.resolve() != ACTIVE_SCENARIO_ACCEPTED_ROOT.resolve():
        raise ValueError("accepted-set manifests must read only the active V0.11.0 accepted root")
    expected_output = accepted_manifest_output_path(scope)
    if args.output.resolve() != expected_output.resolve():
        raise ValueError(f"{scope.value} accepted-set manifest must use {expected_output}")
    if args.output.exists():
        raise FileExistsError(f"accepted-set manifests are immutable and already exist: {args.output}")
    manifest = build_accepted_scenario_manifest(args.accepted_root, scope, args.published_by)
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote {scope.value} accepted-set manifest for {len(manifest.entries)} scenarios to {args.output}")


if __name__ == "__main__":
    main()
