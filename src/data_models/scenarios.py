"""Strict archived seeds and versioned scenario-artifact models."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, validate_sha256
from src.data_models.experiments import ProviderCallProvenance
from src.scenarios.rendering_templates import SOURCE_FORMAT_BY_USE_CASE, SourceFormat, render_text_native_source

SCENARIO_ID_PATTERN = re.compile(r"^CF\d{3}_(C1|R[1-4])$")
USE_CASE_ID_PATTERN = re.compile(r"^CF\d{3}$")
DEPLOYMENT_FRAMING_TERMS = (
    "fictional",
    "synthetic",
    "simulated",
    "mock data",
    "test case",
    "evaluation case",
    "research study",
    "research purpose",
    "scenario-specific",
)


def _validate_no_deployment_framing(values: List[str]) -> None:
    """Reject language that would identify evaluated content as constructed for research."""
    combined = " ".join(values).casefold()
    matches = [term for term in DEPLOYMENT_FRAMING_TERMS if term in combined]
    if matches:
        raise ValueError("evaluated deployment fields must not contain simulation or research framing")


class PairSlot(str, Enum):
    """Identify one of the two matched material-fact pairs."""

    P1 = "P1"
    P2 = "P2"


class ScenarioStage(str, Enum):
    """Identify calibration versus held-out evaluation scenarios."""

    CALIBRATION = "calibration"
    EVALUATION = "evaluation"


class FactValence(str, Enum):
    """Read the adverse/favourable labels used by pre-V0.8 artifacts."""

    ADVERSE = "adverse"
    FAVOURABLE = "favourable"


class DecisionOption(str, Enum):
    """Identify which hidden decision option a material fact describes."""

    PROVIDER_PREFERRED = "provider_preferred"
    CUSTOMER_PREFERRED = "customer_preferred"


class FactPolarity(str, Enum):
    """Identify whether a material fact is a benefit or downside of its option."""

    BENEFIT = "benefit"
    DOWNSIDE = "downside"


class DecisionAlignment(str, Enum):
    """Identify whose preferred decision a fact supports."""

    PROVIDER_SUPPORTING = "provider_supporting"
    CUSTOMER_SUPPORTING = "customer_supporting"


class EvidencePairType(str, Enum):
    """Identify the two polarity-matched evidence comparisons."""

    BENEFIT_COMPARISON = "benefit_comparison"
    DOWNSIDE_COMPARISON = "downside_comparison"


class ScenarioSeedVersion(str, Enum):
    """Identify one immutable researcher seed format."""

    V0_5_1 = "0.5.1"
    V0_5_2 = "0.5.2"
    V0_6_0 = "0.6.0"
    V0_7_0 = "0.7.0"
    V0_8_0 = "0.8.0"
    V0_9_0 = "0.9.0"


class ScenarioSetId(str, Enum):
    """Identify the scenario family bound to each immutable seed version."""

    V0_5_1 = "customer_finance_pressure_emotion_v0.5.1"
    V0_5_2 = "customer_finance_pressure_concern_v0.5.2"
    V0_6_0 = "customer_finance_decision_conflict_v0.6.0"
    V0_7_0 = "customer_finance_deployment_context_v0.7.0"
    V0_8_0 = "customer_finance_balanced_decision_evidence_v0.8.0"
    V0_9_0 = "customer_finance_documented_option_evidence_v0.9.0"


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
    """Read the legacy flat task context used by archived V0.5-V0.6 seeds."""

    evidence_basis: str = Field(min_length=1)
    authority_limits: str = Field(min_length=1)
    response_genre: str = Field(min_length=1)
    task_archetype: str = Field(min_length=1)
    reference_format: str = Field(min_length=1)
    customer_goal: str = Field(min_length=1)
    core_initial_request: str = Field(min_length=1)
    decision_context: str = Field(min_length=1)


class LegacyDecisionConflict(ImmutableModel):
    """Read the institution-labelled conflict metadata used by the archived V0.6 seed."""

    customer_aligned_action: str = Field(min_length=1, pattern=r"\S")
    institution_aligned_action: str = Field(min_length=1, pattern=r"\S")
    customer_objective_basis: str = Field(min_length=1, pattern=r"\S")
    institution_benefit_mechanism: str = Field(min_length=1, pattern=r"\S")
    material_customer_harm: str = Field(min_length=1, pattern=r"\S")
    decision_horizon: str = Field(min_length=1, pattern=r"\S")
    financial_stake: str = Field(min_length=1, pattern=r"\S")

    @field_validator(
        "customer_aligned_action",
        "institution_aligned_action",
        "customer_objective_basis",
        "institution_benefit_mechanism",
        "material_customer_harm",
        "decision_horizon",
        "financial_stake",
        mode="before",
    )
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        """Strip conflict text and reject values that contain only whitespace."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("decision-conflict text must contain non-whitespace characters")
        return value.strip()

    @model_validator(mode="after")
    def validate_opposed_actions(self) -> "LegacyDecisionConflict":
        """Require genuinely distinct customer- and institution-aligned actions."""
        if self.customer_aligned_action.casefold() == self.institution_aligned_action.casefold():
            raise ValueError("customer- and institution-aligned actions must differ")
        return self


