"""Frozen manifests that gate calibration, execution, scoring, and analysis."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, validate_sha256
from src.data_models.experiments import CompletionFinishReason, RetryPolicy
from src.data_models.scenarios import ScenarioStage
from src.data_models.study import (
    ALL_CUE_PHRASES,
    AMPLE_WORD_LIMIT,
    CUE_PAIRS,
    EXPERIMENT_DIMENSIONS,
    PILOT_WORD_LIMIT,
    PROMPT_PACKAGE_VERSION,
    ExperimentName,
    ExpressedConcernCondition,
    assigned_cue,
    cue_template_id,
)
from src.paths import ACTIVE_SCENARIO_SEED_SCHEMA_SHA256, ACTIVE_SCENARIO_SEED_SHA256, ACTIVE_SCENARIO_SET_ID
from src.scenarios.word_count import count_words


class FreezeStatus(str, Enum):
    """Identify whether a manifest remains draft or is immutable for downstream use."""

    DRAFT = "draft"
    FROZEN = "frozen"


class CueReviewDecision(str, Enum):
    """Identify the outcome of the researcher cue self-review."""

    APPROVE = "approve"
    REVISE = "revise"


class ModelWeightType(str, Enum):
    """Identify open- versus closed-weight evaluated model families."""

    OPEN = "open"
    CLOSED = "closed"


class CompleteRenderedRequestReview(ImmutableModel):
    """Store one holistic review of a complete scenario-specific rendered request."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    expressed_concern: ExpressedConcernCondition
    cue_template_id: int = Field(ge=1, le=4)
    assigned_phrase: str = Field(min_length=1)
    rendered_request_text: str = Field(min_length=1)
    rendered_request_sha256: str
    natural: bool
    semantically_equivalent: bool
    urgency_confounded: bool
    desired_detail_confounded: bool
    decision_preference_confounded: bool
    risk_appetite_confounded: bool
    notes: str = Field(min_length=1)

    @field_validator("rendered_request_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the complete rendered-request digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_rendering(self) -> "CompleteRenderedRequestReview":
        """Bind the exact assigned phrase, template, and complete rendered bytes."""
        if self.assigned_phrase != assigned_cue(self.scenario_id, self.expressed_concern):
            raise ValueError("request review does not use the assigned cue phrase")
        if self.cue_template_id != cue_template_id(self.scenario_id):
            raise ValueError("request review cue template does not match the frozen scenario mapping")
        if self.rendered_request_sha256 != sha256_bytes(self.rendered_request_text.encode("utf-8")):
            raise ValueError("rendered-request hash does not match exact text")
        observed = [phrase for phrase in ALL_CUE_PHRASES if phrase in self.rendered_request_text]
        if observed != [self.assigned_phrase] or self.rendered_request_text.count(self.assigned_phrase) != 1:
            raise ValueError("rendered request must contain exactly its assigned cue and no alternative phrase")
        return self


class CalibrationRenderedRequestReview(CompleteRenderedRequestReview):
    """Store one holistic review of a rendered C1 calibration request."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")


class EvaluationRenderedRequestReview(CompleteRenderedRequestReview):
    """Store one holistic review of a rendered R1-R2 evaluation request."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_R[12]$")


def _request_reviews_are_acceptable(request_reviews: List[CompleteRenderedRequestReview]) -> bool:
    """Return whether every complete request passes the frozen holistic review gates."""
    return all(
        review.natural
        and review.semantically_equivalent
        and not any(
            [
                review.urgency_confounded,
                review.desired_detail_confounded,
                review.decision_preference_confounded,
                review.risk_appetite_confounded,
            ]
        )
        for review in request_reviews
    )


