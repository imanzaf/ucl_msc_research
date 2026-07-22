"""Strict V0.5.1 seed, generated-scenario, and accepted-artifact models."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, validate_sha256
from src.data_models.experiments import ProviderCallProvenance
from src.data_models.study import SourceOrderVariant
from src.scenarios.word_count import count_words

SCENARIO_ID_PATTERN = re.compile(r"^CF\d{3}_(C1|R[1-4])$")
USE_CASE_ID_PATTERN = re.compile(r"^CF\d{3}$")


class PairSlot(str, Enum):
    """Identify one of the two matched material-fact pairs."""

    P1 = "P1"
    P2 = "P2"


class ScenarioStage(str, Enum):
    """Identify calibration versus held-out evaluation scenarios."""

    CALIBRATION = "calibration"
    EVALUATION = "evaluation"


class FactValence(str, Enum):
    """Identify material-fact valence without encoding it in visible sources."""

    ADVERSE = "adverse"
    FAVOURABLE = "favourable"


class SpecificityElementType(str, Enum):
    """Identify a typed decision-relevant specificity element."""

    AMOUNT = "amount"
    PERCENTAGE = "percentage"
    DATE = "date"
    DURATION = "duration"
    THRESHOLD = "threshold"
    CONDITION = "condition"
    EXCEPTION = "exception"
    COMPARISON = "comparison"


class NumericOperation(str, Enum):
    """Identify deterministic arithmetic supported by the numeric engine."""

    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    PERCENTAGE_CHANGE = "percentage_change"
    ANNUALISED_TOTAL = "annualised_total"


class TaskContextSeed(ImmutableModel):
    """Represent researcher-owned task context from the immutable seed."""

    evidence_basis: str = Field(min_length=1)
    authority_limits: str = Field(min_length=1)
    response_genre: str = Field(min_length=1)
    task_archetype: str = Field(min_length=1)
    reference_format: str = Field(min_length=1)
    customer_goal: str = Field(min_length=1)
    core_initial_request: str = Field(min_length=1)
    decision_context: str = Field(min_length=1)


class MaterialFactPairBriefSeed(ImmutableModel):
    """Represent one researcher-owned adverse/favourable pair brief."""

    pair_slot: PairSlot
    adverse_theme: str = Field(min_length=1)
    favorable_theme: str = Field(min_length=1)
    matching_requirements: str = Field(min_length=1)


class ReplicationSeed(ImmutableModel):
    """Represent one calibration or held-out scenario brief."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    variation_brief: str = Field(min_length=1)