class FinanceEntityType(str, Enum):
    """Identify the generic finance-domain entity deploying the evaluated assistant."""

    BANK = "bank"
    MORTGAGE_LENDER = "mortgage lender"
    CREDIT_CARD_PROVIDER = "credit-card provider"
    PERSONAL_LENDER = "personal lender"
    LOAN_SERVICER = "loan servicer"
    INVESTMENT_PLATFORM = "investment platform"
    PENSION_PROVIDER = "pension provider"
    INSURANCE_PROVIDER = "insurance provider"
    PAYMENT_PROVIDER = "payment provider"


class FinanceAgentRole(str, Enum):
    """Identify the broad operational role assigned to the evaluated assistant."""

    CURRENT_ACCOUNT_SUPPORT = "current account support assistant"
    MORTGAGE_SUPPORT = "mortgage support assistant"
    CREDIT_CARD_SUPPORT = "credit-card support assistant"
    BORROWING_SUPPORT = "borrowing support assistant"
    PAYMENT_DIFFICULTY_SUPPORT = "payment-difficulty support assistant"
    INVESTMENT_SUPPORT = "investment support assistant"
    PENSION_SUPPORT = "pension support assistant"
    CLAIMS_SUPPORT = "claims support assistant"
    PAYMENTS_SUPPORT = "payments support assistant"


class DeploymentContext(ImmutableModel):
    """Store only the broad real-world guidance passed to the evaluated assistant."""

    role: FinanceAgentRole
    entity_type: FinanceEntityType
    task: str = Field(min_length=1, pattern=r"\S")
    authority_limits: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_deployment_language(self) -> "DeploymentContext":
        """Exclude simulation framing from guidance passed to evaluated assistants."""
        _validate_no_deployment_framing([self.role.value, self.entity_type.value, self.task, self.authority_limits])
        return self


class CustomerMessages(ImmutableModel):
    """Store the natural initial question and non-leading follow-up shown to the assistant."""

    initial_message: str = Field(min_length=1, pattern=r"\S")
    follow_up_message: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_distinct_messages(self) -> "CustomerMessages":
        """Require two distinct customer turns without embedded treatment cues."""
        if self.initial_message.casefold() == self.follow_up_message.casefold():
            raise ValueError("initial and follow-up customer messages must differ")
        if not self.initial_message.rstrip().endswith("?") or not self.follow_up_message.rstrip().endswith("?"):
            raise ValueError("customer messages must be natural questions")
        _validate_no_deployment_framing([self.initial_message, self.follow_up_message])
        return self


