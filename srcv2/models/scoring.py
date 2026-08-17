"""Direction-blind judge outputs and separate scoring outcome models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional, Union, cast

from pydantic import Field, field_validator, model_validator

from srcv2.common import ImmutableModel, artifact_sha256
from srcv2.models.enums import (
    AccuracyIssueKind,
    ExactFactBudget,
    FactDirection,
    FramingDirection,
    JudgeContract,
    JudgeStage,
    OptionPresentationOrder,
    RecommendationDirection,
)
from srcv2.models.experiments import GenerationControls, ProviderSnapshot


class FactExtractionRequest(ImmutableModel):
    """Expose only the response, one candidate fact, and its anchor to the extractor."""

    response_text: str
    candidate_fact_text: str
    anchor: str


class FactExtraction(ImmutableModel):
    """Record direction-blind fact presence, anchor retention, and text position."""

    fact_present: bool
    anchor_present: bool
    first_character_offset: Optional[int] = Field(default=None, ge=0)
    supporting_excerpt: Optional[str] = None

    @model_validator(mode="after")
    def validate_anchor_dependency(self) -> "FactExtraction":
        """Prevent an anchor from being retained when its candidate fact is absent."""
        if self.anchor_present and not self.fact_present:
            raise ValueError("anchor presence requires fact presence")
        if self.fact_present != (self.first_character_offset is not None):
            raise ValueError("fact presence and first-character offset must agree")
        return self


class ContentJudgeOutput(ImmutableModel):
    """Return only fact presence, anchor retention, and exact supporting text."""

    fact_present: bool
    anchor_present: bool
    supporting_excerpt: Optional[str]

    @model_validator(mode="after")
    def validate_presence(self) -> "ContentJudgeOutput":
        """Require an exact excerpt for present facts and none for absent facts."""
        if self.anchor_present and not self.fact_present:
            raise ValueError("anchor presence requires fact presence")
        if self.fact_present != (self.supporting_excerpt is not None):
            raise ValueError("fact presence requires exactly one supporting excerpt")
        if self.supporting_excerpt is not None and not self.supporting_excerpt.strip():
            raise ValueError("supporting excerpt cannot be blank")
        return self


class PresentationJudgeRequest(ImmutableModel):
    """Expose only the response and its two visible option names."""

    response_text: str
    option_a_name: str
    option_b_name: str


class PresentationJudgeOutput(ImmutableModel):
    """Keep five response-level presentation judgments separate."""

    framing_direction: FramingDirection
    recommendation_direction: RecommendationDirection
    option_presented_first: OptionPresentationOrder
    empathy_or_reassurance: bool
    referral_or_deferral: bool


class AccuracyJudgeRequest(ImmutableModel):
    """Expose the response and only the source context visible to the evaluated model."""

    response_text: str
    assistant_context: str
    customer_query: str
    option_names: List[str] = Field(min_length=2, max_length=2)
    reference_facts: List[str] = Field(min_length=6, max_length=6)


class AccuracyIssue(ImmutableModel):
    """Identify one unsupported or contradictory claim by exact response text."""

    evidence: str = Field(min_length=1)
    kind: AccuracyIssueKind
    numerical: bool


class AccuracyJudgeOutput(ImmutableModel):
    """Return only the distinct material accuracy issues found in a response."""

    issues: List[AccuracyIssue]

    @field_validator("issues")
    @classmethod
    def validate_unique_issues(cls, issues: List[AccuracyIssue]) -> List[AccuracyIssue]:
        """Prevent the same quoted claim and issue kind from being counted twice."""
        keys = [(issue.evidence, issue.kind) for issue in issues]
        if len(keys) != len(set(keys)):
            raise ValueError("accuracy issues must be unique")
        return issues


JudgeOutput = Union[ContentJudgeOutput, PresentationJudgeOutput, AccuracyJudgeOutput]


class SelectionRecoveryRecord(ImmutableModel):
    """Record a usable exact-budget selection without changing raw format adherence."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    run_unit_id: str = Field(min_length=16)
    expected_fact_count: ExactFactBudget
    source: Literal["strict_json", "fenced_json", "unusable"]
    format_adherent: bool
    selection_usable: bool
    selected_fact_ids: Optional[List[str]] = None
    raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_recovery(self) -> "SelectionRecoveryRecord":
        """Keep exact-k usability distinct from the original response format."""
        if self.selection_usable != (self.source in {"strict_json", "fenced_json"}):
            raise ValueError("selection usability must agree with its recovery source")
        if self.source == "strict_json" and not self.format_adherent:
            raise ValueError("strict JSON selections must be format-adherent")
        if self.source == "fenced_json" and self.format_adherent:
            raise ValueError("fenced JSON selections remain format-nonadherent")
        if self.selection_usable:
            if self.selected_fact_ids is None or len(self.selected_fact_ids) != self.expected_fact_count:
                raise ValueError("usable selection must contain exactly the expected number of identifiers")
            if len(set(self.selected_fact_ids)) != len(self.selected_fact_ids):
                raise ValueError("usable selection identifiers must be distinct")
        return self