class UseCaseSeed(ImmutableModel):
    """Represent one V0.5.1 use case while excluding its unused legacy extension."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    segment: str = Field(min_length=1)
    customer_journey: str = Field(min_length=1)
    agent_role: str = Field(min_length=1)
    model_owner: str = Field(min_length=1)
    user_role: str = Field(min_length=1)
    agent_task: str = Field(min_length=1)
    task_context: TaskContextSeed
    material_fact_pair_briefs: List[MaterialFactPairBriefSeed] = Field(min_length=2, max_length=2)
    legacy_seed_extension: Dict[str, Any] = Field(alias="potential_harm_pathway", exclude=True)
    replications: List[ReplicationSeed] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_structure(self) -> "UseCaseSeed":
        """Require exact pair slots and C1/R1–R4 identifiers for this use case."""
        if {brief.pair_slot for brief in self.material_fact_pair_briefs} != {PairSlot.P1, PairSlot.P2}:
            raise ValueError("material_fact_pair_briefs must contain exactly P1 and P2")
        expected_ids = {f"{self.use_case_id}_C1", *{f"{self.use_case_id}_R{index}" for index in range(1, 5)}}
        actual_ids = {replication.scenario_id for replication in self.replications}
        if actual_ids != expected_ids:
            raise ValueError("replications must contain C1 and R1-R4 for the use case")
        return self


class ScenarioSeedSet(VersionedImmutableModel):
    """Represent the complete immutable V0.5.1 seed document."""

    schema_version: str = Field(pattern=r"^0\.5\.1$")
    scenario_set_id: str = Field(pattern=r"^customer_finance_pressure_emotion_v0\.5\.1$")
    use_cases: List[UseCaseSeed] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_all_use_cases(self) -> "ScenarioSeedSet":
        """Require the exact CF001–CF010 set and fifty globally unique scenarios."""
        expected_use_case_ids = {f"CF{index:03d}" for index in range(1, 11)}
        actual_use_case_ids = {use_case.use_case_id for use_case in self.use_cases}
        if actual_use_case_ids != expected_use_case_ids:
            raise ValueError("use_cases must contain exactly CF001-CF010")
        scenario_ids = [replication.scenario_id for use_case in self.use_cases for replication in use_case.replications]
        if len(scenario_ids) != 50 or len(set(scenario_ids)) != 50:
            raise ValueError("seed must contain exactly 50 unique scenario ids")
        return self


class ArtifactProvenance(ImmutableModel):
    """Record who or what created a structured artifact and from which inputs."""

    created_at: datetime
    created_by: str = Field(min_length=1)
    generator_model_id: Optional[str] = Field(default=None, min_length=1)
    generator_prompt_sha256: Optional[str] = None
    parent_sha256: Optional[str] = None
    provider_calls: List[ProviderCallProvenance] = Field(default_factory=list)

    @field_validator("generator_prompt_sha256", "parent_sha256")
    @classmethod
    def validate_optional_hashes(cls, value: Optional[str]) -> Optional[str]:
        """Validate optional provenance hashes."""
        return validate_sha256(value) if value is not None else value

    @model_validator(mode="after")
    def validate_provider_calls(self) -> "ArtifactProvenance":
        """Require provider metadata whenever an OpenRouter generator created the artifact."""
        if self.created_by.startswith("openrouter_") and not self.provider_calls:
            raise ValueError("OpenRouter-created scenario artifacts require provider-call provenance")
        if self.generator_model_id is not None and any(call.requested_model_id != self.generator_model_id for call in self.provider_calls):
            raise ValueError("scenario provider calls must use the declared generator model id")
        return self


class NumericInput(ImmutableModel):
    """Represent one typed input to deterministic arithmetic."""

    value_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    value: Decimal
    unit: str = Field(min_length=1)
    source_note: str = Field(min_length=1)


class NumericCalculation(ImmutableModel):
    """Define one deterministic calculation over registered values."""

    output_value_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    operation: NumericOperation
    operand_value_ids: List[str] = Field(min_length=1)
    decimal_places: int = Field(default=2, ge=0, le=8)
    expected_unit: str = Field(min_length=1)


class ComputedNumericValue(ImmutableModel):
    """Store a deterministic result and its dependency identifiers."""

    value_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    value: Decimal
    unit: str = Field(min_length=1)
    calculation: NumericCalculation


class NumericRegistry(VersionedImmutableModel):
    """Collect raw and computed numeric values for one scenario."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    inputs: List[NumericInput]
    calculations: List[NumericCalculation]
    computed_values: List[ComputedNumericValue]

    @model_validator(mode="after")
    def validate_unique_identifiers(self) -> "NumericRegistry":
        """Require unique value identifiers across inputs and computed outputs."""
        value_ids = [value.value_id for value in self.inputs] + [value.value_id for value in self.computed_values]
        if len(value_ids) != len(set(value_ids)):
            raise ValueError("numeric registry value ids must be unique")
        return self


class SourceItem(ImmutableModel):
    """Represent one stable item in the evaluated model's visible packet."""

    source_item_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    header: str = Field(min_length=1)
    body: str = Field(min_length=1)
    numeric_value_ids: List[str] = Field(default_factory=list)


class SourceItemPair(ImmutableModel):
    """Identify one adverse/favourable source-item pair for a later order study."""

    adverse_source_item_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    favourable_source_item_id: str = Field(pattern=r"^[A-Z0-9_]+$")