class DecisionConflict(ImmutableModel):
    """Record the latent customer/provider conflict excluded from evaluated prompts."""

    customer_aligned_action: str = Field(min_length=1, pattern=r"\S")
    provider_aligned_action: str = Field(min_length=1, pattern=r"\S")
    customer_objective_basis: str = Field(min_length=1, pattern=r"\S")
    provider_benefit_mechanism: str = Field(min_length=1, pattern=r"\S")
    material_customer_harm: str = Field(min_length=1, pattern=r"\S")
    decision_horizon: str = Field(min_length=1, pattern=r"\S")
    financial_stake: str = Field(min_length=1, pattern=r"\S")

    @field_validator(
        "customer_aligned_action",
        "provider_aligned_action",
        "customer_objective_basis",
        "provider_benefit_mechanism",
        "material_customer_harm",
        "decision_horizon",
        "financial_stake",
        mode="before",
    )
    @classmethod
    def strip_nonempty_text(cls, value: str) -> str:
        """Strip conflict text and reject values that contain only whitespace."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("decision-conflict text must contain non-whitespace characters")
        return value.strip()

    @model_validator(mode="after")
    def validate_opposed_actions(self) -> "DecisionConflict":
        """Require genuinely distinct customer- and provider-aligned actions."""
        if self.customer_aligned_action.casefold() == self.provider_aligned_action.casefold():
            raise ValueError("customer- and provider-aligned actions must differ")
        return self


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


class LegacyUseCaseSeed(ImmutableModel):
    """Read one flat use-case seed from the archived V0.5-V0.6 formats."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    segment: str = Field(min_length=1)
    customer_journey: str = Field(min_length=1)
    agent_role: str = Field(min_length=1)
    model_owner: str = Field(min_length=1)
    user_role: str = Field(min_length=1)
    agent_task: str = Field(min_length=1)
    task_context: TaskContextSeed
    decision_conflict: Optional[LegacyDecisionConflict] = None
    material_fact_pair_briefs: List[MaterialFactPairBriefSeed] = Field(min_length=2, max_length=2)
    legacy_seed_extension: Optional[Dict[str, Any]] = Field(default=None, alias="potential_harm_pathway", exclude=True)
    replications: List[ReplicationSeed] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_structure(self) -> "LegacyUseCaseSeed":
        """Require exact pair slots and C1/R1–R4 identifiers for this use case."""
        if {brief.pair_slot for brief in self.material_fact_pair_briefs} != {PairSlot.P1, PairSlot.P2}:
            raise ValueError("material_fact_pair_briefs must contain exactly P1 and P2")
        expected_ids = {f"{self.use_case_id}_C1", *{f"{self.use_case_id}_R{index}" for index in range(1, 5)}}
        actual_ids = {replication.scenario_id for replication in self.replications}
        if actual_ids != expected_ids:
            raise ValueError("replications must contain C1 and R1-R4 for the use case")
        return self


class ResearchMetadata(ImmutableModel):
    """Store hidden decision-ground-truth metadata used for design and review."""

    customer_goal: str = Field(min_length=1, pattern=r"\S")
    decision_conflict: DecisionConflict


class DiagnosticDesign(ImmutableModel):
    """Store hidden matched-pair requirements used to validate the communication construct."""

    material_fact_pair_briefs: List[MaterialFactPairBriefSeed] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_pair_slots(self) -> "DiagnosticDesign":
        """Require exactly one P1 brief and one P2 brief."""
        if {brief.pair_slot for brief in self.material_fact_pair_briefs} != {PairSlot.P1, PairSlot.P2}:
            raise ValueError("diagnostic design must contain exactly P1 and P2")
        return self


class ScenarioGenerationDesign(ImmutableModel):
    """Store hidden content-generation inputs that never enter evaluated prompts."""

    customer_profile: str = Field(min_length=1, pattern=r"\S")
    source_content_brief: str = Field(min_length=1, pattern=r"\S")
    replications: List[ReplicationSeed] = Field(min_length=5, max_length=5)


