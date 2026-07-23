"""Build the self-hashed 50-scenario V0.5.2 accepted-set manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.manifests import AcceptedScenarioEntry, AcceptedScenarioManifest, ScenarioManifestScope
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario
from src.paths import REPO_ROOT
from src.scenarios.acceptance import validate_accepted_bundle
from src.storage import read_model_json, write_model_json_atomic


def main() -> None:
    """Authenticate every published bundle and write the immutable accepted-set manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--scope", choices=[scope.value for scope in ScenarioManifestScope], required=True)
    parser.add_argument("--published-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scope = ScenarioManifestScope(args.scope)
    entries = []
    for artifact_path in sorted(args.accepted_root.glob("CF???_*/accepted_scenario.json")):
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
                artifact_path=str(artifact_path.relative_to(args.accepted_root)),
                artifact_sha256=accepted.artifact_sha256,
                review_history_sha256=artifact_sha256(history),
                acceptance_record_sha256=acceptance.record_sha256,
            )
        )
    seed_root = REPO_ROOT / "data" / "inputs" / "scenarios" / "v0.5.2"
    payload = {
        "schema_version": "2.0.0",
        "scenario_set_id": "customer_finance_pressure_concern_v0.5.2",
        "manifest_scope": scope,
        "seed_sha256": file_sha256(seed_root / "scenario_generation_seeds.json"),
        "seed_schema_sha256": file_sha256(seed_root / "scenario_generation_seed_schema.json"),
        "entries": entries,
        "published_at": datetime.now(timezone.utc),
        "published_by": args.published_by,
    }
    manifest = AcceptedScenarioManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, manifest)
    print(f"Wrote {scope.value} accepted-set manifest for {len(entries)} scenarios to {args.output}")


if __name__ == "__main__":
    main()
