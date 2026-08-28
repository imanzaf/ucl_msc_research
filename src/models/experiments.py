"""Experiment-cell, provider, and generic run-unit models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import Field, TypeAdapter, field_validator, model_validator

from src.common import ImmutableModel
from src.models.enums import (
    Affect,
    CommercialInterestInstruction,
    CommercialInterestTask,
    ExactFactBudget,
    ExperimentKind,
    LicenceCategory,
    ModelAccess,
    NaturalWordBudget,
    OwnershipRole,
    QueryLength,
)


class GenerationControls(ImmutableModel):
    """Freeze every effective model-native generation parameter."""

    max_output_tokens: int = Field(gt=0)
    temperature: Optional[float] = Field(default=None, ge=0)
    seed: Optional[int] = None
    reasoning_effort: Optional[str] = None
    extra_parameters: dict[str, object] = Field(default_factory=dict)


class ProviderSnapshot(ImmutableModel):
    """Bind a run to one frozen model, gateway, and routing-policy snapshot."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    model_slug: str = Field(min_length=3)
    returned_model_version: Optional[str] = None
    model_access: ModelAccess
    licence_category: LicenceCategory
    total_parameters: Optional[str] = None
    active_parameters: Optional[str] = None
    provider_name: str = Field(min_length=1)
    provider_endpoint: str = Field(min_length=1)
    routing_policy: str = Field(min_length=1)
    metadata_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_passed: bool = False


class UserStateCell(ImmutableModel):
    """Define one affect and naturally authored query-length treatment cell."""

    kind: Literal[ExperimentKind.USER_STATE] = ExperimentKind.USER_STATE
    affect: Affect
    query_length: QueryLength


class InformationBudgetCell(ImmutableModel):
    """Define one exact fact-count treatment cell."""

    kind: Literal[ExperimentKind.INFORMATION_BUDGET] = ExperimentKind.INFORMATION_BUDGET
    affect: Literal[Affect.NEUTRAL, Affect.ANXIOUS]
    exact_fact_budget: ExactFactBudget

    @model_validator(mode="after")
    def validate_active_cells(self) -> "InformationBudgetCell":
        """Exclude the unplanned anxious six-fact cell."""
        if self.affect == Affect.ANXIOUS and self.exact_fact_budget == 6:
            raise ValueError("anxious information-budget cells use k=2 or k=4 only")
        return self


class WordBudgetCell(ImmutableModel):
    """Define one neutral natural-language word-budget cell."""

    kind: Literal[ExperimentKind.WORD_BUDGET] = ExperimentKind.WORD_BUDGET
    word_budget: NaturalWordBudget


class SingleFactCell(ImmutableModel):
    """Define the natural single-most-important-fact task."""

    kind: Literal[ExperimentKind.SINGLE_FACT] = ExperimentKind.SINGLE_FACT


class OwnershipCell(ImmutableModel):
    """Define one ownership role and jointly counterbalanced rendering."""

    kind: Literal[ExperimentKind.OWNERSHIP] = ExperimentKind.OWNERSHIP
    ownership_role: OwnershipRole
    rendering: Literal[1, 2]


class OptionFirstCell(ImmutableModel):
    """Define the one-response option-choice task."""

    kind: Literal[ExperimentKind.OPTION_FIRST] = ExperimentKind.OPTION_FIRST


class CommercialInterestCell(ImmutableModel):
    """Cross one commercial-interest condition with an approved task and affect."""

    kind: Literal[ExperimentKind.COMMERCIAL_INTEREST] = ExperimentKind.COMMERCIAL_INTEREST
    affect: Affect
    instruction: CommercialInterestInstruction
    task: CommercialInterestTask
    word_budget: Literal[NaturalWordBudget.WORDS_160] = NaturalWordBudget.WORDS_160
    exact_fact_budget: Optional[Literal[ExactFactBudget.FACTS_2, ExactFactBudget.FACTS_4]] = None
    ownership_role: Optional[Literal[OwnershipRole.EMPLOYER_OWNS_A, OwnershipRole.EMPLOYER_OWNS_B]] = None
    rendering: Optional[Literal[1, 2]] = None

    @model_validator(mode="after")
    def validate_task_coordinates(self) -> "CommercialInterestCell":
        """Require exact-budget or ownership coordinates only for their matching task."""
        if self.task == CommercialInterestTask.EXACT_BUDGET:
            if self.exact_fact_budget is None or self.ownership_role is not None or self.rendering is not None:
                raise ValueError("commercial exact-budget cells require only k=2 or k=4")
            return self
        if self.task == CommercialInterestTask.OWNERSHIP_FLIP:
            if self.exact_fact_budget is not None or self.ownership_role is None or self.rendering is None:
                raise ValueError("commercial ownership cells require one employer role and rendering")
            return self
        if self.exact_fact_budget is not None or self.ownership_role is not None or self.rendering is not None:
            raise ValueError("commercial standard and single-fact cells have no extra coordinates")
        return self


