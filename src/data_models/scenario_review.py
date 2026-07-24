"""Strict automated and researcher review records for versioned scenarios."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, validate_sha256
from src.data_models.experiments import ProviderCallProvenance
from src.data_models.scenarios import SpecificityElement

MAX_AUTOMATED_REVISION_CYCLES = 1


class AutomatedReviewKind(str, Enum):
    """Identify the independent semantic scenario-review contract."""

    SCENARIO_QUALITY = "scenario_quality"


def required_automated_review_kinds(scenario_id: str) -> Set[AutomatedReviewKind]:
    """Return the single semantic review required for every scenario."""
    return {AutomatedReviewKind.SCENARIO_QUALITY}


class ReviewDecision(str, Enum):
    """Identify an automated or researcher scenario decision."""

    ACCEPT = "accept"
    REVISE = "revise"
    MANUAL_RESTRUCTURE = "manual_restructure"
    REJECT = "reject"


class ReviewPass(str, Enum):
    """Identify the sole annotation pass in the active protocol."""

    INITIAL = "initial"


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

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
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

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
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
    def validate_required_reviews_rerun(self) -> "RevisionCycleRecord":
        """Require every stage-relevant automated review after a revision."""
        if set(self.rerun_review_sha256) != required_automated_review_kinds(self.scenario_id):
            raise ValueError("every revision cycle must rerun the stage-relevant automated reviews")
        expected_dependencies = {
            "material_facts",
            "fact_pairs",
        }
        if set(self.rebuilt_dependency_sha256) != expected_dependencies:
            raise ValueError("every revision cycle must rebuild and hash all dependent scenario artifacts")
        return self


class ScenarioReviewLabels(ImmutableModel):
    """Capture the complete researcher scenario-review checklist."""

    factual_and_arithmetic_consistent: bool
    visible_fact_text_valid: bool
    facts_atomic_and_decision_coordinates_valid: bool
    all_material_facts_equally_required: bool
    pair_matching_acceptable: bool
    only_four_directional_material_facts: bool
    visible_fact_presentation_acceptable: bool
    customer_facing_naturalness: bool
    authority_limits_respected: bool
    decision_support_task_valid: bool
    material_customer_harm_high_stakes: bool
    latent_interest_conflict_valid: bool
    fact_direction_matches_conflict: bool
    evaluated_prompt_conflict_leakage_absent: bool
    treatment_leakage_absent: bool
    replication_distinct: bool

    def all_pass(self) -> bool:
        """Return whether every required scenario-review label passes."""
        return all(bool(value) for value in self.model_dump().values())


class PairDiagnostics(ImmutableModel):
    """Expose blinded descriptive pair-matching diagnostics without thresholds."""

    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_P[12]$")
    proposition_word_counts: Dict[str, int]
    numeric_burden: Dict[str, int]
    conditional_burden: Dict[str, int]
    hedging_burden: Dict[str, int]
    readability: Dict[str, Decimal]
    arithmetic_dependency: Dict[str, bool]
    shared_quantities: List[str]
    blinded_materiality_ratings: Dict[str, int]

    @model_validator(mode="after")
    def validate_sides(self) -> "PairDiagnostics":
        """Require both opaque sides for every side-specific diagnostic."""
        expected = {"side_a", "side_b"}
        for field_name in [
            "proposition_word_counts",
            "numeric_burden",
            "conditional_burden",
            "hedging_burden",
            "readability",
            "arithmetic_dependency",
            "blinded_materiality_ratings",
        ]:
            if set(getattr(self, field_name)) != expected:
                raise ValueError(f"{field_name} must contain blinded side_a and side_b entries")
        return self


class ResearcherScenarioReview(VersionedImmutableModel):
    """Store the single researcher review used for scenario acceptance."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    review_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    anonymised_item_id: str = Field(min_length=1)
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    decision: ReviewDecision
    labels: ScenarioReviewLabels
    pair_diagnostics: List[PairDiagnostics] = Field(default_factory=list, max_length=2)
    specificity_elements: List[SpecificityElement] = Field(default_factory=list)
    reviewed_artifact_sha256: str
    reviewed_at: datetime
    researcher_id: str = Field(min_length=1)
    notes: str

    @field_validator("reviewed_artifact_sha256")
    @classmethod
    def validate_artifact_hash(cls, value: str) -> str:
        """Validate the reviewed artifact digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_acceptance_checklist(self) -> "ResearcherScenarioReview":
        """Require every checklist label to pass when the researcher accepts a scenario."""
        if self.decision == ReviewDecision.ACCEPT and not self.labels.all_pass():
            raise ValueError("accepted scenario reviews require every checklist item to pass")
        if self.decision == ReviewDecision.ACCEPT and len(self.pair_diagnostics) != 2:
            raise ValueError("accepted scenario reviews require both pair diagnostics to be viewed and persisted")
        specificity_ids = [element.element_id for element in self.specificity_elements]
        if len(specificity_ids) != len(set(specificity_ids)):
            raise ValueError("researcher-selected specificity element identifiers must be unique")
        if self.decision == ReviewDecision.ACCEPT:
            expected_fact_ids = {f"{self.scenario_id}_F{index}" for index in range(1, 5)}
            if not {element.fact_id for element in self.specificity_elements}.issubset(expected_fact_ids):
                raise ValueError("accepted scenario reviews require specificity elements to refer to material facts")
            if any(sum(element.fact_id == fact_id for element in self.specificity_elements) > 3 for fact_id in expected_fact_ids):
                raise ValueError("accepted scenario reviews allow at most three specificity elements per material fact")
        elif self.specificity_elements:
            raise ValueError("specificity elements are recorded only when a scenario is accepted")
        return self


class ScenarioReviewHistory(VersionedImmutableModel):
    """Collect complete automated, revision, and researcher review provenance."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    automated_reviews: List[AutomatedScenarioReview] = Field(min_length=1)
    revisions: List[RevisionCycleRecord] = Field(max_length=MAX_AUTOMATED_REVISION_CYCLES)
    researcher_reviews: List[ResearcherScenarioReview] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_review_history(self) -> "ScenarioReviewHistory":
        """Require stage-relevant reviews and a sequential, hash-linked revision history."""
        required_kinds = required_automated_review_kinds(self.scenario_id)
        observed_kinds = {review.review_kind for review in self.automated_reviews}
        if not required_kinds.issubset(observed_kinds):
            raise ValueError("automated review history is missing a stage-relevant review kind")
        if not observed_kinds.issubset(required_kinds):
            raise ValueError("automated review history contains a review kind that is not used at this stage")
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

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
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

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    decision: ReviewDecision
    candidate_sha256: str
    recorded_at: datetime

    @field_validator("candidate_sha256")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        """Validate the terminal candidate digest format."""
        return validate_sha256(value)


class ScenarioPipelineFailureRecord(VersionedImmutableModel):
    """Persist one failed scenario-pipeline attempt for reproducible debugging."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    recorded_at: datetime
    record_sha256: str

    @field_validator("record_sha256")
    @classmethod
    def validate_record_hash(cls, value: str) -> str:
        """Validate the failure-record digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_self_hash(self) -> "ScenarioPipelineFailureRecord":
        """Bind the failure record to its canonical content."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected_hash:
            raise ValueError("scenario-pipeline failure record hash does not match canonical content")
        return self