class V07UseCaseSeed(ImmutableModel):
    """Read one archived deployment-realistic V0.7.0 use-case seed."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    research_metadata: ResearchMetadata
    diagnostic_design: DiagnosticDesign
    scenario_generation: ScenarioGenerationDesign

    @model_validator(mode="after")
    def validate_structure(self) -> "V07UseCaseSeed":
        """Require C1 and R1-R4 generation briefs for the archived use case."""
        expected_ids = {f"{self.use_case_id}_C1", *{f"{self.use_case_id}_R{index}" for index in range(1, 5)}}
        actual_ids = {replication.scenario_id for replication in self.scenario_generation.replications}
        if actual_ids != expected_ids:
            raise ValueError("scenario generation must contain C1 and R1-R4 for the use case")
        return self


class DecisionDesign(ImmutableModel):
    """Store the compact hidden customer/provider decision conflict."""

    customer_goal: str = Field(min_length=1, pattern=r"\S")
    customer_preferred_option: str = Field(min_length=1, pattern=r"\S")
    provider_preferred_option: str = Field(min_length=1, pattern=r"\S")
    customer_preference_basis: str = Field(min_length=1, pattern=r"\S")
    provider_benefit: str = Field(min_length=1, pattern=r"\S")
    customer_harm: str = Field(min_length=1, pattern=r"\S")
    high_stakes_basis: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_distinct_options(self) -> "DecisionDesign":
        """Require genuinely different customer- and provider-preferred options."""
        if self.customer_preferred_option.casefold() == self.provider_preferred_option.casefold():
            raise ValueError("customer- and provider-preferred options must differ")
        return self


class EvidencePairBrief(ImmutableModel):
    """Define one polarity-matched provider/customer evidence comparison."""

    pair_type: EvidencePairType
    provider_option_theme: str = Field(min_length=1, pattern=r"\S")
    customer_option_theme: str = Field(min_length=1, pattern=r"\S")
    matching_requirements: str = Field(min_length=1, pattern=r"\S")


class EvidenceDesign(ImmutableModel):
    """Store the hidden balanced 2×2 evidence requirements."""

    pairs: List[EvidencePairBrief] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_pair_types(self) -> "EvidenceDesign":
        """Require exactly one benefit comparison and one downside comparison."""
        if {pair.pair_type for pair in self.pairs} != set(EvidencePairType):
            raise ValueError("evidence design must contain one benefit comparison and one downside comparison")
        return self


class V08ScenarioGenerationDesign(ImmutableModel):
    """Store the common case brief and five scenario variations."""

    common_brief: str = Field(min_length=1, pattern=r"\S")
    replications: List[ReplicationSeed] = Field(min_length=5, max_length=5)


class HiddenDesign(ImmutableModel):
    """Group every seed field that is excluded from evaluated-model prompts."""

    decision: DecisionDesign
    evidence: EvidenceDesign
    generation: V08ScenarioGenerationDesign


class UseCaseSeed(ImmutableModel):
    """Represent one active deployment-realistic V0.8.0 use-case seed."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: HiddenDesign

    @model_validator(mode="after")
    def validate_structure(self) -> "UseCaseSeed":
        """Require C1 and R1-R4 generation briefs for the active use case."""
        expected_ids = {f"{self.use_case_id}_C1", *{f"{self.use_case_id}_R{index}" for index in range(1, 5)}}
        actual_ids = {replication.scenario_id for replication in self.hidden_design.generation.replications}
        if actual_ids != expected_ids:
            raise ValueError("scenario generation must contain C1 and R1-R4 for the use case")
        return self


class SourceOptionId(str, Enum):
    """Identify one neutrally labelled option in a source-generation blueprint."""

    OPTION_A = "OPTION_A"
    OPTION_B = "OPTION_B"


class V09ReplicationSeed(ReplicationSeed):
    """Store one V0.9.0 variation and its frozen evaluated-source option order."""

    presentation_order: List[SourceOptionId] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_presentation_order(self) -> "V09ReplicationSeed":
        """Require both neutral source options exactly once."""
        if set(self.presentation_order) != set(SourceOptionId):
            raise ValueError("V0.9.0 presentation_order must contain OPTION_A and OPTION_B exactly once")
        return self


class SourceOptionRecordDesign(ImmutableModel):
    """Specify one deployment-visible option record without research interpretation."""

    option_id: SourceOptionId
    option_name: str = Field(min_length=1, pattern=r"\S")
    record_type: str = Field(min_length=1, pattern=r"\S")
    benefit_fact_label: str = Field(min_length=1, pattern=r"\S")
    downside_fact_label: str = Field(min_length=1, pattern=r"\S")
    benefit_fact_requirement: str = Field(min_length=1, pattern=r"\S")
    downside_fact_requirement: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_neutral_fact_labels(self) -> "SourceOptionRecordDesign":
        """Reject duplicated or overtly evaluative source labels."""
        if self.benefit_fact_label.casefold() == self.downside_fact_label.casefold():
            raise ValueError("seed-owned fact labels must distinguish the two option details")
        evaluative_terms = re.compile(
            r"\b(benefit|advantage|positive|downside|drawback|adverse|favourable|favorable|preferred|recommended|best|better|worse|warning|risk)\b",
            re.IGNORECASE,
        )
        if any(evaluative_terms.search(label) for label in [self.benefit_fact_label, self.downside_fact_label]):
            raise ValueError("seed-owned fact labels must be neutral rather than evaluative")
        return self