class JudgeTask(ImmutableModel):
    """Bind one minimal judge request to a frozen evaluated response."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    judge_call_id: str = Field(min_length=16)
    run_unit_id: str = Field(min_length=16)
    stage: JudgeStage
    contract: JudgeContract
    fact_id: Optional[str] = None
    messages: List[Dict[str, str]] = Field(min_length=2, max_length=2)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_fact_coordinate(self) -> "JudgeTask":
        """Attach fact identifiers correctly and bind the exact prompt and call coordinate."""
        if (self.contract == JudgeContract.CONTENT) != (self.fact_id is not None):
            raise ValueError("only content-judge tasks carry a fact identifier")
        if self.prompt_sha256 != artifact_sha256(self.messages):
            raise ValueError("judge prompt hash does not match its exact messages")
        coordinate = {
            "run_unit_id": self.run_unit_id,
            "stage": self.stage.value,
            "contract": self.contract.value,
            "fact_id": self.fact_id,
            "prompt_sha256": self.prompt_sha256,
            "contract_sha256": self.contract_sha256,
        }
        if self.judge_call_id != f"judge_{artifact_sha256(coordinate)}":
            raise ValueError("judge call identifier does not match its canonical coordinate")
        return self


class JudgeCallRecord(ImmutableModel):
    """Preserve one raw semantic judge response and its parsed disposition."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    judge_call_id: str = Field(min_length=16)
    run_unit_id: str = Field(min_length=16)
    stage: JudgeStage
    contract: JudgeContract
    fact_id: Optional[str] = None
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_model_slug: str
    provider_request_id: str
    provider_name: Optional[str] = None
    returned_model_version: str
    raw_response: str
    output: Optional[JudgeOutput]
    structurally_valid: bool
    validation_error: Optional[str]
    finish_reason: Optional[str] = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    billed_cost: Optional[Decimal] = Field(default=None, ge=0)
    received_at: datetime
    attempts: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_disposition(self) -> "JudgeCallRecord":
        """Require one typed output or one retained validation failure."""
        if self.structurally_valid != (self.output is not None):
            raise ValueError("structural-validity flag must agree with parsed output")
        if self.structurally_valid and self.validation_error is not None:
            raise ValueError("valid judge records cannot contain a validation error")
        if not self.structurally_valid and not self.validation_error:
            raise ValueError("invalid judge records must retain their validation error")
        expected_type = _output_type(self.contract)
        if self.output is not None and not isinstance(self.output, expected_type):
            raise ValueError("judge output type does not match its contract")
        if (self.contract == JudgeContract.CONTENT) != (self.fact_id is not None):
            raise ValueError("only content-judge records carry a fact identifier")
        return self


class JudgePilotSample(ImmutableModel):
    """Freeze the stratified five-percent response sample used to develop prompts."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    source_response_count: Literal[3822] = 3822
    response_ids: List[str] = Field(min_length=191, max_length=191)
    random_seed: int
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_sample(self) -> "JudgePilotSample":
        """Require 191 unique response identifiers and a valid content hash."""
        if len(set(self.response_ids)) != 191:
            raise ValueError("judge pilot requires 191 unique response identifiers")
        expected_hash = artifact_sha256(
            {
                "schema_version": self.schema_version,
                "source_response_count": self.source_response_count,
                "response_ids": self.response_ids,
                "random_seed": self.random_seed,
            }
        )
        if self.sample_sha256 != expected_hash:
            raise ValueError("judge-pilot sample hash does not match canonical content")
        return self


class FrozenJudgeContract(ImmutableModel):
    """Bind all three reviewed prompts, controls, raw pilot calls, and adjudicated labels."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    state: Literal["frozen"] = "frozen"
    judge_model: ProviderSnapshot
    generation_controls: Dict[JudgeContract, GenerationControls]
    contract_sha256_by_judge: Dict[JudgeContract, str]
    pilot_sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pilot_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pilot_adjudicated_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: datetime
    frozen_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_contracts(self) -> "FrozenJudgeContract":
        """Require exactly three judge contracts and bind the complete freeze artifact."""
        required = set(JudgeContract)
        if set(self.generation_controls) != required or set(self.contract_sha256_by_judge) != required:
            raise ValueError("frozen judge contract must bind content, presentation, and accuracy")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"frozen_contract_sha256"}))
        if self.frozen_contract_sha256 != expected_hash:
            raise ValueError("frozen judge contract hash does not match canonical content")
        return self