class SourceOrderPlan(VersionedImmutableModel):
    """Store hidden metadata needed to derive a secondary source-order variant later."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    material_item_pairs: List[SourceItemPair] = Field(min_length=2, max_length=2)
    neutral_source_item_ids: List[str] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_unique_identifiers(self) -> "SourceOrderPlan":
        """Require two disjoint material pairs and two distinct neutral items."""
        material_ids = [item_id for pair in self.material_item_pairs for item_id in (pair.adverse_source_item_id, pair.favourable_source_item_id)]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("source-order material item pairs must be disjoint")
        if len(set(self.neutral_source_item_ids)) != 2:
            raise ValueError("source-order plan requires two distinct neutral items")
        if set(material_ids) & set(self.neutral_source_item_ids):
            raise ValueError("source-order material and neutral items must be disjoint")
        return self


class SourcePacket(VersionedImmutableModel):
    """Represent one deterministic source-order rendering."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    source_order: SourceOrderVariant
    fixed_title: str = Field(min_length=1)
    items: List[SourceItem] = Field(min_length=6)
    rendered_text: str = Field(min_length=1)
    rendered_sha256: str

    @field_validator("rendered_sha256")
    @classmethod
    def validate_rendered_hash(cls, value: str) -> str:
        """Validate the recorded source rendering digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_rendering(self) -> "SourcePacket":
        """Rebuild the fixed rendering and require unique item IDs and exact bytes."""
        item_ids = [item.source_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("source packet item ids must be unique")
        expected_text = "\n\n".join([f"# {self.fixed_title}", *[f"## {item.header}\n{item.body}" for item in self.items]])
        if self.rendered_text != expected_text:
            raise ValueError("source packet rendered_text does not match its title/items")
        if self.rendered_sha256 != sha256_bytes(expected_text.encode("utf-8")):
            raise ValueError("source packet rendered_sha256 does not match rendered_text")
        return self


class EvidenceSpan(ImmutableModel):
    """Locate an exact support span within one rendered source item."""

    source_item_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    exact_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_span_length(self) -> "EvidenceSpan":
        """Require character bounds to match the exact evidence text length."""
        if self.end_char <= self.start_char:
            raise ValueError("evidence span end must follow start")
        if self.end_char - self.start_char != len(self.exact_text):
            raise ValueError("evidence span bounds must equal exact_text length")
        return self


class SpecificityElement(ImmutableModel):
    """Represent one essential or optional fact detail with equivalence rules."""

    element_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    element_type: SpecificityElementType
    canonical_value: str = Field(min_length=1)
    unit: Optional[str] = Field(default=None, min_length=1)
    currency: Optional[str] = Field(default=None, min_length=1)
    numeric_tolerance: Optional[Decimal] = Field(default=None, ge=0)
    acceptable_paraphrases: List[str] = Field(default_factory=list)
    essential: bool


class MaterialFact(ImmutableModel):
    """Represent one equally required decision-material fact."""

    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_P[12]$")
    valence: FactValence
    canonical_proposition: str = Field(min_length=1)
    materiality_rationale: str = Field(min_length=1)
    required_in_complete_response: bool
    materiality_rating: int = Field(ge=1, le=4)
    source_support: List[EvidenceSpan] = Field(min_length=1)
    specificity_elements: List[SpecificityElement]

    @model_validator(mode="after")
    def validate_materiality(self) -> "MaterialFact":
        """Enforce the protocol's equal required-status and materiality threshold."""
        if not self.required_in_complete_response:
            raise ValueError("every material fact must be required in a complete response")
        if self.materiality_rating < 3:
            raise ValueError("every material fact must have materiality rating at least 3")
        return self


class NeutralFact(ImmutableModel):
    """Represent one lower-priority source-supported neutral fact."""

    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_N[1-2]$")
    canonical_proposition: str = Field(min_length=1)
    neutral_status_rationale: str = Field(min_length=1)
    source_support: List[EvidenceSpan] = Field(min_length=1)


class FactPair(ImmutableModel):
    """Represent one matched adverse/favourable comparison pair."""

    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_P[12]$")
    adverse_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    favourable_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    matching_rationale: str = Field(min_length=1)
    pair_balance_score: Decimal = Field(ge=0)


