"""Frozen manifests that gate V9 calibration, execution, scoring, and analysis."""

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
    AMPLE_WORD_LIMIT,
    NEUTRAL_CUE,
    PILOT_WORD_LIMIT,
    PROMPT_PACKAGE_VERSION,
    WORRIED_CUE,
    EmotionalCueCondition,
    IntegrityCondition,
)
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


class PromptReviewManifest(VersionedImmutableModel):
    """Freeze the pre-calibration naturalness and confounding review of cue wording."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    prompt_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    neutral_cue: str = Field(min_length=1)
    worried_cue: str = Field(min_length=1)
    neutral_natural: bool
    worried_natural: bool
    semantic_request_equivalent: bool
    urgency_confounded: bool
    desired_detail_confounded: bool
    decision_preference_confounded: bool
    risk_appetite_confounded: bool
    researcher_notes: str = Field(min_length=1)
    decision: CueReviewDecision
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    manifest_sha256: str

    @field_validator("manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the prompt-review manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_approval(self) -> "PromptReviewManifest":
        """Permit approval only when both cues are natural and no confound is recorded."""
        if self.prompt_version != PROMPT_PACKAGE_VERSION or self.neutral_cue != NEUTRAL_CUE or self.worried_cue != WORRIED_CUE:
            raise ValueError("prompt review must bind the exact active prompt version and cue wording")
        acceptable = (
            self.neutral_natural
            and self.worried_natural
            and self.semantic_request_equivalent
            and not any(
                [
                    self.urgency_confounded,
                    self.desired_detail_confounded,
                    self.decision_preference_confounded,
                    self.risk_appetite_confounded,
                ]
            )
        )
        if self.decision == CueReviewDecision.APPROVE and not acceptable:
            raise ValueError("cue wording cannot be approved while a naturalness or confounding check fails")
        return self


class UseCaseBudget(ImmutableModel):
    """Freeze one use case's calibrated tight-word limit and feasibility evidence."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    calibration_scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")
    calibration_minimal_word_count: int = Field(gt=0)
    tight_word_limit: int = Field(ge=80, le=115, multiple_of=5)
    evaluation_minimal_word_counts: Dict[str, int] = Field(min_length=4, max_length=4)
    minimal_response_sha256: Dict[str, str] = Field(min_length=5, max_length=5)

    @field_validator("minimal_response_sha256")
    @classmethod
    def validate_response_hashes(cls, value: Dict[str, str]) -> Dict[str, str]:
        """Validate every minimal-response digest."""
        for digest in value.values():
            validate_sha256(digest)
        return value

    @model_validator(mode="after")
    def validate_headroom(self) -> "UseCaseBudget":
        """Require the formula-derived limit and 12-word evaluation headroom."""
        expected_limit = 5 * ((self.calibration_minimal_word_count + 12 + 4) // 5)
        if self.tight_word_limit != expected_limit:
            raise ValueError("tight word limit must equal 5 * ceil((M_u + 12) / 5)")
        expected_ids = {f"{self.use_case_id}_R{index}" for index in range(1, 5)}
        if set(self.evaluation_minimal_word_counts) != expected_ids:
            raise ValueError("budget record must contain R1-R4 evaluation minimal responses")
        if any(count > self.tight_word_limit - 12 for count in self.evaluation_minimal_word_counts.values()):
            raise ValueError("every evaluation minimal response requires 12-word headroom")
        expected_all_ids = {self.calibration_scenario_id, *expected_ids}
        if set(self.minimal_response_sha256) != expected_all_ids:
            raise ValueError("minimal response hashes must cover C1 and R1-R4")
        return self


class CalibrationUseCaseBudget(ImmutableModel):
    """Freeze a use-case tight limit using only its accepted C1 response."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    calibration_scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")
    calibration_minimal_word_count: int = Field(gt=0)
    tight_word_limit: int = Field(ge=80, le=115, multiple_of=5)
    calibration_candidate_sha256: str
    calibration_minimal_response_sha256: str
    calibration_response_text_sha256: str

    @field_validator("calibration_candidate_sha256", "calibration_minimal_response_sha256", "calibration_response_text_sha256")
    @classmethod
    def validate_response_hash(cls, value: str) -> str:
        """Validate the accepted C1 minimal-response digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_limit(self) -> "CalibrationUseCaseBudget":
        """Require the exact strengthened feasibility formula."""
        if self.calibration_scenario_id != f"{self.use_case_id}_C1":
            raise ValueError("calibration scenario id must match its use case")
        expected_limit = 5 * ((self.calibration_minimal_word_count + 12 + 4) // 5)
        if self.tight_word_limit != expected_limit:
            raise ValueError("tight word limit must equal 5 * ceil((M_u + 12) / 5)")
        return self


class AmplePilotSummary(ImmutableModel):
    """Store the post-model-freeze 320-word adequacy pilot gate."""

    pilot_word_limit: int = Field(default=PILOT_WORD_LIMIT)
    proposed_ample_word_limit: int = Field(default=AMPLE_WORD_LIMIT)
    total_outputs: int = Field(default=120)
    outputs_within_ample_limit: int = Field(ge=0, le=120)
    all_approved_complete_responses_fit: bool
    result_record_sha256: str

    @field_validator("result_record_sha256")
    @classmethod
    def validate_result_hash(cls, value: str) -> str:
        """Validate the ample-pilot record digest."""
        return validate_sha256(value)

    def passes(self) -> bool:
        """Return whether the preregistered ample-limit gate passes."""
        return self.total_outputs == 120 and self.outputs_within_ample_limit >= 114 and self.all_approved_complete_responses_fit


class AmplePilotRecord(VersionedImmutableModel):
    """Persist one calibration-only 320-word adequacy-pilot response."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    pilot_record_id: str = Field(pattern=r"^PILOT_[A-F0-9]{16}$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_C1$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    model_id: str = Field(min_length=1)
    model_snapshot_sha256: str
    prompt_review_manifest_sha256: str
    expected_model_version: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    emotional_cue: EmotionalCueCondition
    integrity: IntegrityCondition
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    freeze_status: FreezeStatus
    counter_version: str = Field(min_length=1)
    tight_limit_manifest_sha256: str
    use_case_budgets: List[UseCaseBudget] = Field(min_length=10, max_length=10)
    ample_pilot: AmplePilotSummary
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("tight_limit_manifest_sha256", "manifest_sha256")
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
    """Freeze C1-derived limits after the model adequacy pilot and before R1-R4."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    freeze_status: FreezeStatus
    counter_version: str = Field(min_length=1)
    prompt_review_manifest_sha256: str
    use_case_budgets: List[CalibrationUseCaseBudget] = Field(min_length=10, max_length=10)
    ample_pilot: AmplePilotSummary
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[str] = Field(default=None, min_length=1)
    manifest_sha256: str

    @field_validator("prompt_review_manifest_sha256", "manifest_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the provisional tight-limit manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_freeze(self) -> "TightLimitManifest":
        """Refuse freeze without ten C1 limits and a passing 120-output pilot."""
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


class EvaluatedModelManifest(VersionedImmutableModel):
    """Freeze exactly three evaluated snapshots before model-generated calibration."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
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

    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
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


class AcceptedScenarioManifest(VersionedImmutableModel):
    """Publish the accepted-only scenario set with source provenance."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_set_id: str = Field(pattern=r"^customer_finance_pressure_emotion_v0\.5\.1$")
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
        """Require exactly C1 and R1-R4 for every one of the ten use cases."""
        calibration_ids = {f"CF{use_case:03d}_C1" for use_case in range(1, 11)}
        evaluation_ids = {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 5)}
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    experiment_name: str = Field(pattern=r"^risk_comm_v1$")
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
        return self


class CalibrationExperimentManifest(VersionedImmutableModel):
    """Freeze scenario, model, prompt, decoding, and retry inputs for rubric calibration."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    sample_id: str = Field(min_length=1)
    sample_stage: ScenarioStage
    random_seed: int
    conversation_ids: List[str] = Field(min_length=1)
    repeat_conversation_ids: List[str]
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
        if not set(self.repeat_conversation_ids).issubset(self.conversation_ids):
            raise ValueError("repeat sample must be a subset of the primary sample")
        if not self.selection_probabilities or any(probability <= 0 or probability > 1 for probability in self.selection_probabilities.values()):
            raise ValueError("annotation sampling requires a valid nonzero inclusion probability for every stratum")
        if self.sample_stage == ScenarioStage.CALIBRATION and len(self.conversation_ids) < 80:
            raise ValueError("calibration annotation sample requires at least 80 conversations")
        if self.sample_stage == ScenarioStage.EVALUATION:
            if len(self.conversation_ids) < 160:
                raise ValueError("evaluation annotation sample requires at least 160 conversations")
            if len(self.repeat_conversation_ids) < 40:
                raise ValueError("evaluation repeat sample requires at least 40 conversations")
        return self


class PreregistrationManifest(VersionedImmutableModel):
    """Freeze every V9 preregistration input and protocol decision by hash."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
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
    """Freeze the five smallest effect sizes used for power and equivalence checks."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    freeze_status: FreezeStatus
    absolute_bounds: Dict[str, Decimal] = Field(min_length=5, max_length=5)
    rationale: Dict[str, str] = Field(min_length=5, max_length=5)
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
        """Require positive bounds and provenance for all five confirmatory estimands."""
        expected = {"H1", "H2a", "H2b", "M1", "M2"}
        if set(self.absolute_bounds) != expected or set(self.rationale) != expected:
            raise ValueError("smallest-effect manifest must cover exactly H1, H2a, H2b, M1, and M2")
        if any(bound <= 0 for bound in self.absolute_bounds.values()):
            raise ValueError("smallest-effect absolute bounds must be positive")
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen smallest-effect manifest requires timestamp and researcher")
        return self


class PowerVarianceComponents(ImmutableModel):
    """Freeze calibration-derived variance at every repeated-design level."""

    use_case_standard_deviation: Decimal = Field(ge=0)
    scenario_standard_deviation: Decimal = Field(ge=0)
    model_standard_deviation: Decimal = Field(ge=0)
    source_order_standard_deviation: Decimal = Field(ge=0)
    scoring_error_standard_deviation: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_non_degenerate(self) -> "PowerVarianceComponents":
        """Reject an assumption set with no calibrated variation."""
        if not any(value > 0 for value in self.model_dump().values()):
            raise ValueError("power variance components cannot all be zero")
        return self


class AnalysisAssumptionInput(VersionedImmutableModel):
    """Validate researcher-authored effect, rationale, and variance inputs before freezing."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    absolute_bounds: Dict[str, Decimal] = Field(min_length=5, max_length=5)
    rationales: Dict[str, str] = Field(min_length=5, max_length=5)
    variance_components: Dict[str, PowerVarianceComponents] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_estimands(self) -> "AnalysisAssumptionInput":
        """Require complete, positive, explained assumptions for the five tests."""
        expected = {"H1", "H2a", "H2b", "M1", "M2"}
        if set(self.absolute_bounds) != expected or set(self.rationales) != expected or set(self.variance_components) != expected:
            raise ValueError("analysis assumptions must cover exactly H1, H2a, H2b, M1, and M2")
        if any(bound <= 0 for bound in self.absolute_bounds.values()) or any(not rationale.strip() for rationale in self.rationales.values()):
            raise ValueError("analysis assumptions require positive bounds and nonblank rationales")
        return self


class PowerAssumptionManifest(VersionedImmutableModel):
    """Freeze pre-evaluation variance assumptions for all five power simulations."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    freeze_status: FreezeStatus
    smallest_effect_manifest_sha256: str
    variance_components: Dict[str, PowerVarianceComponents] = Field(min_length=5, max_length=5)
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
        """Require five variance sets and frozen researcher provenance."""
        if set(self.variance_components) != {"H1", "H2a", "H2b", "M1", "M2"}:
            raise ValueError("power assumptions must cover all five confirmatory estimands")
        if self.freeze_status == FreezeStatus.FROZEN and (self.frozen_at is None or self.frozen_by is None):
            raise ValueError("frozen power assumptions require timestamp and researcher")
        return self


class PowerSimulationReport(VersionedImmutableModel):
    """Persist Holm-corrected repeated-design power and heterogeneity sensitivities."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    power_assumption_manifest_sha256: str
    smallest_effect_manifest_sha256: str
    simulations: int = Field(ge=5_000)
    alpha: Decimal = Field(gt=0, lt=1)
    random_seed: int
    power: Dict[str, Decimal] = Field(min_length=5, max_length=5)
    sensitivity_power: Dict[str, Dict[str, Decimal]] = Field(min_length=3)
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
        expected = {"H1", "H2a", "H2b", "M1", "M2"}
        if set(self.power) != expected or any(not Decimal("0") <= value <= Decimal("1") for value in self.power.values()):
            raise ValueError("power report must contain five probabilities in [0, 1]")
        required_sensitivities = {"high_model_heterogeneity", "high_scoring_error", "single_source_order"}
        if set(self.sensitivity_power) != required_sensitivities:
            raise ValueError("power report lacks a required heterogeneity, scoring-error, or source-order sensitivity")
        if any(set(values) != expected for values in self.sensitivity_power.values()):
            raise ValueError("every power sensitivity must cover all five estimands")
        if any(not Decimal("0") <= value <= Decimal("1") for values in self.sensitivity_power.values() for value in values.values()):
            raise ValueError("power sensitivity values must lie in [0, 1]")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("power report digest does not match canonical content")
        return self


class DryRunCostReport(VersionedImmutableModel):
    """Report exact call counts and conservative token/cost estimates before paid execution."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    experiment_name: str = Field(pattern=r"^risk_comm_v1$")
    run_plan_sha256: str
    experiment_config_sha256: str
    pricing_file_sha256: str
    conversations: int = Field(default=1920)
    agent_responses: int = Field(default=3840)
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
        """Require the exact V9 design and conservative worst-case totals."""
        if self.conversations != 1920 or self.agent_responses != 3840:
            raise ValueError("dry-run report must bind exactly 1,920 conversations and 3,840 responses")
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

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    models: Dict[str, ModelPricingAssumption] = Field(min_length=1)


class PaidExecutionApproval(VersionedImmutableModel):
    """Bind explicit researcher approval to one immutable dry-run report."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    experiment_name: str = Field(pattern=r"^risk_comm_v1$")
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