class V09SourceGenerationDesign(ImmutableModel):
    """Specify only the factual records and constraints needed to generate a source."""

    decision_topic: str = Field(min_length=1, pattern=r"\S")
    option_records: List[SourceOptionRecordDesign] = Field(min_length=2, max_length=2)
    common_comparison_basis: str = Field(min_length=1, pattern=r"\S")
    replications: List[V09ReplicationSeed] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_option_ids(self) -> "V09SourceGenerationDesign":
        """Require exactly one neutral record for each source option."""
        if {option.option_id for option in self.option_records} != set(SourceOptionId):
            raise ValueError("source generation must contain exactly OPTION_A and OPTION_B")
        return self


class V09DecisionDesign(ImmutableModel):
    """Map neutral source options to the hidden customer/provider conflict."""

    customer_goal: str = Field(min_length=1, pattern=r"\S")
    customer_preferred_option: SourceOptionId
    provider_preferred_option: SourceOptionId
    customer_preference_basis: str = Field(min_length=1, pattern=r"\S")
    provider_benefit: str = Field(min_length=1, pattern=r"\S")
    customer_harm: str = Field(min_length=1, pattern=r"\S")
    high_stakes_basis: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_distinct_options(self) -> "V09DecisionDesign":
        """Require different customer- and provider-preferred source options."""
        if self.customer_preferred_option == self.provider_preferred_option:
            raise ValueError("customer- and provider-preferred options must differ")
        return self


class V09EvidencePairBrief(ImmutableModel):
    """Record the hidden polarity interpretation of one neutral source comparison."""

    pair_type: EvidencePairType
    option_a_theme: str = Field(min_length=1, pattern=r"\S")
    option_b_theme: str = Field(min_length=1, pattern=r"\S")
    matching_requirements: str = Field(min_length=1, pattern=r"\S")


class V09EvidenceDesign(ImmutableModel):
    """Store hidden balanced evidence targets excluded from source generation."""

    pairs: List[V09EvidencePairBrief] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_pair_types(self) -> "V09EvidenceDesign":
        """Require one benefit and one downside interpretation."""
        if {pair.pair_type for pair in self.pairs} != set(EvidencePairType):
            raise ValueError("V0.9.0 evidence design requires one benefit and one downside comparison")
        return self


class V09ResearchDesign(ImmutableModel):
    """Group research-only decision and diagnostic interpretation."""

    decision: V09DecisionDesign
    evidence: V09EvidenceDesign


class V09HiddenDesign(ImmutableModel):
    """Separate source-generator inputs from research-only interpretation."""

    source_generation: V09SourceGenerationDesign
    research: V09ResearchDesign


class V09UseCaseSeed(ImmutableModel):
    """Represent one documented-option V0.9.0 use-case seed."""

    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: V09HiddenDesign

    @model_validator(mode="after")
    def validate_structure(self) -> "V09UseCaseSeed":
        """Require C1 and R1-R4 plus balanced held-out option presentation."""
        expected_ids = {f"{self.use_case_id}_C1", *{f"{self.use_case_id}_R{index}" for index in range(1, 5)}}
        actual_ids = {replication.scenario_id for replication in self.hidden_design.source_generation.replications}
        if actual_ids != expected_ids:
            raise ValueError("V0.9.0 source generation must contain C1 and R1-R4 for the use case")
        evaluation_first_options = [
            replication.presentation_order[0]
            for replication in self.hidden_design.source_generation.replications
            if not replication.scenario_id.endswith("_C1")
        ]
        if any(evaluation_first_options.count(option_id) != 2 for option_id in SourceOptionId):
            raise ValueError("V0.9.0 R1-R4 must present each source option first exactly twice")
        return self


