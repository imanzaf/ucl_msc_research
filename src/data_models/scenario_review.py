"""Strict automated and researcher review records for V0.5.1 scenarios."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, validate_sha256
from src.data_models.experiments import ProviderCallProvenance

MAX_AUTOMATED_REVISION_CYCLES = 3
REPEAT_WASHOUT_DAYS = 14


class AutomatedReviewKind(str, Enum):
    """Identify the independent automated review contract."""

    CONSTRUCT = "construct"
    FINANCE_ARITHMETIC = "finance_arithmetic"
    BATCH_DIVERSITY = "batch_diversity"


class ReviewDecision(str, Enum):
    """Identify an automated or researcher scenario decision."""

    ACCEPT = "accept"
    REVISE = "revise"
    MANUAL_RESTRUCTURE = "manual_restructure"
    REJECT = "reject"


class ReviewPass(str, Enum):
    """Identify an initial, delayed-repeat, or resolution pass."""

    INITIAL = "initial"
    REPEAT = "repeat"
    RESOLUTION = "resolution"


class FindingSeverity(str, Enum):
    """Classify automated findings by protocol impact."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class ReviewFinding(ImmutableModel):
    """Represent one source-grounded automated review finding."""

    finding_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    severity: FindingSeverity
    artifact_path: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)


class AutomatedScenarioReview(VersionedImmutableModel):
    """Store one condition-independent typed automated review."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    review_kind: AutomatedReviewKind
    decision: ReviewDecision
    findings: List[ReviewFinding]
    reviewed_artifact_sha256: str
    reviewer_model_id: str = Field(min_length=1)
    reviewer_prompt_sha256: str
    provider_call: Optional[ProviderCallProvenance] = None
    reviewed_at: datetime

    @field_validator("reviewed_artifact_sha256", "reviewer_prompt_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate reviewed-artifact and prompt hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_decision_findings(self) -> "AutomatedScenarioReview":
        """Require acceptance to be finding-free and blockers to prevent acceptance."""
        if self.decision == ReviewDecision.ACCEPT and self.findings:
            raise ValueError("an accepted automated review cannot contain findings")
        if any(finding.severity == FindingSeverity.BLOCKER for finding in self.findings) and self.decision == ReviewDecision.ACCEPT:
            raise ValueError("blocker findings prevent acceptance")
        if self.reviewer_model_id.startswith("manual:") and self.provider_call is not None:
            raise ValueError("manual scenario review must not fabricate provider provenance")
        if self.provider_call is not None and self.provider_call.requested_model_id != self.reviewer_model_id:
            raise ValueError("scenario-review provider call used a different reviewer alias")
        return self


class ControlledFieldChange(ImmutableModel):
    """Record one field-level revision without permitting whole-object replacement."""

    field_path: str = Field(min_length=1)
    previous_value_sha256: str
    revised_value_sha256: str
    reason: str = Field(min_length=1)
    finding_ids: List[str] = Field(min_length=1)

    @field_validator("previous_value_sha256", "revised_value_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate field-value hashes."""
        return validate_sha256(value)

    @field_validator("field_path")
    @classmethod
    def reject_root_replacement(cls, value: str) -> str:
        """Reject a controlled revision that replaces the complete object."""
        if value in {"$", "", "/"}:
            raise ValueError("controlled revisions must target a field, not the complete object")
        return value


