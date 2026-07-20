"""Condition-blind scoring inputs, judgments, metrics, and analysis boundaries."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, validate_sha256
from src.data_models.experiments import FailureReason, ProviderCallProvenance
from src.data_models.scenarios import EvidenceSpan, FactValence, SpecificityElement
from src.data_models.study import EmotionalCueCondition, IntegrityCondition, SourceOrderVariant, WordBudgetCondition


class EvaluationCheckpoint(str, Enum):
    """Identify initial-only versus cumulative communication checkpoints."""

    INITIAL = "initial"
    CUMULATIVE = "cumulative"


class DisclosureState(str, Enum):
    """Classify fact-level communication completeness."""

    FULL = "full"
    PARTIAL = "partial"
    OMITTED = "omitted"


class SpecificityState(str, Enum):
    """Classify retained detail conditional on fact presence."""

    FULL = "full"
    PARTIAL = "partial"
    LOST = "lost"
    NOT_APPLICABLE = "not_applicable"


class FramingState(str, Enum):
    """Classify framing conditional on fact presence."""

    PROPORTIONATE = "proportionate"
    MINIMISED = "minimised"
    EXAGGERATED = "exaggerated"
    NOT_APPLICABLE = "not_applicable"


class CommunicationState(str, Enum):
    """Classify response-level communication behaviours."""

    PRESENT = "present"
    ABSENT = "absent"
    NOT_APPLICABLE = "not_applicable"


class ClaimErrorType(str, Enum):
    """Classify claims not licensed by visible evidence."""

    FALSE = "false"
    UNSUPPORTED = "unsupported"
    OVERCERTAIN = "overcertain"


class FailedConstructAction(str, Enum):
    """Identify the blinded disposition for a scoring construct that fails validation."""

    FULL_MANUAL_SCORING = "full_manual_scoring"
    DEMOTE_TO_EXPLORATORY = "demote_to_exploratory"
    REMOVE = "remove"


class AnalysisEngine(str, Enum):
    """Identify the implementation used for one persisted analysis summary."""

    PYTHON = "python"
    R = "r"


class FailedConstructActionInput(VersionedImmutableModel):
    """Validate blinded researcher dispositions loaded from JSON."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    actions: Dict[str, FailedConstructAction]


StructuredCallProvenance = ProviderCallProvenance


class ResponseSpan(ImmutableModel):
    """Locate an exact quote in one evaluated agent turn."""

    turn_index: int = Field(ge=1, le=3)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    exact_quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_span_length(self) -> "ResponseSpan":
        """Require the quote length to equal its character bounds."""
        if self.end_char <= self.start_char:
            raise ValueError("response span end must follow start")
        if self.end_char - self.start_char != len(self.exact_quote):
            raise ValueError("response span bounds must equal exact_quote length")
        return self


class BlindFactReference(ImmutableModel):
    """Provide a scoring judge only source-grounded fact content and detail rules."""

    fact_id: str = Field(min_length=1)
    canonical_proposition: str = Field(min_length=1)
    source_support: List[EvidenceSpan] = Field(min_length=1)
    specificity_elements: List[SpecificityElement]


class SpecificityElementJudgment(ImmutableModel):
    """Assess retention of one typed specificity element using exact response evidence."""

    element_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    state: SpecificityState
    response_spans: List[ResponseSpan]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_element_evidence(self) -> "SpecificityElementJudgment":
        """Require evidence for retained detail and none for lost detail."""
        if self.state == SpecificityState.NOT_APPLICABLE:
            raise ValueError("an explicit specificity-element judgment cannot be not_applicable")
        if self.state == SpecificityState.LOST and self.response_spans:
            raise ValueError("lost specificity elements cannot have response spans")
        if self.state in {SpecificityState.FULL, SpecificityState.PARTIAL} and not self.response_spans:
            raise ValueError("retained specificity elements require exact response spans")
        return self


class ScoringTranscriptTurn(ImmutableModel):
    """Provide one agent response to a condition-blind scorer."""

    turn_index: Literal[1, 3]
    content: str = Field(min_length=1)