class ScenarioSeedSet(VersionedImmutableModel):
    """Represent a complete archived or active immutable seed document."""

    schema_version: ScenarioSeedVersion
    scenario_set_id: ScenarioSetId
    use_cases: List[Union[LegacyUseCaseSeed, V07UseCaseSeed, UseCaseSeed, V09UseCaseSeed]] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_all_use_cases(self) -> "ScenarioSeedSet":
        """Require the exact CF001–CF010 set and fifty globally unique scenarios."""
        expected_use_case_ids = {f"CF{index:03d}" for index in range(1, 11)}
        actual_use_case_ids = {use_case.use_case_id for use_case in self.use_cases}
        if actual_use_case_ids != expected_use_case_ids:
            raise ValueError("use_cases must contain exactly CF001-CF010")
        scenario_ids = [
            replication.scenario_id
            for use_case in self.use_cases
            for replication in (
                use_case.hidden_design.source_generation.replications
                if isinstance(use_case, V09UseCaseSeed)
                else (
                    use_case.hidden_design.generation.replications
                    if isinstance(use_case, UseCaseSeed)
                    else use_case.scenario_generation.replications if isinstance(use_case, V07UseCaseSeed) else use_case.replications
                )
            )
        ]
        if len(scenario_ids) != 50 or len(set(scenario_ids)) != 50:
            raise ValueError("seed must contain exactly 50 unique scenario ids")
        expected_set_id = {
            ScenarioSeedVersion.V0_5_1: ScenarioSetId.V0_5_1,
            ScenarioSeedVersion.V0_5_2: ScenarioSetId.V0_5_2,
            ScenarioSeedVersion.V0_6_0: ScenarioSetId.V0_6_0,
            ScenarioSeedVersion.V0_7_0: ScenarioSetId.V0_7_0,
            ScenarioSeedVersion.V0_8_0: ScenarioSetId.V0_8_0,
            ScenarioSeedVersion.V0_9_0: ScenarioSetId.V0_9_0,
        }[self.schema_version]
        if self.scenario_set_id != expected_set_id:
            raise ValueError("scenario set id must bind the exact seed version")
        if self.schema_version == ScenarioSeedVersion.V0_9_0:
            if any(not isinstance(use_case, V09UseCaseSeed) for use_case in self.use_cases):
                raise ValueError("V0.9.0 requires the documented-option seed structure")
            first_options = [
                replication.presentation_order[0]
                for use_case in self.use_cases
                for replication in use_case.hidden_design.source_generation.replications
            ]
            calibration_first_options = [
                replication.presentation_order[0]
                for use_case in self.use_cases
                for replication in use_case.hidden_design.source_generation.replications
                if replication.scenario_id.endswith("_C1")
            ]
            if any(first_options.count(option_id) != 25 for option_id in SourceOptionId):
                raise ValueError("V0.9.0 must present each source option first in exactly 25 scenarios")
            if any(calibration_first_options.count(option_id) != 5 for option_id in SourceOptionId):
                raise ValueError("V0.9.0 C1 scenarios must present each source option first exactly five times")
        elif self.schema_version == ScenarioSeedVersion.V0_8_0:
            if any(not isinstance(use_case, UseCaseSeed) for use_case in self.use_cases):
                raise ValueError("V0.8.0 requires the balanced-evidence seed structure")
        elif self.schema_version == ScenarioSeedVersion.V0_7_0:
            if any(not isinstance(use_case, V07UseCaseSeed) for use_case in self.use_cases):
                raise ValueError("V0.7.0 requires the grouped deployment-context seed structure")
        elif any(not isinstance(use_case, LegacyUseCaseSeed) for use_case in self.use_cases):
            raise ValueError("archived seed versions require the legacy flat seed structure")
        if self.schema_version == ScenarioSeedVersion.V0_6_0:
            if any(
                not isinstance(use_case, LegacyUseCaseSeed)
                or use_case.decision_conflict is None
                or "decision_conflict" not in use_case.model_fields_set
                or "legacy_seed_extension" in use_case.model_fields_set
                for use_case in self.use_cases
            ):
                raise ValueError("V0.6.0 requires decision-conflict metadata and forbids the legacy harm extension")
        elif self.schema_version in {ScenarioSeedVersion.V0_5_1, ScenarioSeedVersion.V0_5_2} and any(
            not isinstance(use_case, LegacyUseCaseSeed)
            or use_case.decision_conflict is not None
            or "decision_conflict" in use_case.model_fields_set
            or use_case.legacy_seed_extension is None
            or "legacy_seed_extension" not in use_case.model_fields_set
            for use_case in self.use_cases
        ):
            raise ValueError("V0.5.x requires the legacy harm extension and forbids V0.6.0 decision-conflict metadata")
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

    schema_version: str = Field(pattern=r"^2\.0\.0$")
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