class RevisionCycleRecord(VersionedImmutableModel):
    """Store one bounded automated revision and full dependency rebuild."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    cycle_number: int = Field(ge=1, le=MAX_AUTOMATED_REVISION_CYCLES)
    changes: List[ControlledFieldChange] = Field(min_length=1)
    input_artifact_sha256: str
    output_artifact_sha256: str
    rebuilt_dependency_sha256: Dict[str, str]
    rerun_review_sha256: Dict[AutomatedReviewKind, str]
    completed_at: datetime

    @field_validator("input_artifact_sha256", "output_artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: str) -> str:
        """Validate revised artifact hashes."""
        return validate_sha256(value)

    @field_validator("rebuilt_dependency_sha256", "rerun_review_sha256")
    @classmethod
    def validate_hash_maps(cls, value: Dict[object, str]) -> Dict[object, str]:
        """Validate every dependency and review digest."""
        for digest in value.values():
            validate_sha256(digest)
        return value

    @model_validator(mode="after")
    def validate_all_reviews_rerun(self) -> "RevisionCycleRecord":
        """Require all three independent review contracts after every revision."""
        if set(self.rerun_review_sha256) != set(AutomatedReviewKind):
            raise ValueError("every revision cycle must rerun all automated review kinds")
        expected_dependencies = {
            "blueprint",
            "numeric_registry",
            "source_order_a",
            "source_order_b",
            "material_facts",
            "neutral_facts",
            "minimal_complete_response",
        }
        if set(self.rebuilt_dependency_sha256) != expected_dependencies:
            raise ValueError("every revision cycle must rebuild and hash all dependent scenario artifacts")
        return self


class ScenarioReviewLabels(ImmutableModel):
    """Capture the complete researcher scenario-review checklist."""

    factual_and_arithmetic_consistent: bool
    exact_source_support_valid: bool
    facts_atomic_and_valence_valid: bool
    all_material_facts_equally_required: bool
    pair_matching_acceptable: bool
    neutral_facts_lower_priority: bool
    source_orders_equivalent: bool
    minimal_response_feasible: bool
    customer_facing_naturalness: bool
    authority_limits_respected: bool
    treatment_leakage_absent: bool
    replication_distinct: bool

    def all_pass(self) -> bool:
        """Return whether every required scenario-review label passes."""
        return all(bool(value) for value in self.model_dump().values())


class ResearcherScenarioReview(VersionedImmutableModel):
    """Store a blinded initial, repeat, or resolution scenario review."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    review_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    anonymised_item_id: str = Field(min_length=1)
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    review_pass: ReviewPass
    decision: ReviewDecision
    labels: ScenarioReviewLabels
    reviewed_artifact_sha256: str
    reviewed_at: datetime
    researcher_id: str = Field(min_length=1)
    notes: str
    initial_review_id: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]+$")
    repeat_review_id: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]+$")
    resolution_reason: Optional[str] = Field(default=None, min_length=1)

    @field_validator("reviewed_artifact_sha256")
    @classmethod
    def validate_artifact_hash(cls, value: str) -> str:
        """Validate the reviewed artifact digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_review_pass(self) -> "ResearcherScenarioReview":
        """Enforce pass-specific linkage and acceptance checklist rules."""
        if self.review_pass == ReviewPass.INITIAL and (self.initial_review_id is not None or self.repeat_review_id is not None):
            raise ValueError("initial reviews cannot link to another review")
        if self.review_pass == ReviewPass.REPEAT and (self.initial_review_id is None or self.repeat_review_id is not None):
            raise ValueError("repeat reviews require only the linked initial review id")
        if self.review_pass == ReviewPass.RESOLUTION and (
            self.initial_review_id is None or self.repeat_review_id is None or self.resolution_reason is None
        ):
            raise ValueError("resolution reviews require linked initial/repeat ids and a reason")
        if self.review_pass != ReviewPass.RESOLUTION and self.resolution_reason is not None:
            raise ValueError("only resolution reviews may include a resolution reason")
        if self.decision == ReviewDecision.ACCEPT and not self.labels.all_pass():
            raise ValueError("accepted scenario reviews require every checklist item to pass")
        return self


class ScenarioReviewHistory(VersionedImmutableModel):
    """Collect complete automated, revision, and researcher review provenance."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    automated_reviews: List[AutomatedScenarioReview] = Field(min_length=3)
    revisions: List[RevisionCycleRecord] = Field(max_length=MAX_AUTOMATED_REVISION_CYCLES)
    researcher_reviews: List[ResearcherScenarioReview] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_review_history(self) -> "ScenarioReviewHistory":
        """Require complete review batches and a sequential, hash-linked revision history."""
        if len(self.automated_reviews) % len(AutomatedReviewKind) != 0:
            raise ValueError("automated review history must contain complete three-contract batches")
        for start in range(0, len(self.automated_reviews), len(AutomatedReviewKind)):
            batch = self.automated_reviews[start : start + len(AutomatedReviewKind)]
            if set(review.review_kind for review in batch) != set(AutomatedReviewKind):
                raise ValueError("each automated review batch must contain all three review kinds")
            if len({review.reviewed_artifact_sha256 for review in batch}) != 1:
                raise ValueError("one automated review batch cannot span multiple candidate hashes")
        if set(review.review_kind for review in self.automated_reviews[-3:]) != set(AutomatedReviewKind):
            raise ValueError("review history must end with all three automated review kinds")
        scenario_ids = {
            *{review.scenario_id for review in self.automated_reviews},
            *{revision.scenario_id for revision in self.revisions},
            *{review.scenario_id for review in self.researcher_reviews},
        }
        if scenario_ids != {self.scenario_id}:
            raise ValueError("every review record must share the history scenario_id")
        if [revision.cycle_number for revision in self.revisions] != list(range(1, len(self.revisions) + 1)):
            raise ValueError("revision cycles must be sequential and ordered from one")
        for index, revision in enumerate(self.revisions):
            if index and revision.input_artifact_sha256 != self.revisions[index - 1].output_artifact_sha256:
                raise ValueError("revision candidate hashes must form one continuous chain")
            matched_reviews = [review for review in self.automated_reviews if review.reviewed_artifact_sha256 == revision.output_artifact_sha256]
            if any(
                not any(review.review_kind == kind and artifact_sha256(review) == digest for review in matched_reviews)
                for kind, digest in revision.rerun_review_sha256.items()
            ):
                raise ValueError("revision record does not bind the complete rerun review outputs")
        return self


class ScenarioAcceptanceRecord(VersionedImmutableModel):
    """Record the acyclic researcher acceptance decision before publishing an accepted artifact."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    candidate_sha256: str
    review_history_sha256: str
    accepted_at: datetime
    accepted_by: str = Field(min_length=1)
    record_sha256: str

    @field_validator("candidate_sha256", "review_history_sha256", "record_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate every acceptance provenance digest."""
        return validate_sha256(value)


class ScenarioPipelineDisposition(VersionedImmutableModel):
    """Persist the terminal automated-pipeline disposition for one candidate."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    decision: ReviewDecision
    candidate_sha256: str
    recorded_at: datetime

    @field_validator("candidate_sha256")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        """Validate the terminal candidate digest format."""
        return validate_sha256(value)