class MinimalCompleteResponse(VersionedImmutableModel):
    """Store the approved facts-only feasibility response and frozen word count."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    text: str = Field(min_length=1)
    word_count: int = Field(gt=0)
    covered_fact_ids: List[str] = Field(min_length=4, max_length=4)
    covered_specificity_element_ids: List[str]
    approved: bool
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = Field(default=None, min_length=1)
    text_sha256: str

    @field_validator("text_sha256")
    @classmethod
    def validate_text_hash(cls, value: str) -> str:
        """Validate the minimal-response text digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_approval_provenance(self) -> "MinimalCompleteResponse":
        """Require exact text metadata and researcher provenance only after approval."""
        if self.word_count != count_words(self.text):
            raise ValueError("minimal response word_count does not match frozen counter")
        if self.text_sha256 != sha256_bytes(self.text.encode("utf-8")):
            raise ValueError("minimal response text_sha256 does not match text")
        if self.approved and (self.approved_at is None or self.approved_by is None):
            raise ValueError("approved minimal response requires researcher and timestamp")
        if not self.approved and (self.approved_at is not None or self.approved_by is not None):
            raise ValueError("draft minimal response cannot claim approval provenance")
        return self


class CandidateScenario(VersionedImmutableModel):
    """Represent the rebuilt scenario candidate before researcher acceptance."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    agent_role: str = Field(min_length=1)
    model_owner: str = Field(min_length=1)
    agent_task: str = Field(min_length=1)
    task_context: TaskContextSeed
    source_order_a: SourcePacket
    source_order_plan: SourceOrderPlan
    numeric_registry: NumericRegistry
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    neutral_facts: List[NeutralFact] = Field(min_length=2, max_length=2)
    fact_pairs: List[FactPair] = Field(min_length=2, max_length=2)
    minimal_complete_response: MinimalCompleteResponse
    provenance: ArtifactProvenance
    candidate_sha256: str

    @field_validator("candidate_sha256")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        """Validate the candidate artifact digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_candidate_structure(self) -> "CandidateScenario":
        """Enforce scenario identity, source equivalence, and exact fact design."""
        _validate_scenario_content(self)
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected_hash:
            raise ValueError("candidate_sha256 does not match canonical candidate content")
        return self


class AcceptedScenario(VersionedImmutableModel):
    """Represent the only scenario artifact accepted by evaluation loaders."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    agent_role: str = Field(min_length=1)
    model_owner: str = Field(min_length=1)
    agent_task: str = Field(min_length=1)
    task_context: TaskContextSeed
    source_order_a: SourcePacket
    source_order_plan: SourceOrderPlan
    numeric_registry: NumericRegistry
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    neutral_facts: List[NeutralFact] = Field(min_length=2, max_length=2)
    fact_pairs: List[FactPair] = Field(min_length=2, max_length=2)
    minimal_complete_response: MinimalCompleteResponse
    review_history_sha256: str
    acceptance_record_sha256: str
    accepted_at: datetime
    accepted_by: str = Field(min_length=1)
    artifact_sha256: str

    @field_validator("review_history_sha256", "acceptance_record_sha256", "artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: str) -> str:
        """Validate accepted-artifact provenance hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_complete_scenario(self) -> "AcceptedScenario":
        """Enforce fact counts, pair coverage, source equivalence, and identifier alignment."""
        _validate_scenario_content(self)
        fact_ids = {fact.fact_id for fact in self.material_facts}
        if not self.minimal_complete_response.approved or set(self.minimal_complete_response.covered_fact_ids) != fact_ids:
            raise ValueError("minimal complete response must be approved and cover all four material facts")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("artifact_sha256 does not match canonical accepted content")
        return self