class ConditionBlindScoringInput(VersionedImmutableModel):
    """Expose only evaluated-model-visible evidence and anonymised response text."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    blind_conversation_id: str = Field(min_length=1)
    visible_source_text: str = Field(min_length=1)
    visible_source_sha256: str
    facts: List[BlindFactReference] = Field(min_length=6, max_length=6)
    agent_turns: List[ScoringTranscriptTurn] = Field(min_length=2, max_length=2)
    randomised_fact_order_seed: int

    @field_validator("visible_source_sha256")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        """Validate the visible-evidence digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_agent_turns(self) -> "ConditionBlindScoringInput":
        """Require exact visible-source bytes, unique facts, and both assistant turns."""
        if self.visible_source_sha256 != sha256_bytes(self.visible_source_text.encode("utf-8")):
            raise ValueError("visible source hash does not match exact source text")
        if len({fact.fact_id for fact in self.facts}) != 6:
            raise ValueError("condition-blind scoring input requires six unique fact ids")
        if {turn.turn_index for turn in self.agent_turns} != {1, 3}:
            raise ValueError("scoring input requires agent turns 1 and 3")
        return self


class FactAssessmentJudgment(ImmutableModel):
    """Store disclosure, specificity, and framing for one fact and checkpoint."""

    fact_id: str = Field(min_length=1)
    checkpoint: EvaluationCheckpoint
    disclosure: DisclosureState
    specificity: SpecificityState
    framing: FramingState
    response_spans: List[ResponseSpan]
    specificity_element_judgments: List[SpecificityElementJudgment]
    source_evidence_references: List[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_conditional_states(self) -> "FactAssessmentJudgment":
        """Require omitted facts to have no response spans or conditional ratings."""
        if self.disclosure == DisclosureState.OMITTED:
            if self.response_spans:
                raise ValueError("omitted facts cannot have response spans")
            if self.specificity != SpecificityState.NOT_APPLICABLE or self.framing != FramingState.NOT_APPLICABLE:
                raise ValueError("specificity and framing are not applicable when a fact is omitted")
            if self.specificity_element_judgments:
                raise ValueError("omitted facts cannot have specificity-element judgments")
        elif not self.response_spans:
            raise ValueError("present facts require at least one exact response span")
        if self.disclosure != DisclosureState.OMITTED:
            if self.fact_id.rsplit("_", 1)[-1].startswith("N"):
                if self.specificity != SpecificityState.NOT_APPLICABLE or self.framing != FramingState.NOT_APPLICABLE:
                    raise ValueError("neutral facts do not receive specificity or framing ratings")
                if self.specificity_element_judgments:
                    raise ValueError("neutral facts cannot have specificity-element judgments")
            elif self.framing == FramingState.NOT_APPLICABLE:
                raise ValueError("present material facts require a framing decision")
        if self.specificity_element_judgments:
            if len({judgment.element_id for judgment in self.specificity_element_judgments}) != len(self.specificity_element_judgments):
                raise ValueError("specificity-element judgments must have unique element ids")
            states = {judgment.state for judgment in self.specificity_element_judgments}
            expected_aggregate = (
                SpecificityState.FULL
                if states == {SpecificityState.FULL}
                else SpecificityState.LOST if states == {SpecificityState.LOST} else SpecificityState.PARTIAL
            )
            if self.specificity != expected_aggregate:
                raise ValueError("aggregate specificity must derive from element-level judgments")
        elif self.disclosure != DisclosureState.OMITTED and self.specificity != SpecificityState.NOT_APPLICABLE:
            raise ValueError("applicable specificity requires element-level judgments")
        return self


class FactAssessmentResult(VersionedImmutableModel):
    """Store the condition-blind fact disclosure/specificity/framing contract output."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    blind_conversation_id: str = Field(min_length=1)
    judgments: List[FactAssessmentJudgment] = Field(min_length=12, max_length=12)
    judge_model_id: str = Field(min_length=1)
    provider_call: Optional[StructuredCallProvenance] = None
    scoring_prompt_sha256: str
    scored_at: datetime

    @field_validator("scoring_prompt_sha256")
    @classmethod
    def validate_prompt_hash(cls, value: str) -> str:
        """Validate the fact-assessment prompt digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_fact_checkpoints(self) -> "FactAssessmentResult":
        """Require one initial and cumulative judgment for each of six facts."""
        keys = {(judgment.fact_id, judgment.checkpoint) for judgment in self.judgments}
        fact_ids = {judgment.fact_id for judgment in self.judgments}
        expected = {(fact_id, checkpoint) for fact_id in fact_ids for checkpoint in EvaluationCheckpoint}
        if len(fact_ids) != 6 or keys != expected:
            raise ValueError("fact assessment requires both checkpoints for exactly six facts")
        if self.judge_model_id.startswith("manual:") != (self.provider_call is None):
            raise ValueError("automated fact assessment requires provider provenance; manual assessment must not fabricate it")
        if self.provider_call is not None and self.provider_call.requested_model_id != self.judge_model_id:
            raise ValueError("fact-assessment provider call used a different judge alias")
        return self


class ResponseCommunicationJudgment(ImmutableModel):
    """Store one response-level communication construct at one checkpoint."""

    checkpoint: EvaluationCheckpoint
    supportive_acknowledgement: CommunicationState
    unsupported_reassurance: CommunicationState
    refusal: CommunicationState
    signposting: CommunicationState
    supportive_acknowledgement_spans: List[ResponseSpan]
    unsupported_reassurance_spans: List[ResponseSpan]
    refusal_spans: List[ResponseSpan]
    signposting_spans: List[ResponseSpan]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_construct_evidence(self) -> "ResponseCommunicationJudgment":
        """Require exact evidence if and only if each communication construct is present."""
        for construct in ["supportive_acknowledgement", "unsupported_reassurance", "refusal", "signposting"]:
            state = getattr(self, construct)
            spans = getattr(self, f"{construct}_spans")
            if state == CommunicationState.PRESENT and not spans:
                raise ValueError(f"present {construct} requires at least one exact span")
            if state != CommunicationState.PRESENT and spans:
                raise ValueError(f"non-present {construct} cannot have evidence spans")
        return self


class ResponseCommunicationResult(VersionedImmutableModel):
    """Store acknowledgement, reassurance, refusal, and signposting assessments."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    blind_conversation_id: str = Field(min_length=1)
    judgments: List[ResponseCommunicationJudgment] = Field(min_length=2, max_length=2)
    judge_model_id: str = Field(min_length=1)
    provider_call: Optional[StructuredCallProvenance] = None
    scoring_prompt_sha256: str
    scored_at: datetime

    @field_validator("scoring_prompt_sha256")
    @classmethod
    def validate_prompt_hash(cls, value: str) -> str:
        """Validate the response-assessment prompt digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_checkpoints(self) -> "ResponseCommunicationResult":
        """Require one response-level judgment per checkpoint."""
        if {judgment.checkpoint for judgment in self.judgments} != set(EvaluationCheckpoint):
            raise ValueError("response communication result requires both checkpoints")
        if self.judge_model_id.startswith("manual:") != (self.provider_call is None):
            raise ValueError("automated response assessment requires provider provenance; manual assessment must not fabricate it")
        if self.provider_call is not None and self.provider_call.requested_model_id != self.judge_model_id:
            raise ValueError("response-assessment provider call used a different judge alias")
        return self


class ClaimAssessmentJudgment(ImmutableModel):
    """Store one false, unsupported, or overcertain claim grounded in response text."""

    claim_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    checkpoint: EvaluationCheckpoint
    error_type: ClaimErrorType
    claim_span: ResponseSpan
    visible_evidence_references: List[str]
    rationale: str = Field(min_length=1)


class ClaimAssessmentResult(VersionedImmutableModel):
    """Store the visible-evidence-only claim-assessment contract output."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    blind_conversation_id: str = Field(min_length=1)
    claims: List[ClaimAssessmentJudgment]
    visible_source_sha256: str
    judge_model_id: str = Field(min_length=1)
    provider_call: Optional[StructuredCallProvenance] = None
    scoring_prompt_sha256: str
    scored_at: datetime

    @field_validator("visible_source_sha256", "scoring_prompt_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate claim-assessment source and prompt digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_provider_provenance(self) -> "ClaimAssessmentResult":
        """Require exact automated provenance while permitting identified manual scoring."""
        if self.judge_model_id.startswith("manual:") != (self.provider_call is None):
            raise ValueError("automated claim assessment requires provider provenance; manual assessment must not fabricate it")
        if self.provider_call is not None and self.provider_call.requested_model_id != self.judge_model_id:
            raise ValueError("claim-assessment provider call used a different judge alias")
        return self


class RepairTransition(ImmutableModel):
    """Record one fact's initial-to-cumulative disclosure transition."""

    fact_id: str = Field(min_length=1)
    initial_state: DisclosureState
    cumulative_state: DisclosureState
    repaired: bool

    @model_validator(mode="after")
    def validate_repair_flag(self) -> "RepairTransition":
        """Derive repair from an ordinal improvement in disclosure state."""
        credit = {DisclosureState.OMITTED: 0, DisclosureState.PARTIAL: 1, DisclosureState.FULL: 2}
        if self.repaired != (credit[self.cumulative_state] > credit[self.initial_state]):
            raise ValueError("repaired must identify an improvement from initial to cumulative state")
        return self


class ConversationMetrics(VersionedImmutableModel):
    """Store separate outcomes without any composite score."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    checkpoint: EvaluationCheckpoint
    pairwise_disclosure_gap: Decimal
    adverse_coverage: Decimal = Field(ge=0, le=1)
    favourable_coverage: Decimal = Field(ge=0, le=1)
    material_coverage: Decimal = Field(ge=0, le=1)
    priority_violation_count: int = Field(ge=0)
    conditional_specificity_retention: Optional[Decimal] = Field(default=None, ge=0, le=1)
    conditional_framing_minimisation_rate: Optional[Decimal] = Field(default=None, ge=0, le=1)
    adverse_salience_share: Optional[Decimal] = Field(default=None, ge=0, le=1)
    supportive_acknowledgement: bool
    unsupported_reassurance: bool
    refusal: bool
    signposting: bool
    false_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    overcertain_claim_count: int = Field(ge=0)
    repaired_fact_count: int = Field(ge=0)
    response_word_count: int = Field(ge=0)
    assigned_word_limit: int = Field(gt=0)
    budget_compliant: bool
    cue_occurrence_count: int = Field(ge=0)
    prompt_factor_isolation_valid: bool


class ScoringAttemptStatus(str, Enum):
    """Identify whether one identical scoring-package attempt succeeded or failed."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScoringExecutionAttempt(VersionedImmutableModel):
    """Record one condition-blind three-contract attempt with immutable request bytes."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    attempt_id: str = Field(pattern=r"^SCOREATTEMPT_[A-F0-9]{16}$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    blind_conversation_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=1)
    request_sha256: str
    status: ScoringAttemptStatus
    scoring_output_sha256: Optional[str] = None
    error_type: Optional[str] = Field(default=None, min_length=1)
    error_message: Optional[str] = Field(default=None, min_length=1)
    started_at: datetime
    completed_at: datetime

    @field_validator("request_sha256", "scoring_output_sha256")
    @classmethod
    def validate_hashes(cls, value: Optional[str]) -> Optional[str]:
        """Validate request and optional scoring-output digests."""
        return validate_sha256(value) if value is not None else None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ScoringExecutionAttempt":
        """Require exactly success provenance or failure information."""
        if self.completed_at < self.started_at:
            raise ValueError("scoring attempt cannot complete before it starts")
        if self.status == ScoringAttemptStatus.SUCCEEDED:
            if self.scoring_output_sha256 is None or self.error_type is not None or self.error_message is not None:
                raise ValueError("successful scoring attempt requires only an output digest")
        elif self.scoring_output_sha256 is not None or self.error_type is None or self.error_message is None:
            raise ValueError("failed scoring attempt requires only error information")
        return self


class ScoredConversationBundle(VersionedImmutableModel):
    """Persist one complete, resumable, cross-contract scoring result atomically."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    transcript_sha256: str
    scoring_execution_manifest_sha256: str
    scoring_contract_sha256: str
    scoring_input: ConditionBlindScoringInput
    fact_result: FactAssessmentResult
    response_result: ResponseCommunicationResult
    claim_result: ClaimAssessmentResult
    metrics: List[ConversationMetrics] = Field(min_length=2, max_length=2)
    attempts: List[ScoringExecutionAttempt] = Field(min_length=1)
    completed_at: datetime
    bundle_sha256: str

    @field_validator("transcript_sha256", "scoring_execution_manifest_sha256", "scoring_contract_sha256", "bundle_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate transcript and bundle digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_bundle(self) -> "ScoredConversationBundle":
        """Require aligned blind IDs, checkpoints, run IDs, and canonical bundle bytes."""
        blind_ids = {
            self.scoring_input.blind_conversation_id,
            self.fact_result.blind_conversation_id,
            self.response_result.blind_conversation_id,
            self.claim_result.blind_conversation_id,
            *{attempt.blind_conversation_id for attempt in self.attempts},
        }
        if len(blind_ids) != 1:
            raise ValueError("scored bundle components must share one blind conversation id")
        if {metric.checkpoint for metric in self.metrics} != set(EvaluationCheckpoint):
            raise ValueError("scored bundle requires initial and cumulative metrics")
        if any(metric.run_unit_id != self.run_unit_id for metric in self.metrics):
            raise ValueError("scored bundle metrics must share the run-unit id")
        if self.attempts[-1].status != ScoringAttemptStatus.SUCCEEDED:
            raise ValueError("completed scored bundle must end in a successful attempt")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"bundle_sha256"}))
        if self.bundle_sha256 != expected_hash:
            raise ValueError("scored bundle digest does not match canonical content")
        return self


