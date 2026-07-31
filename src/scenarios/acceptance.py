"""Build and atomically publish researcher-accepted versioned scenario bundles."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.scenario_review import (
    ResearcherScenarioReview,
    ReviewDecision,
    ScenarioAcceptanceRecord,
    ScenarioReviewHistory,
    required_automated_review_kinds,
)
from src.data_models.scenarios import AcceptedScenario, CandidateScenario
from src.scenarios.researcher_edits import apply_researcher_fact_reviews
from src.storage import write_model_json_atomic


def validate_candidate_scenario_hash(candidate: CandidateScenario) -> None:
    """Require the candidate digest to match every canonical content field."""
    validate_model_self_hash(candidate, "candidate_sha256")


def validate_accepted_scenario_hash(accepted: AcceptedScenario) -> None:
    """Require the accepted artifact digest to match every canonical content field."""
    validate_model_self_hash(accepted, "artifact_sha256")


def _validated_researcher_review(
    reviews: List[ResearcherScenarioReview],
    candidate: CandidateScenario,
) -> ResearcherScenarioReview:
    """Require exactly one researcher review bound to the candidate proposed for acceptance."""
    if len(reviews) != 1:
        raise ValueError("acceptance requires exactly one researcher scenario review")
    review = reviews[0]
    if review.scenario_id != candidate.scenario_id or review.reviewed_artifact_sha256 != candidate.candidate_sha256:
        raise ValueError("researcher review does not bind the accepted candidate")
    return review


def build_accepted_scenario(
    candidate: CandidateScenario,
    review_history: ScenarioReviewHistory,
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
    required_review_kinds = required_automated_review_kinds(candidate.scenario_id)
    final_automated = {
        review.review_kind: review for review in review_history.automated_reviews if review.reviewed_artifact_sha256 == candidate.candidate_sha256
    }
    if set(final_automated) != required_review_kinds:
        raise ValueError("acceptance requires every stage-relevant automated review of the final candidate")
    if any(review.decision != ReviewDecision.ACCEPT for review in final_automated.values()):
        raise ValueError("acceptance requires every final automated review to pass")
    researcher_review = _validated_researcher_review(review_history.researcher_reviews, candidate)
    if researcher_review.decision != ReviewDecision.ACCEPT:
        raise ValueError("acceptance requires an accepted researcher decision")
    accepted_options = apply_researcher_fact_reviews(candidate, researcher_review.fact_reviews)
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
        "options": accepted_options,
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