def _validate_scenario_content(scenario: Union[CandidateScenario, AcceptedScenario]) -> None:
    """Validate cross-field scenario identity, evidence, pairing, and feasibility coverage."""
    if scenario.use_case_id != scenario.scenario_id.split("_")[0]:
        raise ValueError("scenario use_case_id must match scenario_id")
    expected_stage = infer_scenario_stage(scenario.scenario_id)
    if scenario.study_stage != expected_stage:
        raise ValueError("scenario stage must be derived from scenario_id")
    if scenario.source_order_a.scenario_id != scenario.scenario_id or scenario.minimal_complete_response.scenario_id != scenario.scenario_id:
        raise ValueError("scenario components must share scenario_id")
    if scenario.source_order_a.source_order != SourceOrderVariant.A:
        raise ValueError("scenario requires canonical source order A")
    items_a = {item.source_item_id: item for item in scenario.source_order_a.items}
    planned_item_ids = {
        item_id
        for pair in scenario.source_order_plan.material_item_pairs
        for item_id in (pair.adverse_source_item_id, pair.favourable_source_item_id)
    } | set(scenario.source_order_plan.neutral_source_item_ids)
    if not planned_item_ids.issubset(items_a):
        raise ValueError("source-order plan references an unknown canonical source item")
    registered_value_ids = {value.value_id for value in scenario.numeric_registry.inputs} | {
        value.value_id for value in scenario.numeric_registry.computed_values
    }
    referenced_value_ids = {value_id for item in scenario.source_order_a.items for value_id in item.numeric_value_ids}
    if referenced_value_ids != registered_value_ids:
        raise ValueError("canonical source numeric references must exactly cover the numeric registry")
    expected_prefix = f"{scenario.scenario_id}_"
    material_ids = [fact.fact_id for fact in scenario.material_facts]
    neutral_ids = [fact.fact_id for fact in scenario.neutral_facts]
    if len(set(material_ids + neutral_ids)) != 6 or any(not fact_id.startswith(expected_prefix) for fact_id in material_ids + neutral_ids):
        raise ValueError("scenario fact ids must be unique and scenario-scoped")
    valences = [fact.valence for fact in scenario.material_facts]
    if valences.count(FactValence.ADVERSE) != 2 or valences.count(FactValence.FAVOURABLE) != 2:
        raise ValueError("scenario must contain exactly two facts per valence")
    expected_pair_ids = {f"{scenario.scenario_id}_P1", f"{scenario.scenario_id}_P2"}
    pair_by_id = {pair.pair_id: pair for pair in scenario.fact_pairs}
    if set(pair_by_id) != expected_pair_ids:
        raise ValueError("scenario must contain its exact P1 and P2 pair ids")
    fact_by_id = {fact.fact_id: fact for fact in scenario.material_facts}
    paired_fact_ids: List[str] = []
    for pair_id, pair in pair_by_id.items():
        if pair.adverse_fact_id not in fact_by_id or pair.favourable_fact_id not in fact_by_id:
            raise ValueError("fact pair references an unknown material fact")
        adverse = fact_by_id[pair.adverse_fact_id]
        favourable = fact_by_id[pair.favourable_fact_id]
        if adverse.valence != FactValence.ADVERSE or favourable.valence != FactValence.FAVOURABLE:
            raise ValueError("fact pair adverse/favourable references have the wrong valence")
        if adverse.pair_id != pair_id or favourable.pair_id != pair_id:
            raise ValueError("material fact pair_id does not match the pair manifest")
        if abs(adverse.materiality_rating - favourable.materiality_rating) > 1:
            raise ValueError("within-pair materiality ratings may differ by at most one point")
        paired_fact_ids.extend([adverse.fact_id, favourable.fact_id])
    if len(paired_fact_ids) != len(set(paired_fact_ids)) or set(paired_fact_ids) != set(material_ids):
        raise ValueError("fact pairs must cover every material fact exactly once")
    support_lists = [fact.source_support for fact in scenario.material_facts] + [fact.source_support for fact in scenario.neutral_facts]
    for source_support in support_lists:
        for span in source_support:
            if span.source_item_id not in items_a:
                raise ValueError("fact evidence references an unknown source item")
            body = items_a[span.source_item_id].body
            if span.end_char > len(body) or body[span.start_char : span.end_char] != span.exact_text:
                raise ValueError("fact evidence span does not match exact source text")
    required_specificity_ids = {element.element_id for fact in scenario.material_facts for element in fact.specificity_elements if element.essential}
    if set(scenario.minimal_complete_response.covered_fact_ids) != set(material_ids):
        raise ValueError("minimal complete response must cover every material fact")
    if not required_specificity_ids.issubset(scenario.minimal_complete_response.covered_specificity_element_ids):
        raise ValueError("minimal complete response must cover every essential specificity element")


def infer_scenario_stage(scenario_id: str) -> ScenarioStage:
    """Derive calibration or evaluation stage from a validated scenario identifier."""
    if SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
        raise ValueError(f"invalid V0.5.1 scenario id: {scenario_id}")
    return ScenarioStage.CALIBRATION if scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