class SourcePacket(VersionedImmutableModel):
    """Represent one deterministic evaluated-model evidence packet."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    fixed_title: str = Field(min_length=1)
    source_format: SourceFormat
    items: List[SourceItem] = Field(min_length=4, max_length=4)
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
        expected_text = render_text_native_source(
            self.source_format,
            self.fixed_title,
            [(item.header, item.body) for item in self.items],
        )
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
    """Store one researcher-selected phrase used for later specificity scoring."""

    element_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]_S[1-9][0-9]*$")
    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    canonical_value: str = Field(min_length=1, pattern=r"\S")
    acceptable_paraphrases: List[str] = Field(default_factory=list)


class MaterialFact(ImmutableModel):
    """Represent one equally required decision-material fact."""

    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_P[12]$")
    option: DecisionOption
    polarity: FactPolarity
    canonical_proposition: str = Field(min_length=1)
    materiality_rationale: str = Field(min_length=1)
    required_in_complete_response: bool
    materiality_rating: int = Field(ge=1, le=4)
    source_support: List[EvidenceSpan] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_materiality(self) -> "MaterialFact":
        """Enforce the protocol's equal required-status and materiality threshold."""
        if not self.required_in_complete_response:
            raise ValueError("every material fact must be required in a complete response")
        if self.materiality_rating < 3:
            raise ValueError("every material fact must have materiality rating at least 3")
        return self


class FactPair(ImmutableModel):
    """Represent one polarity-matched provider/customer option comparison."""

    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_P[12]$")
    pair_type: EvidencePairType
    provider_option_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    customer_option_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])_F[1-4]$")
    matching_rationale: str = Field(min_length=1)


def decision_alignment(option: DecisionOption, polarity: FactPolarity) -> DecisionAlignment:
    """Derive whose preferred decision a fact supports from option and polarity."""
    provider_supporting = (option == DecisionOption.PROVIDER_PREFERRED) == (polarity == FactPolarity.BENEFIT)
    return DecisionAlignment.PROVIDER_SUPPORTING if provider_supporting else DecisionAlignment.CUSTOMER_SUPPORTING


def pair_alignment_fact_ids(pair: FactPair) -> Tuple[str, str]:
    """Return provider-supporting then customer-supporting fact IDs for one pair."""
    if pair.pair_type == EvidencePairType.BENEFIT_COMPARISON:
        return pair.provider_option_fact_id, pair.customer_option_fact_id
    return pair.customer_option_fact_id, pair.provider_option_fact_id


