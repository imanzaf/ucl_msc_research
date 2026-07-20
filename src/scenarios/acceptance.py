"""Build and atomically publish researcher-accepted V0.5.1 scenario bundles."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from src.data_models.annotations import repeat_washout_elapsed
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    ResearcherScenarioReview,
    ReviewDecision,
    ReviewPass,
    ScenarioAcceptanceRecord,
    ScenarioReviewHistory,
)
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, MinimalCompleteResponse
from src.storage import write_model_json_atomic


def validate_candidate_scenario_hash(candidate: CandidateScenario) -> None:
    """Require the candidate digest to match every canonical content field."""
    validate_model_self_hash(candidate, "candidate_sha256")


def validate_accepted_scenario_hash(accepted: AcceptedScenario) -> None:
    """Require the accepted artifact digest to match every canonical content field."""
    validate_model_self_hash(accepted, "artifact_sha256")


def _validated_final_researcher_review(
    reviews: List[ResearcherScenarioReview],
    candidate: CandidateScenario,
) -> ResearcherScenarioReview:
    """Validate the initial-repeat-resolution sequence and return its final decision."""
    initial = [review for review in reviews if review.review_pass == ReviewPass.INITIAL]
    repeated = [review for review in reviews if review.review_pass == ReviewPass.REPEAT]
    resolutions = [review for review in reviews if review.review_pass == ReviewPass.RESOLUTION]
    if len(initial) != 1 or len(repeated) != 1 or len(resolutions) > 1:
        raise ValueError("acceptance requires exactly one initial and one delayed-repeat review, plus at most one resolution")
    first = initial[0]
    second = repeated[0]
    if second.initial_review_id != first.review_id:
        raise ValueError("repeat review does not link to the initial review")
    if not repeat_washout_elapsed(first.reviewed_at, second.reviewed_at):
        raise ValueError("repeat scenario review did not satisfy the 14-day washout")
    if first.researcher_id != second.researcher_id:
        raise ValueError("initial and repeat reviews must use the same researcher")
    disagreement = first.decision != second.decision or first.labels != second.labels
    if disagreement and len(resolutions) != 1:
        raise ValueError("disagreeing scenario reviews require one resolution record")
    if not disagreement and resolutions:
        raise ValueError("resolution is permitted only when initial and repeat reviews disagree")
    final_review = second
    if resolutions:
        resolution = resolutions[0]
        if resolution.initial_review_id != first.review_id or resolution.repeat_review_id != second.review_id:
            raise ValueError("resolution does not bind the reviewed initial/repeat pair")
        if resolution.reviewed_at < second.reviewed_at:
            raise ValueError("scenario resolution cannot predate the repeat review")
        final_review = resolution
    for review in reviews:
        if review.scenario_id != candidate.scenario_id or review.reviewed_artifact_sha256 != candidate.candidate_sha256:
            raise ValueError("researcher review does not bind the accepted candidate")
    return final_review


def build_accepted_scenario(
    candidate: CandidateScenario,
    review_history: ScenarioReviewHistory,
    approved_minimal_response: MinimalCompleteResponse,
    accepted_at: datetime,
    accepted_by: str,
    artifact_version: str = "v1",
) -> Tuple[ScenarioAcceptanceRecord, AcceptedScenario]:
    """Build an acyclic acceptance record and immutable artifact after every review gate passes."""
    validate_candidate_scenario_hash(candidate)
    if review_history.scenario_id != candidate.scenario_id:
        raise ValueError("review history does not match candidate scenario")
    if review_history.revisions:
        if review_history.revisions[-1].output_artifact_sha256 != candidate.candidate_sha256:
            raise ValueError("final revision output does not match the candidate proposed for acceptance")
    elif any(review.reviewed_artifact_sha256 != candidate.candidate_sha256 for review in review_history.automated_reviews):
        raise ValueError("unrevised review history contains a review of a different candidate")
    final_automated = review_history.automated_reviews[-3:]
    if set(review.review_kind for review in final_automated) != set(AutomatedReviewKind):
        raise ValueError("acceptance requires all three final automated review kinds")
    if any(review.decision != ReviewDecision.ACCEPT for review in final_automated):
        raise ValueError("acceptance requires every final automated review to pass")
    if any(review.reviewed_artifact_sha256 != candidate.candidate_sha256 for review in final_automated):
        raise ValueError("final automated reviews do not bind the accepted candidate")
    final_researcher_review = _validated_final_researcher_review(review_history.researcher_reviews, candidate)
    if final_researcher_review.decision != ReviewDecision.ACCEPT:
        raise ValueError("acceptance requires an accepted final researcher decision")
    if not approved_minimal_response.approved or approved_minimal_response.scenario_id != candidate.scenario_id:
        raise ValueError("acceptance requires a researcher-approved minimal response for the candidate")
    approval_fields = {"approved", "approved_at", "approved_by"}
    candidate_response = candidate.minimal_complete_response.model_dump(mode="json", exclude=approval_fields)
    approved_response = approved_minimal_response.model_dump(mode="json", exclude=approval_fields)
    if approved_response != candidate_response:
        raise ValueError("minimal response content changed after review; rebuild the candidate and rerun every review")
    review_history_sha256 = artifact_sha256(review_history)
    record_payload = {
        "schema_version": "1.0.0",
        "scenario_id": candidate.scenario_id,
        "artifact_version": artifact_version,
        "candidate_sha256": candidate.candidate_sha256,
        "review_history_sha256": review_history_sha256,
        "accepted_at": accepted_at,
        "accepted_by": accepted_by,
    }
    acceptance_record = ScenarioAcceptanceRecord.model_validate({**record_payload, "record_sha256": artifact_sha256(record_payload)})
    accepted_payload = {
        "schema_version": "1.0.0",
        "artifact_version": artifact_version,
        "scenario_id": candidate.scenario_id,
        "use_case_id": candidate.use_case_id,
        "study_stage": candidate.study_stage,
        "agent_role": candidate.agent_role,
        "model_owner": candidate.model_owner,
        "agent_task": candidate.agent_task,
        "task_context": candidate.task_context,
        "source_order_a": candidate.source_order_a,
        "source_order_b": candidate.source_order_b,
        "numeric_registry": candidate.numeric_registry,
        "material_facts": candidate.material_facts,
        "neutral_facts": candidate.neutral_facts,
        "fact_pairs": candidate.fact_pairs,
        "minimal_complete_response": approved_minimal_response,
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
) -> None:
    """Publish a complete accepted bundle with one atomic directory rename."""
    validate_accepted_bundle(accepted, review_history, acceptance_record)
    accepted_root.mkdir(parents=True, exist_ok=True)
    scenario_dir = accepted_root / accepted.scenario_id
    if scenario_dir.exists():
        raise FileExistsError(f"accepted scenario is immutable and already exists: {accepted.scenario_id}")
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{accepted.scenario_id}.", dir=accepted_root))
    try:
        write_model_json_atomic(temporary_dir / "review_history.json", review_history)
        write_model_json_atomic(temporary_dir / "acceptance_record.json", acceptance_record)
        write_model_json_atomic(temporary_dir / "accepted_scenario.json", accepted)
        directory_descriptor = os.open(temporary_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        os.replace(temporary_dir, scenario_dir)
        root_descriptor = os.open(accepted_root, os.O_RDONLY)
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