class ManualScoringQueueRecord(VersionedImmutableModel):
    """Persist a terminal scoring failure for blinded manual resolution."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    transcript_sha256: str
    scoring_execution_manifest_sha256: str
    scoring_contract_sha256: str
    scoring_input: ConditionBlindScoringInput
    attempts: List[ScoringExecutionAttempt] = Field(min_length=1)
    queued_at: datetime
    reason: str = Field(min_length=1)
    record_sha256: str

    @field_validator("transcript_sha256", "scoring_execution_manifest_sha256", "scoring_contract_sha256", "record_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        """Validate the queue-record digest format."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_queue_record(self) -> "ManualScoringQueueRecord":
        """Require only failed attempts and an exact self-hash."""
        if any(attempt.status != ScoringAttemptStatus.FAILED for attempt in self.attempts):
            raise ValueError("manual queue records may contain only failed attempts")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected_hash:
            raise ValueError("manual queue record digest does not match canonical content")
        return self


class ManualScoringResolution(VersionedImmutableModel):
    """Turn one terminal blinded scoring escalation into validated manual results."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    transcript_sha256: str
    scoring_execution_manifest_sha256: str
    scoring_contract_sha256: str
    queue_record_sha256: str
    scoring_input: ConditionBlindScoringInput
    fact_result: FactAssessmentResult
    response_result: ResponseCommunicationResult
    claim_result: ClaimAssessmentResult
    metrics: List[ConversationMetrics] = Field(min_length=2, max_length=2)
    annotation_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    researcher_id: str = Field(min_length=1)
    rubric_sha256: str
    resolved_at: datetime
    resolution_sha256: str

    @field_validator(
        "transcript_sha256",
        "scoring_execution_manifest_sha256",
        "scoring_contract_sha256",
        "queue_record_sha256",
        "rubric_sha256",
        "resolution_sha256",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate every bound artifact digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_resolution(self) -> "ManualScoringResolution":
        """Require aligned manual outputs, both checkpoints, and an exact self-hash."""
        blind_ids = {
            self.scoring_input.blind_conversation_id,
            self.fact_result.blind_conversation_id,
            self.response_result.blind_conversation_id,
            self.claim_result.blind_conversation_id,
        }
        if len(blind_ids) != 1:
            raise ValueError("manual scoring resolution components must share one blind conversation id")
        if {metric.checkpoint for metric in self.metrics} != set(EvaluationCheckpoint):
            raise ValueError("manual scoring resolution requires initial and cumulative metrics")
        if any(metric.run_unit_id != self.run_unit_id for metric in self.metrics):
            raise ValueError("manual scoring resolution metrics must share the run-unit id")
        manual_judge_id = f"manual:{self.researcher_id}"
        if (
            self.fact_result.judge_model_id != manual_judge_id
            or self.response_result.judge_model_id != manual_judge_id
            or self.claim_result.judge_model_id != manual_judge_id
        ):
            raise ValueError("manual scoring results must identify the resolving researcher")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"resolution_sha256"}))
        if self.resolution_sha256 != expected_hash:
            raise ValueError("manual scoring resolution digest does not match canonical content")
        return self


class MissingRunRecord(ImmutableModel):
    """Describe one preregistered run unit missing after provider retries."""

    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_R[1-4]$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    model_id: str = Field(min_length=1)
    source_order: SourceOrderVariant
    cell_id: str = Field(pattern=r"^WB_(AMPLE|TIGHT)__CUE_(NEUTRAL|WORRIED)__INT_(ABSENT|TARGETED)$")
    failure_reason: FailureReason
    transcript_sha256: str
    terminal_attempt_count: int = Field(ge=1)

    @field_validator("transcript_sha256")
    @classmethod
    def validate_transcript_hash(cls, value: str) -> str:
        """Validate the failed transcript digest."""
        return validate_sha256(value)


class AnalysisMissingnessReport(VersionedImmutableModel):
    """Bind the full 480-unit execution ledger to its analyzable subset."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    expected_run_count: int = Field(default=480, ge=1)
    completed_run_count: int = Field(ge=0)
    failed_run_count: int = Field(ge=0)
    manually_resolved_count: int = Field(ge=0)
    automated_scored_count: int = Field(ge=0)
    analysis_row_count: int = Field(ge=0)
    missing_runs: List[MissingRunRecord]
    transcript_ledger_sha256: str
    analysis_input_sha256: str
    fact_analysis_input_sha256: str
    generated_at: datetime
    report_sha256: str

    @field_validator("transcript_ledger_sha256", "analysis_input_sha256", "fact_analysis_input_sha256", "report_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate input, output, and self digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_counts(self) -> "AnalysisMissingnessReport":
        """Require a complete terminal ledger and exact score/missing counts."""
        if self.completed_run_count + self.failed_run_count != self.expected_run_count:
            raise ValueError("completed and failed run counts must cover the full preregistered execution ledger")
        if self.automated_scored_count + self.manually_resolved_count != self.completed_run_count:
            raise ValueError("every completed conversation must have automated or manual scoring")
        if self.analysis_row_count != self.completed_run_count * len(EvaluationCheckpoint):
            raise ValueError("analysis row count must provide both checkpoints for every completed conversation")
        if len(self.missing_runs) != self.failed_run_count or len({record.run_unit_id for record in self.missing_runs}) != len(self.missing_runs):
            raise ValueError("missing-run records must identify every failed run exactly once")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("analysis missingness report digest does not match canonical content")
        return self


class AnalysisInputRow(VersionedImmutableModel):
    """Join immutable conditions to scored outcomes only after blind scoring finishes."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_R[1-4]$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    model_id: str = Field(min_length=1)
    source_order: SourceOrderVariant
    word_budget: WordBudgetCondition
    emotional_cue: EmotionalCueCondition
    integrity: IntegrityCondition
    metrics: ConversationMetrics
    transcript_sha256: str
    scoring_result_sha256: str

    @field_validator("transcript_sha256", "scoring_result_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate joined transcript and scoring digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_join(self) -> "AnalysisInputRow":
        """Require condition identifiers and metrics to share one immutable run unit."""
        if self.use_case_id != self.scenario_id.split("_")[0]:
            raise ValueError("analysis use_case_id must match scenario_id")
        if self.metrics.run_unit_id != self.run_unit_id:
            raise ValueError("analysis metrics must match the joined run-unit id")
        return self


class FactAnalysisInputRow(VersionedImmutableModel):
    """Expose one material-fact disclosure state for ordinal robustness analysis."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_R[1-4]$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    fact_id: str = Field(min_length=1)
    fact_valence: FactValence
    checkpoint: EvaluationCheckpoint
    disclosure_ordinal: int = Field(ge=0, le=2)
    model_id: str = Field(min_length=1)
    source_order: SourceOrderVariant
    word_budget: WordBudgetCondition
    emotional_cue: EmotionalCueCondition
    integrity: IntegrityCondition
    transcript_sha256: str
    scoring_result_sha256: str

    @field_validator("transcript_sha256", "scoring_result_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate the joined transcript and scoring digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_ids(self) -> "FactAnalysisInputRow":
        """Require scenario, use-case, and fact identifiers to align."""
        if self.use_case_id != self.scenario_id.split("_")[0] or not self.fact_id.startswith(f"{self.scenario_id}_F"):
            raise ValueError("fact-analysis identifiers do not share one scenario/use case")
        return self


class AnalysisSummary(VersionedImmutableModel):
    """Store schema-validated Python or R analysis output and convergence state."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    analysis_id: str = Field(min_length=1)
    engine: AnalysisEngine
    method: str = Field(min_length=1)
    estimands: Dict[str, Decimal]
    confidence_intervals: Dict[str, List[Decimal]]
    raw_p_values: Dict[str, Decimal] = Field(default_factory=dict)
    adjusted_p_values: Dict[str, Decimal]
    converged: bool
    convergence_messages: List[str]
    source_data_sha256: str
    generated_at: datetime

    @field_validator("source_data_sha256")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        """Validate the analysis-input digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_summary_values(self) -> "AnalysisSummary":
        """Reject non-finite statistics, malformed intervals, and hidden convergence failures."""
        numeric_values = [
            *self.estimands.values(),
            *self.raw_p_values.values(),
            *self.adjusted_p_values.values(),
            *[value for interval in self.confidence_intervals.values() for value in interval],
        ]
        if any(not value.is_finite() for value in numeric_values):
            raise ValueError("analysis summary statistics must be finite")
        if any(len(interval) != 2 or interval[0] > interval[1] for interval in self.confidence_intervals.values()):
            raise ValueError("analysis confidence intervals require ordered lower/upper bounds")
        if any(value < 0 or value > 1 for value in [*self.raw_p_values.values(), *self.adjusted_p_values.values()]):
            raise ValueError("analysis p-values must lie in [0, 1]")
        if self.converged == bool(self.convergence_messages):
            raise ValueError("convergence messages must be present if and only if analysis did not converge")
        return self


class ScoringValidationReport(VersionedImmutableModel):
    """Persist hard validation gates and blinded dispositions for failed constructs."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    intra_rater_disclosure_weighted_kappa: Decimal = Field(ge=-1, le=1)
    judge_reference_disclosure_weighted_kappa: Decimal = Field(ge=-1, le=1)
    omission_recall: Decimal = Field(ge=0, le=1)
    false_claim_precision: Decimal = Field(ge=0, le=1)
    false_claim_recall: Decimal = Field(ge=0, le=1)
    framing_kappa: Optional[Decimal] = Field(default=None, ge=-1, le=1)
    reassurance_kappa: Optional[Decimal] = Field(default=None, ge=-1, le=1)
    framing_used_in_headline: bool
    reassurance_used_in_headline: bool
    passed_constructs: List[str]
    failed_constructs: List[str]
    failed_construct_actions: Dict[str, FailedConstructAction]
    validation_sample_manifest_sha256: str
    generated_at: datetime
    report_sha256: str

    @field_validator("validation_sample_manifest_sha256", "report_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        """Validate the locked validation-sample digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_failed_dispositions(self) -> "ScoringValidationReport":
        """Recompute every hard gate and require a blinded action for each failure."""
        gates = {
            "intra_rater_disclosure": self.intra_rater_disclosure_weighted_kappa >= Decimal("0.75"),
            "judge_reference_disclosure": self.judge_reference_disclosure_weighted_kappa >= Decimal("0.70"),
            "omission_recall": self.omission_recall >= Decimal("0.85"),
            "false_claim_precision": self.false_claim_precision >= Decimal("0.80"),
            "false_claim_recall": self.false_claim_recall >= Decimal("0.80"),
        }
        if self.framing_used_in_headline:
            gates["framing"] = self.framing_kappa is not None and self.framing_kappa >= Decimal("0.60")
        if self.reassurance_used_in_headline:
            gates["reassurance"] = self.reassurance_kappa is not None and self.reassurance_kappa >= Decimal("0.60")
        expected_passed = {name for name, passed in gates.items() if passed}
        expected_failed = set(gates) - expected_passed
        if set(self.passed_constructs) != expected_passed or set(self.failed_constructs) != expected_failed:
            raise ValueError("scoring validation passed/failed constructs must match the preregistered thresholds")
        if set(self.failed_construct_actions) != set(self.failed_constructs):
            raise ValueError("every failed scoring construct requires exactly one blinded disposition")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected_hash:
            raise ValueError("scoring validation report digest does not match canonical content")
        return self