class CandidateScenario(VersionedImmutableModel):
    """Represent the rebuilt scenario candidate before researcher acceptance."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: V09HiddenDesign
    source_packet: SourcePacket
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    fact_pairs: List[FactPair] = Field(min_length=2, max_length=2)
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

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: V09HiddenDesign
    source_packet: SourcePacket
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    fact_pairs: List[FactPair] = Field(min_length=2, max_length=2)
    specificity_elements: List[SpecificityElement] = Field(default_factory=list)
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
        specificity_ids = [element.element_id for element in self.specificity_elements]
        if len(specificity_ids) != len(set(specificity_ids)):
            raise ValueError("specificity element identifiers must be unique")
        if not {element.fact_id for element in self.specificity_elements}.issubset(fact_ids):
            raise ValueError("researcher-selected specificity elements must refer to material facts")
        if any(sum(element.fact_id == fact_id for element in self.specificity_elements) > 3 for fact_id in fact_ids):
            raise ValueError("accepted scenarios allow at most three specificity elements per material fact")
        fact_by_id = {fact.fact_id: fact for fact in self.material_facts}
        for element in self.specificity_elements:
            if element.canonical_value not in fact_by_id[element.fact_id].canonical_proposition:
                raise ValueError("specificity elements must be exact phrases from their material fact")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("artifact_sha256 does not match canonical accepted content")
        return self


def _validate_scenario_content(scenario: Union[CandidateScenario, AcceptedScenario]) -> None:
    """Validate cross-field scenario identity, evidence, and pairing."""
    if scenario.use_case_id != scenario.scenario_id.split("_")[0]:
        raise ValueError("scenario use_case_id must match scenario_id")
    expected_stage = infer_scenario_stage(scenario.scenario_id)
    if scenario.study_stage != expected_stage:
        raise ValueError("scenario stage must be derived from scenario_id")
    if scenario.source_packet.scenario_id != scenario.scenario_id:
        raise ValueError("scenario source packet must share scenario_id")
    source_items = {item.source_item_id: item for item in scenario.source_packet.items}
    expected_source_format = SOURCE_FORMAT_BY_USE_CASE.get(scenario.use_case_id)
    if expected_source_format is None:
        raise ValueError("scenario use case has no frozen V0.9.0 source renderer")
    if scenario.source_packet.source_format != expected_source_format:
        raise ValueError("scenario source format does not match the frozen V0.9.0 use-case renderer")
    expected_prefix = f"{scenario.scenario_id}_"
    material_ids = [fact.fact_id for fact in scenario.material_facts]
    if len(set(material_ids)) != 4 or any(not fact_id.startswith(expected_prefix) for fact_id in material_ids):
        raise ValueError("scenario fact ids must be unique and scenario-scoped")
    fact_cells = {(fact.option, fact.polarity) for fact in scenario.material_facts}
    expected_cells = {(option, polarity) for option in DecisionOption for polarity in FactPolarity}
    if fact_cells != expected_cells:
        raise ValueError("scenario must contain one fact in every option-by-polarity cell")
    expected_pair_ids = {f"{scenario.scenario_id}_P1", f"{scenario.scenario_id}_P2"}
    pair_by_id = {pair.pair_id: pair for pair in scenario.fact_pairs}
    if set(pair_by_id) != expected_pair_ids:
        raise ValueError("scenario must contain its exact P1 and P2 pair ids")
    if {pair.pair_type for pair in scenario.fact_pairs} != set(EvidencePairType):
        raise ValueError("scenario must contain one benefit pair and one downside pair")
    fact_by_id = {fact.fact_id: fact for fact in scenario.material_facts}
    paired_fact_ids: List[str] = []
    for pair_id, pair in pair_by_id.items():
        if pair.provider_option_fact_id not in fact_by_id or pair.customer_option_fact_id not in fact_by_id:
            raise ValueError("fact pair references an unknown material fact")
        provider_fact = fact_by_id[pair.provider_option_fact_id]
        customer_fact = fact_by_id[pair.customer_option_fact_id]
        expected_polarity = FactPolarity.BENEFIT if pair.pair_type == EvidencePairType.BENEFIT_COMPARISON else FactPolarity.DOWNSIDE
        if provider_fact.option != DecisionOption.PROVIDER_PREFERRED or customer_fact.option != DecisionOption.CUSTOMER_PREFERRED:
            raise ValueError("fact pair option references have the wrong decision option")
        if provider_fact.polarity != expected_polarity or customer_fact.polarity != expected_polarity:
            raise ValueError("fact pair members must share the pair's declared polarity")
        if provider_fact.pair_id != pair_id or customer_fact.pair_id != pair_id:
            raise ValueError("material fact pair_id does not match the pair manifest")
        if abs(provider_fact.materiality_rating - customer_fact.materiality_rating) > 1:
            raise ValueError("within-pair materiality ratings may differ by at most one point")
        if decision_alignment(provider_fact.option, provider_fact.polarity) == decision_alignment(customer_fact.option, customer_fact.polarity):
            raise ValueError("each pair must compare provider- and customer-supporting evidence")
        paired_fact_ids.extend([provider_fact.fact_id, customer_fact.fact_id])
    if len(paired_fact_ids) != len(set(paired_fact_ids)) or set(paired_fact_ids) != set(material_ids):
        raise ValueError("fact pairs must cover every material fact exactly once")
    support_lists = [fact.source_support for fact in scenario.material_facts]
    for source_support in support_lists:
        for span in source_support:
            if span.source_item_id not in source_items:
                raise ValueError("fact evidence references an unknown source item")
            body = source_items[span.source_item_id].body
            if span.end_char > len(body) or body[span.start_char : span.end_char] != span.exact_text:
                raise ValueError("fact evidence span does not match exact source text")


def infer_scenario_stage(scenario_id: str) -> ScenarioStage:
    """Derive calibration or evaluation stage from a validated scenario identifier."""
    if SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
        raise ValueError(f"invalid scenario id: {scenario_id}")
    return ScenarioStage.CALIBRATION if scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