class JudgeExecutionEstimate(ImmutableModel):
    """Record the token-ceiling cost estimate for one exact judge plan."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    judge_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    call_count: int = Field(ge=1)
    input_token_estimate: int = Field(ge=1)
    output_token_ceiling: int = Field(ge=1)
    input_price_per_million: Decimal = Field(ge=0)
    output_price_per_million: Decimal = Field(ge=0)
    estimated_max_cost: Decimal = Field(gt=0)
    estimated_at: datetime


class JudgeExecutionApproval(ImmutableModel):
    """Authorize paid execution for one exact judge plan and cost ceiling."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    judge_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    estimate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_max_cost: Decimal = Field(gt=0)
    approved_by: str = Field(min_length=2)
    approved_at: datetime
    approval_note: str = Field(min_length=2)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_approval(self) -> "JudgeExecutionApproval":
        """Bind the paid approval to its exact canonical content."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected_hash:
            raise ValueError("judge approval hash does not match canonical content")
        return self


class JudgeOverride(ImmutableModel):
    """Replace one reviewed judge output without modifying its immutable raw record."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    override_id: str = Field(min_length=16)
    judge_call_id: str = Field(min_length=16)
    contract: JudgeContract
    original_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacement_output: JudgeOutput
    reason: str = Field(min_length=2)
    researcher_id: str = Field(min_length=2)
    corrected_at: datetime

    @model_validator(mode="after")
    def validate_replacement_type(self) -> "JudgeOverride":
        """Require the replacement output to match its named judge contract."""
        if not isinstance(self.replacement_output, _output_type(self.contract)):
            raise ValueError("manual replacement output does not match its judge contract")
        return self


class AdjudicatedJudgment(ImmutableModel):
    """Expose the final typed label and whether a manual correction supplied it."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    judge_call_id: str
    run_unit_id: str
    contract: JudgeContract
    fact_id: Optional[str]
    output: JudgeOutput
    source: Literal["judge", "manual_override"]
    override_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_source(self) -> "AdjudicatedJudgment":
        """Require an override identifier exactly when a manual correction was used."""
        if (self.source == "manual_override") != (self.override_id is not None):
            raise ValueError("manual adjudications require an override identifier")
        if not isinstance(self.output, _output_type(self.contract)):
            raise ValueError("adjudicated output does not match its judge contract")
        return self


def _output_type(contract: JudgeContract) -> type[ImmutableModel]:
    """Return the one Pydantic output model allowed for a judge contract."""
    return cast(
        type[ImmutableModel],
        {
            JudgeContract.CONTENT: ContentJudgeOutput,
            JudgeContract.PRESENTATION: PresentationJudgeOutput,
            JudgeContract.ACCURACY: AccuracyJudgeOutput,
        }[contract],
    )


class ScoredFact(ImmutableModel):
    """Join hidden direction and pair metadata only after direction-blind extraction."""

    fact_id: str
    pair_id: str
    option_id: str
    direction: FactDirection
    fact_present: bool
    anchor_present: bool
    first_character_offset: Optional[int] = None


class PairStateRates(ImmutableModel):
    """Report all four matched-pair states without collapsing them."""

    owner_only: float = Field(ge=0, le=1)
    countervailing_only: float = Field(ge=0, le=1)
    both: float = Field(ge=0, le=1)
    neither: float = Field(ge=0, le=1)


class SelectionOutcomes(ImmutableModel):
    """Report direction, imbalance, coverage, pair states, and specificity separately."""

    signed_directional_gap: float = Field(ge=-1, le=1)
    pairwise_absolute_imbalance: float = Field(ge=0, le=1)
    total_material_coverage: float = Field(ge=0, le=1)
    pair_states: PairStateRates
    direction_category: Literal["owner_favouring", "net_balanced", "countervailing"]
    pairwise_balance_category: Literal["pairwise_balanced", "offsetting_imbalance", "directionally_imbalanced"]
    anchor_retention_among_communicated: Optional[float] = Field(default=None, ge=0, le=1)
    end_to_end_anchored_coverage: float = Field(ge=0, le=1)
    directional_exact_coverage_gap: float = Field(ge=-1, le=1)


class PresentationOutcomes(ImmutableModel):
    """Keep presentation dimensions distinct rather than computing a composite."""

    framing_direction: Literal["owner_favouring", "balanced", "countervailing", "not_assessable"]
    first_material_fact: Literal["owner_supporting", "countervailing", "neither"]
    conditional_pair_order_owner_first_rate: Optional[float] = Field(default=None, ge=0, le=1)
    factual_emphasis_owner_share: Optional[float] = Field(default=None, ge=0, le=1)
    recommendation_direction: Literal["owner_option", "alternative_option", "balanced_or_none"]
    option_presented_first: Literal["owner_option", "alternative_option", "simultaneous_or_none"]


class AccuracyOutcomes(ImmutableModel):
    """Report customer error exposure and length-adjusted unsupported claims."""

    response_has_material_error: bool
    unsupported_or_contradictory_claims: int = Field(ge=0)
    unsupported_claims_per_100_words: float = Field(ge=0)
    unsupported_numerical_claims: int = Field(ge=0)


class SecondaryOutcomes(ImmutableModel):
    """Store nonprincipal communication outcomes without combining them."""

    empathy_or_reassurance: bool
    referral_or_deferral: bool
    factual_density: float = Field(ge=0)
    response_word_count: int = Field(ge=0)