class CalibrationPromptReviewManifest(VersionedImmutableModel):
    """Freeze holistic researcher review of the twenty C1 pilot requests."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    prompt_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    accepted_scenario_manifest_sha256: str
    cue_pairs: Dict[int, List[str]]
    request_reviews: List[CalibrationRenderedRequestReview] = Field(min_length=20, max_length=20)
    researcher_notes: str = Field(min_length=1)
    decision: CueReviewDecision
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    manifest_sha256: str

    @field_validator("accepted_scenario_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the calibration scenario and self-hash digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_approval(self) -> "CalibrationPromptReviewManifest":
        """Permit approval only after every C1-by-concern request passes review."""
        expected_pairs = {index: list(pair) for index, pair in CUE_PAIRS.items()}
        if self.prompt_version != PROMPT_PACKAGE_VERSION or self.cue_pairs != expected_pairs:
            raise ValueError("calibration prompt review must bind the active prompt version and cue pairs")
        expected_keys = {(f"CF{use_case:03d}_C1", condition) for use_case in range(1, 11) for condition in ExpressedConcernCondition}
        observed_keys = {(review.scenario_id, review.expressed_concern) for review in self.request_reviews}
        if observed_keys != expected_keys or len(observed_keys) != len(self.request_reviews):
            raise ValueError("calibration prompt review must contain each of the twenty C1-by-concern requests exactly once")
        if self.decision == CueReviewDecision.APPROVE and not _request_reviews_are_acceptable(self.request_reviews):
            raise ValueError("calibration prompts cannot be approved while a complete-request review fails")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected_hash:
            raise ValueError("calibration prompt-review digest does not match canonical content")
        return self


class PromptReviewManifest(VersionedImmutableModel):
    """Freeze holistic researcher review of all 40 rendered evaluation requests."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    prompt_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    accepted_scenario_manifest_sha256: str
    cue_pairs: Dict[int, List[str]]
    request_reviews: List[EvaluationRenderedRequestReview] = Field(min_length=40, max_length=40)
    researcher_notes: str = Field(min_length=1)
    decision: CueReviewDecision
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    manifest_sha256: str

    @field_validator("accepted_scenario_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the prompt-review manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_approval(self) -> "PromptReviewManifest":
        """Permit approval only after all 20×2 complete requests pass holistic review."""
        expected_pairs = {index: list(pair) for index, pair in CUE_PAIRS.items()}
        if self.prompt_version != PROMPT_PACKAGE_VERSION or self.cue_pairs != expected_pairs:
            raise ValueError("prompt review must bind the exact active prompt version and four cue pairs")
        expected_keys = {
            (f"CF{use_case:03d}_R{replication}", condition)
            for use_case in range(1, 11)
            for replication in range(1, 3)
            for condition in ExpressedConcernCondition
        }
        observed_keys = {(review.scenario_id, review.expressed_concern) for review in self.request_reviews}
        if observed_keys != expected_keys or len(observed_keys) != len(self.request_reviews):
            raise ValueError("prompt review must contain each of the 40 scenario-by-concern requests exactly once")
        if self.decision == CueReviewDecision.APPROVE and not _request_reviews_are_acceptable(self.request_reviews):
            raise ValueError("cue wording cannot be approved while any complete-request review fails")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected_hash:
            raise ValueError("prompt-review manifest digest does not match canonical content")
        return self


class UseCaseBudget(ImmutableModel):
    """Freeze one use case's calibrated tight-word limit and feasibility evidence."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    calibration_scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")
    calibration_fact_word_count: int = Field(gt=0)
    tight_word_limit: int = Field(ge=80, le=115, multiple_of=5)
    evaluation_fact_word_counts: Dict[str, int] = Field(min_length=2, max_length=2)
    material_facts_sha256: Dict[str, str] = Field(min_length=3, max_length=3)

    @field_validator("material_facts_sha256")
    @classmethod
    def validate_fact_hashes(cls, value: Dict[str, str]) -> Dict[str, str]:
        """Validate every material-fact-list digest."""
        for digest in value.values():
            validate_sha256(digest)
        return value

    @model_validator(mode="after")
    def validate_headroom(self) -> "UseCaseBudget":
        """Require the formula-derived limit and 12-word evaluation headroom."""
        expected_limit = 5 * ((self.calibration_fact_word_count + 12 + 4) // 5)
        if self.tight_word_limit != expected_limit:
            raise ValueError("tight word limit must equal 5 * ceil((M_u + 12) / 5)")
        expected_ids = {f"{self.use_case_id}_R{index}" for index in range(1, 3)}
        if set(self.evaluation_fact_word_counts) != expected_ids:
            raise ValueError("budget record must contain R1-R2 evaluation material fact lists")
        if any(count > self.tight_word_limit - 12 for count in self.evaluation_fact_word_counts.values()):
            raise ValueError("every evaluation material fact list requires 12-word headroom")
        expected_all_ids = {self.calibration_scenario_id, *expected_ids}
        if set(self.material_facts_sha256) != expected_all_ids:
            raise ValueError("material fact hashes must cover C1 and R1-R2")
        return self


class CalibrationUseCaseBudget(ImmutableModel):
    """Freeze a use-case tight limit using only its accepted C1 response."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    calibration_scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")
    calibration_fact_word_count: int = Field(gt=0)
    tight_word_limit: int = Field(ge=80, le=115, multiple_of=5)
    calibration_candidate_sha256: str
    calibration_material_facts_sha256: str
    calibration_fact_text_sha256: str

    @field_validator("calibration_candidate_sha256", "calibration_material_facts_sha256", "calibration_fact_text_sha256")
    @classmethod
    def validate_fact_hash(cls, value: str) -> str:
        """Validate the accepted C1 material-fact digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_limit(self) -> "CalibrationUseCaseBudget":
        """Require the exact strengthened feasibility formula."""
        if self.calibration_scenario_id != f"{self.use_case_id}_C1":
            raise ValueError("calibration scenario id must match its use case")
        expected_limit = 5 * ((self.calibration_fact_word_count + 12 + 4) // 5)
        if self.tight_word_limit != expected_limit:
            raise ValueError("tight word limit must equal 5 * ceil((M_u + 12) / 5)")
        return self


class AmplePilotSummary(ImmutableModel):
    """Store the post-model-freeze 320-word adequacy pilot gate."""

    pilot_word_limit: int = Field(default=PILOT_WORD_LIMIT)
    proposed_ample_word_limit: int = Field(default=AMPLE_WORD_LIMIT)
    total_outputs: int = Field(default=60)
    outputs_within_ample_limit: int = Field(ge=0, le=60)
    all_material_fact_lists_fit: bool
    result_record_sha256: str

    @field_validator("result_record_sha256")
    @classmethod
    def validate_result_hash(cls, value: str) -> str:
        """Validate the ample-pilot record digest."""
        return validate_sha256(value)

    def passes(self) -> bool:
        """Return whether the preregistered ample-limit gate passes."""
        return self.total_outputs == 60 and self.outputs_within_ample_limit >= 57 and self.all_material_fact_lists_fit


class AmplePilotRecord(VersionedImmutableModel):
    """Persist one calibration-only 320-word adequacy-pilot response."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    pilot_record_id: str = Field(pattern=r"^PILOT_[A-F0-9]{16}$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    model_id: str = Field(min_length=1)
    model_snapshot_sha256: str
    prompt_review_manifest_sha256: str
    expected_model_version: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    expressed_concern: ExpressedConcernCondition
    pilot_word_limit: int = Field(default=PILOT_WORD_LIMIT, ge=PILOT_WORD_LIMIT, le=PILOT_WORD_LIMIT)
    output_text: str = Field(min_length=1)
    output_word_count: int = Field(gt=0)
    finished_naturally: bool
    finish_reason: CompletionFinishReason
    prompt_sha256: str
    request_sha256: str
    random_seed: int
    provider_request_id: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    scenario_artifact_sha256: str
    generated_at: datetime
    output_sha256: str
    record_sha256: str

    @field_validator(
        "model_snapshot_sha256",
        "prompt_review_manifest_sha256",
        "prompt_sha256",
        "request_sha256",
        "scenario_artifact_sha256",
        "output_sha256",
        "record_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate pilot snapshot, scenario, and output digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_output(self) -> "AmplePilotRecord":
        """Require exact IDs, frozen word counts, and output bytes."""
        if self.use_case_id != self.scenario_id.split("_")[0]:
            raise ValueError("pilot record use_case_id must match its C1 scenario")
        if self.output_word_count != count_words(self.output_text):
            raise ValueError("pilot output word count does not match frozen counter")
        if self.output_sha256 != sha256_bytes(self.output_text.encode("utf-8")):
            raise ValueError("pilot output hash does not match output text")
        if self.returned_model_version != self.expected_model_version:
            raise ValueError("pilot response does not come from the frozen evaluated-model version")
        if self.finished_naturally != (self.finish_reason == CompletionFinishReason.STOP):
            raise ValueError("pilot natural-finish flag must derive from the provider finish reason")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected_hash:
            raise ValueError("pilot record digest does not match canonical content")
        return self

    def finishes_within_ample_limit(self) -> bool:
        """Return whether the response ended naturally within the proposed 240-word limit."""
        return self.finished_naturally and self.output_word_count <= AMPLE_WORD_LIMIT


class PilotAttemptStatus(str, Enum):
    """Identify a failed or successful exact-request ample-pilot attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AmplePilotAttempt(VersionedImmutableModel):
    """Persist each ample-pilot provider attempt immediately for safe resume."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    attempt_id: str = Field(pattern=r"^PILOTATTEMPT_[A-F0-9]{16}$")
    pilot_record_id: str = Field(pattern=r"^PILOT_[A-F0-9]{16}$")
    attempt_number: int = Field(ge=1)
    request_sha256: str
    status: PilotAttemptStatus
    returned_model_version: Optional[str] = Field(default=None, min_length=1)
    provider_request_id: Optional[str] = Field(default=None, min_length=1)
    finish_reason: Optional[CompletionFinishReason] = None
    response_sha256: Optional[str] = None
    error_type: Optional[str] = Field(default=None, min_length=1)
    error_message: Optional[str] = Field(default=None, min_length=1)
    started_at: datetime
    completed_at: datetime
    attempt_sha256: str

    @field_validator("request_sha256", "response_sha256", "attempt_sha256")
    @classmethod
    def validate_hashes(cls, value: Optional[str]) -> Optional[str]:
        """Validate request, response, and canonical attempt digests."""
        return validate_sha256(value) if value is not None else None

    @model_validator(mode="after")
    def validate_attempt(self) -> "AmplePilotAttempt":
        """Require coherent terminal fields, timestamps, and a canonical self-hash."""
        if self.completed_at < self.started_at:
            raise ValueError("pilot attempt cannot finish before it starts")
        if self.status == PilotAttemptStatus.SUCCEEDED:
            required = [self.returned_model_version, self.provider_request_id, self.finish_reason, self.response_sha256]
            if any(value is None for value in required) or self.error_type is not None or self.error_message is not None:
                raise ValueError("successful pilot attempt requires response provenance and no error")
        elif self.error_type is None or self.error_message is None or self.response_sha256 is not None:
            raise ValueError("failed pilot attempt requires error provenance and no response digest")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"attempt_sha256"}))
        if self.attempt_sha256 != expected_hash:
            raise ValueError("pilot attempt digest does not match canonical content")
        return self


