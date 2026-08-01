"""Save a freely edited scenario candidate as a new parent-linked version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from src.paths import scenario_generation_run_root
from src.scenarios.revisions import EDITABLE_CANDIDATE_FIELDS, save_candidate_revision, save_in_place_candidate_revision
from src.scenarios.run_resolution import current_scenario_artifacts


def _read_editable_content(path: Path) -> tuple[str, Dict[str, Any]]:
    """Read either a full candidate JSON object or only its editable sections."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("edited scenario file must contain one JSON object")
    scenario_id = payload.get("scenario_id")
    if not isinstance(scenario_id, str):
        raise ValueError("edited scenario file must include scenario_id")
    editable_content = {field_name: payload[field_name] for field_name in EDITABLE_CANDIDATE_FIELDS if field_name in payload}
    if not editable_content:
        raise ValueError("edited scenario file does not contain any editable candidate fields")
    return scenario_id, editable_content


def main() -> None:
    """Save a JSON edit without automated review, regeneration, or acceptance gates."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--file", type=Path, required=True, help="Edited full candidate JSON or editable-field JSON")
    parser.add_argument("--edited-by", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    run_root = scenario_generation_run_root(args.run_id)
    if not run_root.is_dir():
        raise FileNotFoundError(f"unknown scenario generation run: {args.run_id}")
    if args.file.resolve().is_relative_to(run_root.resolve()):
        candidate, record, round_root = save_in_place_candidate_revision(
            run_root=run_root,
            candidate_path=args.file,
            edited_by=args.edited_by,
            notes=args.notes,
        )
    else:
        scenario_id, edited_content = _read_editable_content(args.file)
        current = current_scenario_artifacts(run_root)
        if scenario_id not in current:
            raise ValueError(f"scenario run has no current candidate for {scenario_id}")
        candidate, record, round_root = save_candidate_revision(
            run_root=run_root,
            parent=current[scenario_id].candidate,
            edited_content=edited_content,
            edited_by=args.edited_by,
            notes=args.notes,
        )
    print(
        f"Saved {candidate.scenario_id} revision {record.revision_number} "
        f"({record.parent_candidate_sha256[:12]} -> {candidate.candidate_sha256[:12]})"
    )
    print(f"Round root: {round_root}")


if __name__ == "__main__":
    main()