ExperimentCell = Annotated[
    Union[
        UserStateCell,
        InformationBudgetCell,
        WordBudgetCell,
        SingleFactCell,
        OwnershipCell,
        OptionFirstCell,
        CommercialInterestCell,
    ],
    Field(discriminator="kind"),
]
EXPERIMENT_CELL_ADAPTER: TypeAdapter[ExperimentCell] = TypeAdapter(ExperimentCell)


class ResponseContract(ImmutableModel):
    """Freeze the response format and semantic non-adherence policy."""

    contract_name: str = Field(min_length=2)
    contract_version: str = Field(min_length=1)
    structured: bool
    exact_fact_budget: Optional[int] = Field(default=None, ge=1)
    word_budget: Optional[int] = Field(default=None, ge=1)
    malformed_output_is_non_adherence: bool = True


class AttemptMetadata(ImmutableModel):
    """Record one provider attempt without silently replacing semantic output."""

    attempt_number: int = Field(ge=1)
    started_at: datetime
    completed_at: Optional[datetime] = None
    provider_request_id: Optional[str] = None
    transport_failure: bool = False
    semantic_response_received: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class ResponseMetadata(ImmutableModel):
    """Record immutable response text, adherence, token, cost, and truncation metadata."""

    raw_response: str
    returned_model_version: Optional[str] = None
    provider_name: Optional[str] = None
    selected_fact_ids: Optional[List[str]] = None
    answer_text: Optional[str] = None
    structurally_valid: bool
    adherent: bool
    finish_reason: Optional[str] = None
    truncated: bool = False
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    billed_cost: Optional[Decimal] = Field(default=None, ge=0)
    received_at: datetime


class RunUnit(ImmutableModel):
    """Bind one experiment treatment, prompt, model snapshot, and response record."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    run_unit_id: str = Field(min_length=16)
    experiment: ExperimentKind
    cell: ExperimentCell
    scenario_id: str = Field(min_length=3)
    query_variant_id: str = Field(min_length=3)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: ProviderSnapshot
    generation_controls: GenerationControls
    response: Optional[ResponseMetadata] = None
    attempts: List[AttemptMetadata] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_binding(self) -> "RunUnit":
        """Require the run experiment to agree with the discriminated treatment cell."""
        if self.cell.kind != self.experiment:
            raise ValueError("run-unit experiment does not match treatment-cell kind")
        return self

    @field_validator("attempts")
    @classmethod
    def validate_transport_only_retries(cls, attempts: List[AttemptMetadata]) -> List[AttemptMetadata]:
        """Reject a retry after an attempt produced any semantic response."""
        for attempt in attempts[:-1]:
            if attempt.semantic_response_received or not attempt.transport_failure:
                raise ValueError("only transport/provider failures without semantic output may be retried")
        return attempts


class UsageTotals(ImmutableModel):
    """Aggregate response counts, native token usage, and billed provider cost."""

    response_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    billed_cost: Decimal = Field(ge=0)
    missing_token_records: int = Field(ge=0)
    missing_cost_records: int = Field(ge=0)


class BatchExecutionSummary(ImmutableModel):
    """Record resumable evaluated-run completion and auditable usage totals."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    protocol_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_response_count: int = Field(ge=0)
    completed_response_count: int = Field(ge=0)
    remaining_response_count: int = Field(ge=0)
    totals: UsageTotals
    by_model: Dict[str, UsageTotals]
    by_experiment: Dict[str, UsageTotals]
    generated_at: datetime
