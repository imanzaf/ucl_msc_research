"""Save freely edited scenario candidates as simple parent-linked versions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.data_models.common import artifact_sha256, utc_now, validate_sha256
from src.data_models.scenario_review import ScenarioRevisionRecord
from src.data_models.scenarios import AcceptedScenario, ArtifactProvenance, CandidateScenario, ScenarioGenerationInvocationConfig, ScenarioStage
from src.paths import scenario_generation_round_id
from src.storage import append_model_jsonl_atomic, read_model_jsonl, write_model_json_atomic

EDITABLE_CANDIDATE_FIELDS = (
    "deployment_context",
    "customer_messages",
    "hidden_design",
    "options",
)


def _list_item_key(value: Any, index: int) -> str:
    """Return a stable path component for a structured list item."""
    if isinstance(value, dict):
        for field_name in ("option_id", "fact_id", "scenario_id"):
            identifier = value.get(field_name)
            if isinstance(identifier, str) and identifier:
                return identifier
    return str(index)


def _changed_field_paths(previous: Any, revised: Any, prefix: str = "") -> List[str]:
    """Return leaf paths whose canonical values differ between two payloads."""
    if previous == revised:
        return []
    if isinstance(previous, dict) and isinstance(revised, dict):
        paths: List[str] = []
        for field_name in sorted(set(previous) | set(revised)):
            field_path = f"{prefix}.{field_name}" if prefix else field_name
            paths.extend(_changed_field_paths(previous.get(field_name), revised.get(field_name), field_path))
        return paths
    if isinstance(previous, list) and isinstance(revised, list) and len(previous) == len(revised):
        paths = []
        for index, (previous_item, revised_item) in enumerate(zip(previous, revised)):
            item_path = f"{prefix}.{_list_item_key(revised_item, index)}"
            paths.extend(_changed_field_paths(previous_item, revised_item, item_path))
        return paths
    return [prefix or "candidate"]


def editable_candidate_content(candidate: CandidateScenario | AcceptedScenario) -> Dict[str, Any]:
    """Return the four candidate sections that a researcher may freely edit."""
    payload = candidate.model_dump(mode="python")
    return {field_name: payload[field_name] for field_name in EDITABLE_CANDIDATE_FIELDS}


def build_revised_candidate(
    parent: CandidateScenario | AcceptedScenario,
    edited_content: Dict[str, Any],
    edited_by: str,
    saved_at: datetime,
) -> Tuple[CandidateScenario, List[str]]:
    """Build one validated candidate version from arbitrary researcher edits."""
    unknown_fields = set(edited_content) - set(EDITABLE_CANDIDATE_FIELDS)
    if unknown_fields:
        raise ValueError(f"unknown editable candidate fields: {', '.join(sorted(unknown_fields))}")
    if saved_at.tzinfo is None:
        raise ValueError("revision saved_at must be timezone-aware")
    revised_by = edited_by.strip()
    if not revised_by:
        raise ValueError("edited_by is required")
    parent_hash = parent.candidate_sha256 if isinstance(parent, CandidateScenario) else parent.artifact_sha256
    base_payload = {
        "schema_version": parent.schema_version,
        "scenario_id": parent.scenario_id,
        "use_case_id": parent.use_case_id,
        "study_stage": parent.study_stage,
        **editable_candidate_content(parent),
    }
    base_payload.update(edited_content)
    candidate_payload = {
        **base_payload,
        "provenance": ArtifactProvenance(
            created_at=saved_at,
            created_by=f"manual:{revised_by}",
            parent_sha256=parent_hash,
        ),
    }
    candidate = CandidateScenario.model_validate({**candidate_payload, "candidate_sha256": artifact_sha256(candidate_payload)})
    changed_fields = _changed_field_paths(editable_candidate_content(parent), editable_candidate_content(candidate))
    if not changed_fields:
        raise ValueError("the edited scenario is identical to its current version")
    return candidate, changed_fields


def _round_timestamp(round_id: str) -> datetime:
    """Parse a round identifier into its exact timezone-aware timestamp."""
    return datetime.strptime(round_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)


def _revision_history_path(run_root: Path, scenario_id: str) -> Path:
    """Return the append-only revision-history path for one scenario."""
    return run_root / "revision_history" / f"{scenario_id}.jsonl"


def _save_revision_artifacts(
    run_root: Path,
    candidate: CandidateScenario,
    parent_hash: str,
    changed_fields: List[str],
    edited_by: str,
    notes: str,
    saved_at: datetime,
) -> Tuple[CandidateScenario, ScenarioRevisionRecord, Path]:
    """Write one already-built candidate version and its append-only history record."""
    if not (run_root / "run_config.json").is_file():
        raise FileNotFoundError(f"scenario run is missing run_config.json: {run_root}")
    history_path = _revision_history_path(run_root, candidate.scenario_id)
    history = read_model_jsonl(history_path, ScenarioRevisionRecord)
    record_payload = {
        "schema_version": "1.0.0",
        "scenario_id": candidate.scenario_id,
        "revision_number": len(history) + 1,
        "parent_candidate_sha256": parent_hash,
        "candidate_sha256": candidate.candidate_sha256,
        "changed_fields": changed_fields,
        "edited_by": edited_by.strip(),
        "notes": notes.strip(),
        "saved_at": saved_at,
    }
    record = ScenarioRevisionRecord.model_validate({**record_payload, "record_sha256": artifact_sha256(record_payload)})
    round_id = scenario_generation_round_id(saved_at)
    round_root = run_root / round_id
    round_root.mkdir(parents=True, exist_ok=False)
    invocation = ScenarioGenerationInvocationConfig(
        schema_version="1.0.0",
        run_id=run_root.name,
        invocation_id=round_id,
        stage=ScenarioStage(candidate.study_stage),
        scenario_ids=[candidate.scenario_id],
        backend="manual:scenario_editor",
        created_at=_round_timestamp(round_id),
    )
    scenario_root = round_root / "scenarios" / candidate.scenario_id
    write_model_json_atomic(round_root / "invocation_config.json", invocation)
    write_model_json_atomic(scenario_root / "candidate.json", candidate)
    write_model_json_atomic(scenario_root / "revision_record.json", record)
    append_model_jsonl_atomic(history_path, record)
    return candidate, record, round_root


def save_candidate_revision(
    run_root: Path,
    parent: CandidateScenario | AcceptedScenario,
    edited_content: Dict[str, Any],
    edited_by: str,
    notes: str = "",
    saved_at: datetime | None = None,
) -> Tuple[CandidateScenario, ScenarioRevisionRecord, Path]:
    """Persist an edited candidate in a new round and append its revision record."""
    timestamp = saved_at or utc_now()
    candidate, changed_fields = build_revised_candidate(parent, edited_content, edited_by, timestamp)
    parent_hash = parent.candidate_sha256 if isinstance(parent, CandidateScenario) else parent.artifact_sha256
    return _save_revision_artifacts(
        run_root=run_root,
        candidate=candidate,
        parent_hash=parent_hash,
        changed_fields=changed_fields,
        edited_by=edited_by,
        notes=notes,
        saved_at=timestamp,
    )


def save_in_place_candidate_revision(
    run_root: Path,
    candidate_path: Path,
    edited_by: str,
    notes: str = "",
    saved_at: datetime | None = None,
) -> Tuple[CandidateScenario, ScenarioRevisionRecord, Path]:
    """Normalise a directly edited candidate JSON file and save it as a new version."""
    if not candidate_path.resolve().is_relative_to(run_root.resolve()):
        raise ValueError("an in-place candidate edit must be inside the selected scenario run")
    raw_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(raw_payload, dict):
        raise ValueError("edited candidate JSON must contain one object")
    parent_hash = validate_sha256(str(raw_payload.get("candidate_sha256", "")))
    timestamp = saved_at or utc_now()
    revised_by = edited_by.strip()
    if not revised_by:
        raise ValueError("edited_by is required")
    candidate_payload = {
        field_name: raw_payload[field_name]
        for field_name in ("schema_version", "scenario_id", "use_case_id", "study_stage", *EDITABLE_CANDIDATE_FIELDS)
    }
    candidate_payload["provenance"] = ArtifactProvenance(
        created_at=timestamp,
        created_by=f"manual:{revised_by}",
        parent_sha256=parent_hash,
    )
    candidate = CandidateScenario.model_validate({**candidate_payload, "candidate_sha256": artifact_sha256(candidate_payload)})
    write_model_json_atomic(candidate_path, candidate)
    return _save_revision_artifacts(
        run_root=run_root,
        candidate=candidate,
        parent_hash=parent_hash,
        changed_fields=["manual_json_edit"],
        edited_by=revised_by,
        notes=notes,
        saved_at=timestamp,
    )