class WordBudgetManifest(VersionedImmutableModel):
    """Freeze all ten use-case limits only after feasibility and ample checks pass."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    freeze_status: FreezeStatus
    counter_version: str = Field(min_length=1)
    tight_limit_manifest_sha256: str
    evaluated_model_manifest_sha256: str
    use_case_budgets: List[UseCaseBudget] = Field(min_length=10, max_length=10)
    ample_pilot: AmplePilotSummary
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("tight_limit_manifest_sha256", "evaluated_model_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the word-budget manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_freeze(self) -> "WordBudgetManifest":
        """Refuse a frozen manifest unless all ten use cases and the ample gate pass."""
        if {budget.use_case_id for budget in self.use_case_budgets} != {f"CF{index:03d}" for index in range(1, 11)}:
            raise ValueError("word-budget manifest must contain exactly CF001-CF010")
        if self.freeze_status == FreezeStatus.FROZEN:
            if not self.ample_pilot.passes():
                raise ValueError("cannot freeze word budgets before the ample-pilot gate passes")
            if self.frozen_at is None or self.frozen_by is None:
                raise ValueError("frozen word-budget manifest requires timestamp and researcher")
        return self


class TightLimitManifest(VersionedImmutableModel):
    """Freeze C1-derived limits after the model adequacy pilot and before R1-R2."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    freeze_status: FreezeStatus
    counter_version: str = Field(min_length=1)
    prompt_review_manifest_sha256: str
    evaluated_model_manifest_sha256: str
    use_case_budgets: List[CalibrationUseCaseBudget] = Field(min_length=10, max_length=10)
    ample_pilot: AmplePilotSummary
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("prompt_review_manifest_sha256", "evaluated_model_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the provisional tight-limit manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_freeze(self) -> "TightLimitManifest":
        """Refuse freeze without ten C1 limits and a passing 60-output pilot."""
        if {budget.use_case_id for budget in self.use_case_budgets} != {f"CF{index:03d}" for index in range(1, 11)}:
            raise ValueError("tight-limit manifest must contain exactly CF001-CF010")
        if self.freeze_status == FreezeStatus.FROZEN:
            if not self.ample_pilot.passes():
                raise ValueError("cannot freeze tight limits before the ample-pilot gate passes")
            if self.frozen_at is None or self.frozen_by is None:
                raise ValueError("frozen tight-limit manifest requires timestamp and researcher")
        return self


class EvaluatedModelSnapshot(ImmutableModel):
    """Freeze one evaluated model and its provider-returned identity."""

    name: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    family: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    weight_type: ModelWeightType
    metadata_sha256: str
    frozen_at: datetime

    @field_validator("metadata_sha256")
    @classmethod
    def validate_metadata_hash(cls, value: str) -> str:
        """Validate the model metadata snapshot digest."""
        return validate_sha256(value)


class C1EvaluationPurpose(str, Enum):
    """Identify the non-canonical purpose of a single-model C1 run."""

    DIAGNOSTIC = "diagnostic"


class C1EvaluationConfig(VersionedImmutableModel):
    """Snapshot a resumable one-model C1 2×2 diagnostic and its scoring contract."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: str = Field(pattern=r"^c1_[a-z0-9_]+_v[1-9][0-9]*$")
    purpose: C1EvaluationPurpose = C1EvaluationPurpose.DIAGNOSTIC
    accepted_scenario_manifest_sha256: str
    evaluated_model: EvaluatedModelSnapshot
    prompt_package_sha256: str
    scoring_execution_manifest_sha256: str
    scenario_count: int = Field(default=10, ge=10, le=10)
    evaluated_model_count: int = Field(default=1, ge=1, le=1)
    cell_count: int = Field(default=4, ge=4, le=4)
    expected_conversation_count: int = Field(default=40, ge=40, le=40)
    expected_agent_response_count: int = Field(default=80, ge=80, le=80)
    temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    randomisation_seed: int
    retry_policy: RetryPolicy
    results_filename: str = Field(pattern=r"^\d{8}T\d{6}_results\.jsonl$")
    log_filename: str = Field(pattern=r"^\d{8}T\d{6}_run\.log$")
    created_at: datetime

    @field_validator("accepted_scenario_manifest_sha256", "prompt_package_sha256", "scoring_execution_manifest_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate scenario and scoring-manifest digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_diagnostic_matrix(self) -> "C1EvaluationConfig":
        """Require aligned result/log names for the fixed 40-conversation matrix."""
        if self.results_filename.split("_", 1)[0] != self.log_filename.split("_", 1)[0]:
            raise ValueError("C1 diagnostic result and log filenames must share one timestamp")
        return self


class EvaluatedModelManifest(VersionedImmutableModel):
    """Freeze exactly three evaluated snapshots before model-generated calibration."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    freeze_status: FreezeStatus
    evaluated_models: List[EvaluatedModelSnapshot] = Field(min_length=3, max_length=3)
    scoring_judge_model_ids: List[str] = Field(min_length=1)
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the evaluated-model manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_freeze(self) -> "EvaluatedModelManifest":
        """Require family/provider diversity, open weights, and an independent judge."""
        if len({model.family for model in self.evaluated_models}) != 3:
            raise ValueError("evaluated snapshots must span exactly three families")
        if len({model.provider for model in self.evaluated_models}) < 2:
            raise ValueError("evaluated snapshots must span at least two providers")
        if not any(model.weight_type == ModelWeightType.OPEN for model in self.evaluated_models):
            raise ValueError("at least one evaluated snapshot must be open-weight")
        evaluated_ids = {model.model_id for model in self.evaluated_models}
        if not any(judge_id not in evaluated_ids for judge_id in self.scoring_judge_model_ids):
            raise ValueError("an evaluated model cannot serve as its own sole scoring judge")
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen evaluated-model manifest requires timestamp and researcher")
        return self


class AcceptedScenarioEntry(ImmutableModel):
    """Record one immutable accepted scenario in a scenario-set manifest."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    study_stage: ScenarioStage
    artifact_path: str = Field(min_length=1)
    artifact_sha256: str
    review_history_sha256: str
    acceptance_record_sha256: str

    @field_validator("artifact_sha256", "review_history_sha256", "acceptance_record_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate accepted-scenario provenance hashes."""
        return validate_sha256(value)


class ScenarioManifestScope(str, Enum):
    """Identify a calibration-only checkpoint versus the final complete scenario set."""

    CALIBRATION = "calibration"
    COMPLETE = "complete"


class AcceptedScenarioSetId(str, Enum):
    """Identify the active accepted scenario family."""

    V0_11_0 = ACTIVE_SCENARIO_SET_ID


class AcceptedScenarioManifest(VersionedImmutableModel):
    """Publish the accepted-only scenario set with seed provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    scenario_set_id: AcceptedScenarioSetId
    manifest_scope: ScenarioManifestScope
    seed_sha256: str
    seed_schema_sha256: str
    entries: List[AcceptedScenarioEntry]
    published_at: datetime
    published_by: str = Field(min_length=1)
    manifest_sha256: str

    @field_validator("seed_sha256", "seed_schema_sha256", "manifest_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate scenario-set source and manifest hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_complete_scenario_set(self) -> "AcceptedScenarioManifest":
        """Require exactly C1, R1, and R2 for every one of the ten use cases."""
        if self.seed_sha256 != ACTIVE_SCENARIO_SEED_SHA256 or self.seed_schema_sha256 != ACTIVE_SCENARIO_SEED_SCHEMA_SHA256:
            raise ValueError("accepted-scenario manifest must bind the approved immutable V0.11.0 seed and schema")
        calibration_ids = {f"CF{use_case:03d}_C1" for use_case in range(1, 11)}
        evaluation_ids = {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 3)}
        expected_ids = calibration_ids if self.manifest_scope == ScenarioManifestScope.CALIBRATION else calibration_ids | evaluation_ids
        entry_ids = {entry.scenario_id for entry in self.entries}
        if len(self.entries) != len(expected_ids) or entry_ids != expected_ids:
            raise ValueError("accepted-scenario manifest does not contain the exact scenario ids required by its scope")
        for entry in self.entries:
            expected_stage = ScenarioStage.CALIBRATION if entry.scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
            if entry.study_stage != expected_stage:
                raise ValueError("accepted-scenario manifest stage does not match scenario id")
        return self


class ExperimentManifest(VersionedImmutableModel):
    """Freeze evaluated models, prompts, scenarios, decoding, and retry policy."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: ExperimentName
    expected_conversation_count: int = Field(ge=1)
    freeze_status: FreezeStatus
    evaluated_models: List[EvaluatedModelSnapshot] = Field(min_length=3, max_length=3)
    scoring_judge_model_ids: List[str] = Field(min_length=1)
    evaluated_model_manifest_sha256: str
    accepted_scenario_manifest_sha256: str
    word_budget_manifest_sha256: str
    prompt_review_manifest_sha256: str
    prompt_package_sha256: str
    scoring_execution_manifest_sha256: str
    scoring_contract_sha256: str
    decoding_temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    randomisation_seed: int
    retry_policy: RetryPolicy
    frozen_at: Optional[datetime] = None
    manifest_sha256: str

    @field_validator(
        "accepted_scenario_manifest_sha256",
        "evaluated_model_manifest_sha256",
        "word_budget_manifest_sha256",
        "prompt_review_manifest_sha256",
        "prompt_package_sha256",
        "scoring_execution_manifest_sha256",
        "scoring_contract_sha256",
        "manifest_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate every frozen input digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_model_design(self) -> "ExperimentManifest":
        """Require three families, provider diversity, open weights, and independent judges."""
        if len({model.family for model in self.evaluated_models}) != 3:
            raise ValueError("evaluated models must span exactly three model families")
        if len({model.provider for model in self.evaluated_models}) < 2:
            raise ValueError("evaluated models must span at least two providers")
        if not any(model.weight_type == ModelWeightType.OPEN for model in self.evaluated_models):
            raise ValueError("at least one evaluated model must be open-weight")
        evaluated_ids = {model.model_id for model in self.evaluated_models}
        if not any(judge_id not in evaluated_ids for judge_id in self.scoring_judge_model_ids):
            raise ValueError("an evaluated model cannot serve as its own sole scoring judge")
        if self.freeze_status == FreezeStatus.FROZEN and self.frozen_at is None:
            raise ValueError("frozen experiment manifest requires frozen_at")
        expected = EXPERIMENT_DIMENSIONS[self.experiment_name].conversation_count
        if self.expected_conversation_count != expected:
            raise ValueError(f"{self.experiment_name.value} manifest must freeze exactly {expected} conversations")
        return self


class CalibrationExperimentManifest(VersionedImmutableModel):
    """Freeze scenario, model, prompt, decoding, and retry inputs for rubric calibration."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: str = Field(pattern=r"^risk_comm_calibration_v1$")
    freeze_status: FreezeStatus
    evaluated_models: List[EvaluatedModelSnapshot] = Field(min_length=3, max_length=3)
    evaluated_model_manifest_sha256: str
    accepted_scenario_manifest_sha256: str
    word_budget_manifest_sha256: str
    prompt_review_manifest_sha256: str
    prompt_package_sha256: str
    decoding_temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    randomisation_seed: int
    retry_policy: RetryPolicy
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator(
        "evaluated_model_manifest_sha256",
        "accepted_scenario_manifest_sha256",
        "word_budget_manifest_sha256",
        "prompt_review_manifest_sha256",
        "prompt_package_sha256",
        "manifest_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate every calibration input and self-digest field."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_freeze(self) -> "CalibrationExperimentManifest":
        """Require exact model design and provenance before calibration calls."""
        if len({model.family for model in self.evaluated_models}) != 3 or len({model.provider for model in self.evaluated_models}) < 2:
            raise ValueError("calibration models must preserve the frozen three-family, two-provider design")
        if not any(model.weight_type == ModelWeightType.OPEN for model in self.evaluated_models):
            raise ValueError("calibration models must include an open-weight family")
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen calibration manifest requires timestamp and researcher")
        return self


class ScoringExecutionManifest(VersionedImmutableModel):
    """Freeze scoring judges, contracts, fact ordering, and invalid-output retries."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    freeze_status: FreezeStatus
    judge_model_ids: List[str] = Field(min_length=1)
    judge_snapshots: List[EvaluatedModelSnapshot] = Field(min_length=1)
    scoring_contract_sha256: str
    fact_order_seed: int
    retry_policy: RetryPolicy
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("scoring_contract_sha256", "manifest_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate scoring contract and manifest digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_freeze(self) -> "ScoringExecutionManifest":
        """Require provenance whenever the scoring package is frozen."""
        if len(self.judge_model_ids) != len(set(self.judge_model_ids)):
            raise ValueError("scoring judge model ids must be unique")
        if {snapshot.model_id for snapshot in self.judge_snapshots} != set(self.judge_model_ids):
            raise ValueError("scoring judge ids must exactly match their frozen returned snapshots")
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen scoring execution manifest requires timestamp and researcher")
        return self


class AnnotationSampleManifest(VersionedImmutableModel):
    """Freeze a blinded calibration or evaluation annotation sample."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    sample_id: str = Field(min_length=1)
    sample_stage: ScenarioStage
    random_seed: int
    conversation_ids: List[str] = Field(min_length=1)
    strata_summary: Dict[str, int]
    selection_probabilities: Dict[str, Decimal]
    scoring_execution_manifest_sha256: str
    source_transcripts_sha256: str
    frozen_at: datetime
    manifest_sha256: str

    @field_validator("source_transcripts_sha256", "scoring_execution_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate annotation-sample provenance hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_sample_sizes(self) -> "AnnotationSampleManifest":
        """Enforce minimum calibration and locked evaluation sample sizes."""
        if len(self.conversation_ids) != len(set(self.conversation_ids)):
            raise ValueError("annotation sample conversation ids must be unique")
        if not self.selection_probabilities or any(probability <= 0 or probability > 1 for probability in self.selection_probabilities.values()):
            raise ValueError("annotation sampling requires a valid nonzero inclusion probability for every stratum")
        if self.sample_stage == ScenarioStage.CALIBRATION and len(self.conversation_ids) != 80:
            raise ValueError("calibration annotation sample requires exactly 80 conversations")
        if self.sample_stage == ScenarioStage.EVALUATION:
            if len(self.conversation_ids) != 160:
                raise ValueError("evaluation annotation sample requires exactly 160 conversations")
        return self


class PreregistrationManifest(VersionedImmutableModel):
    """Freeze every preregistration input and protocol decision by hash."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_manifest_sha256: str
    experiment_config_sha256: str
    run_plan_sha256: str
    accepted_scenario_manifest_sha256: str
    word_budget_manifest_sha256: str
    calibration_annotation_sample_manifest_sha256: str
    analysis_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    analysis_code_sha256: str
    power_report_sha256: str
    smallest_effects_sha256: str
    retry_policy_sha256: str
    analysis_plan_sha256: str
    protocol_deviation_policy_sha256: str
    frozen_at: datetime
    frozen_by: str = Field(min_length=1)
    manifest_sha256: str

    @field_validator(
        "experiment_manifest_sha256",
        "experiment_config_sha256",
        "run_plan_sha256",
        "accepted_scenario_manifest_sha256",
        "word_budget_manifest_sha256",
        "calibration_annotation_sample_manifest_sha256",
        "analysis_code_sha256",
        "power_report_sha256",
        "smallest_effects_sha256",
        "retry_policy_sha256",
        "analysis_plan_sha256",
        "protocol_deviation_policy_sha256",
        "manifest_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate each preregistration component digest."""
        return validate_sha256(value)


class ProtocolDeviation(ImmutableModel):
    """Record one post-preregistration protocol deviation and its scientific disposition."""

    deviation_id: str = Field(pattern=r"^DEV_[A-Z0-9_]+$")
    occurred_at: datetime
    lifecycle_gate: int = Field(ge=8, le=13)
    description: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    analysis_impact: str = Field(min_length=1)
    disposition: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)


class ProtocolDeviationManifest(VersionedImmutableModel):
    """Finalise the complete post-preregistration deviation register by backward hashes."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    preregistration_manifest_sha256: str
    experiment_manifest_sha256: str
    deviations: List[ProtocolDeviation]
    finalised_at: datetime
    finalised_by: str = Field(min_length=1)
    manifest_sha256: str

    @field_validator("preregistration_manifest_sha256", "experiment_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate deviation-register provenance and self-digest fields."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_manifest(self) -> "ProtocolDeviationManifest":
        """Require unique deviations and an exact canonical self-hash, including an empty register."""
        if len({deviation.deviation_id for deviation in self.deviations}) != len(self.deviations):
            raise ValueError("protocol deviation identifiers must be unique")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected_hash:
            raise ValueError("protocol deviation manifest digest does not match canonical content")
        return self


class SmallestEffectManifest(VersionedImmutableModel):
    """Freeze the two smallest composite effects used for power and equivalence checks."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    freeze_status: FreezeStatus
    absolute_bounds: Dict[str, Decimal] = Field(min_length=2, max_length=2)
    rationale: Dict[str, str] = Field(min_length=2, max_length=2)
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the smallest-effect manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_effects(self) -> "SmallestEffectManifest":
        """Require positive bounds and provenance for both confirmatory estimands."""
        expected = {"H1", "H2"}
        if set(self.absolute_bounds) != expected or set(self.rationale) != expected:
            raise ValueError("smallest-effect manifest must cover exactly H1 and H2")
        if any(bound <= 0 for bound in self.absolute_bounds.values()):
            raise ValueError("smallest-effect absolute bounds must be positive")
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen smallest-effect manifest requires timestamp and researcher")
        return self


class PowerVarianceComponents(ImmutableModel):
    """Freeze calibration-derived variance at every repeated-design level."""

    cue_template_standard_deviation: Decimal = Field(ge=0)
    pair_standard_deviation: Decimal = Field(ge=0)
    fact_standard_deviation: Decimal = Field(ge=0)
    scenario_standard_deviation: Decimal = Field(ge=0)
    model_standard_deviation: Decimal = Field(ge=0)
    scoring_error_standard_deviation: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_non_degenerate(self) -> "PowerVarianceComponents":
        """Reject an assumption set with no calibrated variation."""
        if not any(value > 0 for value in self.model_dump().values()):
            raise ValueError("power variance components cannot all be zero")
        return self


class AnalysisAssumptionInput(VersionedImmutableModel):
    """Validate researcher-authored effect, rationale, and variance inputs before freezing."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    absolute_bounds: Dict[str, Decimal] = Field(min_length=2, max_length=2)
    rationales: Dict[str, str] = Field(min_length=2, max_length=2)
    variance_components: PowerVarianceComponents

    @model_validator(mode="after")
    def validate_estimands(self) -> "AnalysisAssumptionInput":
        """Require complete, positive, explained assumptions for both tests."""
        expected = {"H1", "H2"}
        if set(self.absolute_bounds) != expected or set(self.rationales) != expected:
            raise ValueError("analysis assumptions must cover exactly H1 and H2")
        if any(bound <= 0 for bound in self.absolute_bounds.values()) or any(not rationale.strip() for rationale in self.rationales.values()):
            raise ValueError("analysis assumptions require positive bounds and nonblank rationales")
        return self


class PowerAssumptionManifest(VersionedImmutableModel):
    """Freeze pre-evaluation variance assumptions for the composite estimator."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    freeze_status: FreezeStatus
    smallest_effect_manifest_sha256: str
    variance_components: PowerVarianceComponents
    calibration_source_sha256: str
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("smallest_effect_manifest_sha256", "calibration_source_sha256", "manifest_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate every power-assumption provenance digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_assumptions(self) -> "PowerAssumptionManifest":
        """Require calibrated composite variance and frozen researcher provenance."""
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen power assumptions require timestamp and researcher")
        return self


class PowerSimulationReport(VersionedImmutableModel):
    """Persist Holm-corrected repeated-design power and heterogeneity sensitivities."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    power_assumption_manifest_sha256: str
    smallest_effect_manifest_sha256: str
    simulations: int = Field(ge=5_000)
    alpha: Decimal = Field(gt=0, lt=1)
    random_seed: int
    power: Dict[str, Decimal] = Field(min_length=2, max_length=2)
    sensitivity_power: Dict[str, Dict[str, Decimal]] = Field(min_length=2, max_length=2)
    generated_at: datetime
    report_sha256: str

    @field_validator("power_assumption_manifest_sha256", "smallest_effect_manifest_sha256", "report_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate report provenance and self-digest fields."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_report(self) -> "PowerSimulationReport":
        """Require every power surface, valid probabilities, and an exact canonical self-hash."""
        expected = {"H1", "H2"}
        if set(self.power) != expected or any(not Decimal("0") <= value <= Decimal("1") for value in self.power.values()):
            raise ValueError("power report must contain both probabilities in [0, 1]")
        required_sensitivities = {"high_model_heterogeneity", "high_scoring_error"}
        if set(self.sensitivity_power) != required_sensitivities:
            raise ValueError("power report lacks a required heterogeneity or scoring-error sensitivity")
        if any(set(values) != expected for values in self.sensitivity_power.values()):
            raise ValueError("every power sensitivity must cover both estimands")
        if any(not Decimal("0") <= value <= Decimal("1") for values in self.sensitivity_power.values() for value in values.values()):
            raise ValueError("power sensitivity values must lie in [0, 1]")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("power report digest does not match canonical content")
        return self


class DryRunCostReport(VersionedImmutableModel):
    """Report exact call counts and conservative token/cost estimates before paid execution."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: ExperimentName
    run_plan_sha256: str
    experiment_config_sha256: str
    pricing_file_sha256: str
    conversations: int = Field(gt=0)
    agent_responses: int = Field(gt=0)
    maximum_attempts_including_retries: int = Field(gt=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=0)
    worst_case_input_tokens: int = Field(ge=0)
    worst_case_output_tokens: int = Field(ge=0)
    worst_case_cost_usd: Decimal = Field(ge=0)
    pricing_assumptions: Dict[str, Decimal]
    generated_at: datetime
    report_sha256: str

    @field_validator("run_plan_sha256", "experiment_config_sha256", "pricing_file_sha256", "report_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate the run-plan and dry-run report digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_counts_and_costs(self) -> "DryRunCostReport":
        """Require the exact design and conservative worst-case totals."""
        dimensions = EXPERIMENT_DIMENSIONS[self.experiment_name]
        expected = (dimensions.conversation_count, dimensions.response_count)
        if (self.conversations, self.agent_responses) != expected:
            raise ValueError(f"dry-run report has invalid counts for {self.experiment_name.value}")
        if self.worst_case_input_tokens < self.estimated_input_tokens or self.worst_case_output_tokens < self.estimated_output_tokens:
            raise ValueError("worst-case token totals cannot be smaller than base estimates")
        if self.worst_case_cost_usd < self.estimated_cost_usd:
            raise ValueError("worst-case cost cannot be smaller than the base estimate")
        return self


class ModelPricingAssumption(ImmutableModel):
    """Store one provider's input and output price assumptions per million tokens."""

    input_per_million_usd: Decimal = Field(ge=0)
    output_per_million_usd: Decimal = Field(ge=0)


class PricingAssumptionInput(VersionedImmutableModel):
    """Validate model-keyed dry-run pricing assumptions from a researcher-authored file."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    models: Dict[str, ModelPricingAssumption] = Field(min_length=1)


class AmplePilotCostReport(VersionedImmutableModel):
    """Bind the exact 60-response ample pilot to an offline cost estimate."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    accepted_scenario_manifest_sha256: str
    evaluated_model_manifest_sha256: str
    prompt_review_manifest_sha256: str
    prompt_package_sha256: str
    retry_policy_sha256: str
    pricing_file_sha256: str
    randomisation_seed: int
    provider_request_sha256s: List[str] = Field(min_length=60, max_length=60)
    pilot_responses: int = Field(gt=0)
    maximum_attempts_including_retries: int = Field(gt=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=0)
    worst_case_input_tokens: int = Field(ge=0)
    worst_case_output_tokens: int = Field(ge=0)
    worst_case_cost_usd: Decimal = Field(ge=0)
    pricing_assumptions: Dict[str, Decimal]
    generated_at: datetime
    report_sha256: str

    @field_validator(
        "accepted_scenario_manifest_sha256",
        "evaluated_model_manifest_sha256",
        "prompt_review_manifest_sha256",
        "prompt_package_sha256",
        "retry_policy_sha256",
        "pricing_file_sha256",
        "report_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate every pilot input digest and the report self-digest."""
        return validate_sha256(value)

    @field_validator("provider_request_sha256s")
    @classmethod
    def validate_request_hashes(cls, value: List[str]) -> List[str]:
        """Validate and require sixty unique, canonically ordered request digests."""
        for digest in value:
            validate_sha256(digest)
        if len(set(value)) != 60 or value != sorted(value):
            raise ValueError("ample-pilot request digests must contain sixty unique hashes in canonical order")
        return value

    @model_validator(mode="after")
    def validate_cost_report(self) -> "AmplePilotCostReport":
        """Require the frozen response count, conservative totals, and exact self-hash."""
        if self.pilot_responses != 60:
            raise ValueError("ample-pilot cost report must cover exactly 60 responses")
        if self.maximum_attempts_including_retries < self.pilot_responses:
            raise ValueError("ample-pilot maximum attempts cannot be below the response count")
        if self.worst_case_input_tokens < self.estimated_input_tokens or self.worst_case_output_tokens < self.estimated_output_tokens:
            raise ValueError("ample-pilot worst-case tokens cannot be below estimated tokens")
        if self.worst_case_cost_usd < self.estimated_cost_usd:
            raise ValueError("ample-pilot worst-case cost cannot be below estimated cost")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("ample-pilot cost-report digest does not match canonical content")
        return self


class AmplePilotApproval(VersionedImmutableModel):
    """Bind explicit researcher cost approval to one ample-pilot report."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    cost_report_sha256: str
    approved: bool
    approved_maximum_cost_usd: Decimal = Field(gt=0)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    approval_sha256: str

    @field_validator("cost_report_sha256", "approval_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate the pilot cost-report and approval digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_approval(self) -> "AmplePilotApproval":
        """Require explicit approval and an exact canonical self-hash."""
        if not self.approved:
            raise ValueError("ample-pilot approval must be explicitly true")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected_hash:
            raise ValueError("ample-pilot approval digest does not match canonical content")
        return self


class PaidExecutionApproval(VersionedImmutableModel):
    """Bind explicit researcher approval to one immutable dry-run report."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: ExperimentName
    dry_run_report_sha256: str
    approved: bool
    approved_maximum_cost_usd: Decimal = Field(gt=0)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    approval_sha256: str

    @field_validator("dry_run_report_sha256", "approval_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate approval linkage and approval-record digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_explicit_approval(self) -> "PaidExecutionApproval":
        """Reject placeholder or negative approval records."""
        if not self.approved:
            raise ValueError("paid execution approval must be explicitly true")
        return self
