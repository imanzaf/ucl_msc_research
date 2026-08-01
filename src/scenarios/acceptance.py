"""Build and atomically publish researcher-accepted versioned scenario bundles."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Tuple

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario, CandidateScenario
from src.storage import read_model_json, write_model_json_atomic


def validate_candidate_scenario_hash(candidate: CandidateScenario) -> None:
    """Require the candidate digest to match every canonical content field."""
    validate_model_self_hash(candidate, "candidate_sha256")


def validate_accepted_scenario_hash(accepted: AcceptedScenario) -> None:
    """Require the accepted artifact digest to match every canonical content field."""
    validate_model_self_hash(accepted, "artifact_sha256")


def build_accepted_scenario(
    candidate: CandidateScenario,
    review_history: ScenarioReviewHistory,
    accepted_at: datetime,
    accepted_by: str,
    artifact_version: str = "v1",
) -> Tuple[ScenarioAcceptanceRecord, AcceptedScenario]:
    """Build a published artifact directly from the researcher-selected candidate version."""
    validate_candidate_scenario_hash(candidate)
    if review_history.scenario_id != candidate.scenario_id:
        raise ValueError("review history does not match candidate scenario")
    review_history_sha256 = artifact_sha256(review_history)
    record_payload = {
        "schema_version": "3.0.0",
        "scenario_id": candidate.scenario_id,
        "artifact_version": artifact_version,
        "candidate_sha256": candidate.candidate_sha256,
        "review_history_sha256": review_history_sha256,
        "accepted_at": accepted_at,
        "accepted_by": accepted_by,
    }
    acceptance_record = ScenarioAcceptanceRecord.model_validate({**record_payload, "record_sha256": artifact_sha256(record_payload)})
    accepted_payload = {
        "schema_version": candidate.schema_version,
        "artifact_version": artifact_version,
        "scenario_id": candidate.scenario_id,
        "use_case_id": candidate.use_case_id,
        "study_stage": candidate.study_stage,
        "deployment_context": candidate.deployment_context,
        "customer_messages": candidate.customer_messages,
        "hidden_design": candidate.hidden_design,
        "options": candidate.options,
        "review_history_sha256": review_history_sha256,
        "acceptance_record_sha256": acceptance_record.record_sha256,
        "accepted_at": accepted_at,
        "accepted_by": accepted_by,
    }
    accepted = AcceptedScenario.model_validate({**accepted_payload, "artifact_sha256": artifact_sha256(accepted_payload)})
    return acceptance_record, accepted


def validate_accepted_bundle(
    accepted: AcceptedScenario,
    review_history: ScenarioReviewHistory,
    acceptance_record: ScenarioAcceptanceRecord,
) -> None:
    """Verify every digest and identifier in one accepted publication bundle."""
    validate_accepted_scenario_hash(accepted)
    validate_model_self_hash(acceptance_record, "record_sha256")
    if {accepted.scenario_id, review_history.scenario_id, acceptance_record.scenario_id} != {accepted.scenario_id}:
        raise ValueError("accepted bundle scenario ids do not match")
    if accepted.review_history_sha256 != artifact_sha256(review_history):
        raise ValueError("accepted artifact does not bind the supplied review history")
    if acceptance_record.review_history_sha256 != accepted.review_history_sha256:
        raise ValueError("acceptance record does not bind the supplied review history")
    if accepted.acceptance_record_sha256 != acceptance_record.record_sha256:
        raise ValueError("accepted artifact does not bind the supplied acceptance record")
    if accepted.accepted_at != acceptance_record.accepted_at or accepted.accepted_by != acceptance_record.accepted_by:
        raise ValueError("accepted artifact provenance differs from the acceptance record")


def publish_accepted_scenario(
    accepted: AcceptedScenario,
    review_history: ScenarioReviewHistory,
    acceptance_record: ScenarioAcceptanceRecord,
    accepted_root: Path,
    replace_existing: bool = False,
) -> None:
    """Publish a complete bundle, optionally archiving and replacing the current version."""
    validate_accepted_bundle(accepted, review_history, acceptance_record)
    accepted_root.mkdir(parents=True, exist_ok=True)
    scenario_dir = accepted_root / accepted.scenario_id
    if scenario_dir.exists() and not replace_existing:
        raise FileExistsError(f"accepted scenario is immutable and already exists: {accepted.scenario_id}")
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{accepted.scenario_id}.", dir=accepted_root))
    archived_dir = None
    try:
        write_model_json_atomic(temporary_dir / "review_history.json", review_history)
        write_model_json_atomic(temporary_dir / "acceptance_record.json", acceptance_record)
        write_model_json_atomic(temporary_dir / "accepted_scenario.json", accepted)
        directory_descriptor = os.open(temporary_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        if scenario_dir.exists():
            previous = read_model_json(scenario_dir / "accepted_scenario.json", AcceptedScenario)
            archived_dir = accepted_root / "_history" / accepted.scenario_id / previous.artifact_sha256
            archived_dir.parent.mkdir(parents=True, exist_ok=True)
            if archived_dir.exists():
                raise FileExistsError(f"published history already contains {previous.artifact_sha256}")
            os.replace(scenario_dir, archived_dir)
        try:
            os.replace(temporary_dir, scenario_dir)
        except Exception:
            if archived_dir is not None and archived_dir.exists():
                os.replace(archived_dir, scenario_dir)
            raise
        root_descriptor = os.open(accepted_root, os.O_RDONLY)
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
