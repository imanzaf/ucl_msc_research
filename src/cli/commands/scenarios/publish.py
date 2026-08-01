"""Publish any researcher-selected current scenario versions without review gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from src.cli.commands.scenarios.build_manifest import accepted_manifest_output_path, build_accepted_scenario_manifest
from src.data_models.manifests import ScenarioManifestScope
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario, CandidateScenario
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, scenario_generation_run_root
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario
from src.scenarios.run_resolution import current_scenario_artifacts
from src.storage import read_model_json, write_model_json_atomic


def _next_artifact_version(scenario_id: str) -> str:
    """Return the next simple publication version for one scenario."""
    current_path = ACTIVE_SCENARIO_ACCEPTED_ROOT / scenario_id / "accepted_scenario.json"
    if not current_path.is_file():
        return "v1"
    current = read_model_json(current_path, AcceptedScenario)
    return f"v{int(current.artifact_version.removeprefix('v')) + 1}"


def _already_published(candidate: CandidateScenario) -> bool:
    """Return whether the current publication already points to this candidate hash."""
    record_path = ACTIVE_SCENARIO_ACCEPTED_ROOT / candidate.scenario_id / "acceptance_record.json"
    if not record_path.is_file():
        return False
    return read_model_json(record_path, ScenarioAcceptanceRecord).candidate_sha256 == candidate.candidate_sha256


def _published_scenario_ids() -> set[str]:
    """Return scenario identifiers that currently have complete published bundles."""
    return {
        path.parent.name
        for path in ACTIVE_SCENARIO_ACCEPTED_ROOT.glob("CF???_*/accepted_scenario.json")
        if (path.parent / "review_history.json").is_file() and (path.parent / "acceptance_record.json").is_file()
    }


def refresh_available_manifests(published_by: str, published_at: datetime) -> List[Path]:
    """Refresh calibration or complete manifests only when their exact sets exist."""
    published_ids = _published_scenario_ids()
    calibration_ids = {f"CF{index:03d}_C1" for index in range(1, 11)}
    evaluation_ids = {f"CF{index:03d}_R{replication}" for index in range(1, 11) for replication in range(1, 3)}
    written: List[Path] = []
    for scope, required_ids in (
        (ScenarioManifestScope.CALIBRATION, calibration_ids),
        (ScenarioManifestScope.COMPLETE, calibration_ids | evaluation_ids),
    ):
        if not required_ids.issubset(published_ids):
            continue
        manifest = build_accepted_scenario_manifest(
            accepted_root=ACTIVE_SCENARIO_ACCEPTED_ROOT,
            scope=scope,
            published_by=published_by,
            published_at=published_at,
        )
        output_path = accepted_manifest_output_path(scope)
        write_model_json_atomic(output_path, manifest)
        written.append(output_path)
    return written


def publish_selected_candidates(
    run_root: Path,
    scenario_ids: List[str],
    published_by: str,
    published_at: datetime | None = None,
) -> Tuple[List[AcceptedScenario], List[Path]]:
    """Publish only the named current candidates and refresh any now-complete manifests."""
    if not (run_root / "run_config.json").is_file():
        raise FileNotFoundError(f"scenario run is missing run_config.json: {run_root}")
    selected_ids = list(dict.fromkeys(scenario_ids))
    if not selected_ids:
        raise ValueError("select at least one scenario to publish")
    researcher = published_by.strip()
    if not researcher:
        raise ValueError("published_by is required")
    current = current_scenario_artifacts(run_root)
    missing = sorted(set(selected_ids) - set(current))
    if missing:
        raise ValueError(f"scenario run has no current candidate for: {', '.join(missing)}")
    timestamp = published_at or datetime.now(timezone.utc)
    published: List[AcceptedScenario] = []
    for scenario_id in selected_ids:
        candidate = current[scenario_id].candidate
        if _already_published(candidate):
            continue
        history = ScenarioReviewHistory(schema_version="3.4.0", scenario_id=scenario_id)
        acceptance_record, accepted = build_accepted_scenario(
            candidate=candidate,
            review_history=history,
            accepted_at=timestamp,
            accepted_by=researcher,
            artifact_version=_next_artifact_version(scenario_id),
        )
        publish_accepted_scenario(
            accepted=accepted,
            review_history=history,
            acceptance_record=acceptance_record,
            accepted_root=ACTIVE_SCENARIO_ACCEPTED_ROOT,
            replace_existing=True,
        )
        published.append(accepted)
    manifest_paths = refresh_available_manifests(researcher, timestamp) if published else []
    return published, manifest_paths


def main() -> None:
    """Publish selected current candidate versions in one command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scenario-id", action="append", dest="scenario_ids")
    selection.add_argument("--all-current", action="store_true")
    parser.add_argument("--published-by", required=True)
    args = parser.parse_args()

    run_root = scenario_generation_run_root(args.run_id)
    if not run_root.is_dir():
        raise FileNotFoundError(f"unknown scenario generation run: {args.run_id}")
    scenario_ids = sorted(current_scenario_artifacts(run_root)) if args.all_current else args.scenario_ids
    published, manifest_paths = publish_selected_candidates(run_root, scenario_ids, args.published_by)
    if published:
        print(f"Published {len(published)} selected scenario version(s): {', '.join(item.scenario_id for item in published)}")
    else:
        print("Every selected scenario already points to the current published version.")
    for path in manifest_paths:
        print(f"Refreshed manifest: {path}")


if __name__ == "__main__":
    main()
