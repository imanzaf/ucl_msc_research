"""Strict V2.0.0 seed and option-information scenario models."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional, Tuple

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, validate_sha256
from src.data_models.experiments import ProviderCallProvenance

SCENARIO_ID_REGEX = r"^CF\d{3}_(C1|R[12])$"
SCENARIO_ID_PATTERN = re.compile(SCENARIO_ID_REGEX)
USE_CASE_ID_REGEX = r"^CF\d{3}$"
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


class ScenarioStage(str, Enum):
    """Identify calibration versus held-out evaluation scenarios."""

    CALIBRATION = "calibration"
    EVALUATION = "evaluation"


class ScenarioGenerationRunConfig(VersionedImmutableModel):
    """Record the immutable seed and protocol identity for one logical generation run."""

    schema_version: Literal["2.0.0"]
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
    seed_version: Literal["v2.0.0"]
    generation_protocol_version: Literal["v1.0.5"]
    scenario_set_id: Literal["customer_facing_risk_communication_v2.0.0"]
    seed_sha256: str
    seed_schema_sha256: str
    query_sha256: str
    query_schema_sha256: str
    created_at: datetime

    @field_validator("seed_sha256", "seed_schema_sha256", "query_sha256", "query_schema_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate the definition and query hashes captured at run creation."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_run_creation(self) -> "ScenarioGenerationRunConfig":
        """Require one timezone-aware creation timestamp for the named run."""
        if self.created_at.tzinfo is None:
            raise ValueError("run created_at must be timezone-aware")
        return self


class ScenarioGenerationInvocationConfig(VersionedImmutableModel):
    """Record one resumable command invocation within a logical generation run."""

    schema_version: Literal["1.0.0"]
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
    invocation_id: str = Field(pattern=r"^\d{8}T\d{12}Z$")
    stage: ScenarioStage
    scenario_ids: List[str] = Field(min_length=1, max_length=10)
    backend: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_invocation(self) -> "ScenarioGenerationInvocationConfig":
        """Bind the invocation timestamp and require one lifecycle stage."""
        if self.created_at.tzinfo is None or self.created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") != self.invocation_id:
            raise ValueError("invocation_id must equal the UTC created_at timestamp")
        if len(self.scenario_ids) != len(set(self.scenario_ids)):
            raise ValueError("scenario generation invocation ids must be unique")
        wrong_stage = (
            any(not scenario_id.endswith("_C1") for scenario_id in self.scenario_ids)
            if self.stage == ScenarioStage.CALIBRATION
            else any(scenario_id.endswith("_C1") for scenario_id in self.scenario_ids)
        )
        if wrong_stage:
            raise ValueError("invocation scenario ids must match the selected lifecycle stage")
        return self


class DecisionOption(str, Enum):
    """Identify which hidden decision option a material fact describes."""

    OWNER_OPTION = "owner_option"
    ALTERNATIVE_OPTION = "alternative_option"


class FactPolarity(str, Enum):
    """Identify whether a material fact is a benefit or downside of its option."""

    BENEFIT = "benefit"
    DOWNSIDE = "downside"


class DecisionAlignment(str, Enum):
    """Identify whether a fact supports or counters the model owner's preferred option."""

    OWNER_SUPPORTING = "owner_supporting"
    OWNER_COUNTERVAILING = "owner_countervailing"


class FactPairType(str, Enum):
    """Identify the two polarity-matched fact comparisons."""

    BENEFIT_COMPARISON = "benefit_comparison"
    DOWNSIDE_COMPARISON = "downside_comparison"


class SeedOptionId(str, Enum):
    """Identify one neutrally labelled option in a generation seed."""

    OPTION_A = "OPTION_A"
    OPTION_B = "OPTION_B"


def alternative_seed_option(owner_supporting_option: SeedOptionId) -> SeedOptionId:
    """Return the non-owner-supporting option in a two-option seed decision."""
    return SeedOptionId.OPTION_B if owner_supporting_option == SeedOptionId.OPTION_A else SeedOptionId.OPTION_A


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
    SAVINGS_SUPPORT = "savings support assistant"
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
    """Store natural condition-specific questions and one shared non-leading follow-up."""

    neutral_user_query: str = Field(min_length=1, pattern=r"\S")
    concerned_user_query: str = Field(min_length=1, pattern=r"\S")
    follow_up_query: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_distinct_messages(self) -> "CustomerMessages":
        """Require distinct condition queries and a generic shared follow-up."""
        queries = [self.neutral_user_query, self.concerned_user_query, self.follow_up_query]
        if len({query.casefold() for query in queries}) != 3:
            raise ValueError("neutral, concerned, and follow-up customer queries must differ")
        if any(not query.rstrip().endswith("?") for query in queries):
            raise ValueError("customer messages must be natural questions")
        _validate_no_deployment_framing(queries)
        return self


class ScenarioOptionDefinition(ImmutableModel):
    """Name one neutral decision option supplied to the fact generator."""

    option_id: SeedOptionId
    option_name: str = Field(min_length=1, pattern=r"\S")


class OptionDescription(ImmutableModel):
    """Store one neutral generated description for a seed-owned option."""

    option_id: SeedOptionId
    description: str = Field(min_length=1, max_length=400, pattern=r"\S")

    @model_validator(mode="after")
    def validate_private_identifiers_absent(self) -> "OptionDescription":
        """Keep internal seed option identifiers out of potentially visible text."""
        if any(option_id.value in self.description for option_id in SeedOptionId):
            raise ValueError("option descriptions must not contain internal option identifiers")
        return self


class ScenarioHiddenDesign(ImmutableModel):
    """Store one decision's research-only ownership mapping and display order."""

    decision_type: str = Field(min_length=1, pattern=r"\S")
    options: List[ScenarioOptionDefinition] = Field(min_length=2, max_length=2)
    owner_supporting_option: SeedOptionId
    owner_benefit_mechanism: str = Field(min_length=1, pattern=r"\S")
    presentation_order: List[SeedOptionId] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_options(self) -> "ScenarioHiddenDesign":
        """Require two distinct options, one owner preference, and a complete order."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("V2.0.0 decisions require exactly OPTION_A and OPTION_B")
        if len({option.option_name.casefold() for option in self.options}) != 2:
            raise ValueError("V2.0.0 option names must be distinct")
        if set(self.presentation_order) != set(SeedOptionId):
            raise ValueError("V2.0.0 presentation_order must contain OPTION_A and OPTION_B exactly once")
        return self


class ScenarioReplicationDefinition(ScenarioHiddenDesign):
    """Define one calibration or held-out decision without customer queries."""

    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)


class ScenarioUseCaseDefinition(ImmutableModel):
    """Represent one broad agent-task family with three distinct decisions."""

    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    deployment_context: DeploymentContext
    replications: List[ScenarioReplicationDefinition] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_structure(self) -> "ScenarioUseCaseDefinition":
        """Require exactly C1, R1, and R2 with distinct decisions."""
        expected_ids = {f"{self.use_case_id}_C1", f"{self.use_case_id}_R1", f"{self.use_case_id}_R2"}
        actual_ids = {replication.scenario_id for replication in self.replications}
        if actual_ids != expected_ids:
            raise ValueError("V2.0.0 task families must contain exactly C1, R1, and R2")
        if len({replication.decision_type.casefold() for replication in self.replications}) != 3:
            raise ValueError("each V2.0.0 task family requires three distinct decision types")
        return self


class ScenarioSeedSet(VersionedImmutableModel):
    """Represent the complete active V2.0.0 scenario-definition document."""

    schema_version: Literal["2.0.0"]
    scenario_set_id: Literal["customer_facing_risk_communication_v2.0.0"]
    use_cases: List[ScenarioUseCaseDefinition] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_all_use_cases(self) -> "ScenarioSeedSet":
        """Require exact families, scenario identifiers, and global counterbalancing."""
        expected_use_case_ids = {f"CF{index:03d}" for index in range(1, 11)}
        actual_use_case_ids = {use_case.use_case_id for use_case in self.use_cases}
        if actual_use_case_ids != expected_use_case_ids:
            raise ValueError("use_cases must contain exactly CF001-CF010")
        replications = [replication for use_case in self.use_cases for replication in use_case.replications]
        scenario_ids = [replication.scenario_id for replication in replications]
        if len(scenario_ids) != 30 or len(set(scenario_ids)) != 30:
            raise ValueError("V2.0.0 must contain exactly 30 unique scenario ids")
        first_options = [replication.presentation_order[0] for replication in replications]
        calibration_first_options = [replication.presentation_order[0] for replication in replications if replication.scenario_id.endswith("_C1")]
        owner_options = [replication.owner_supporting_option for replication in replications]
        calibration_owner_options = [replication.owner_supporting_option for replication in replications if replication.scenario_id.endswith("_C1")]
        if any(first_options.count(option_id) != 15 for option_id in SeedOptionId):
            raise ValueError("V2.0.0 must present each option first in exactly 15 scenarios")
        if any(calibration_first_options.count(option_id) != 5 for option_id in SeedOptionId):
            raise ValueError("V2.0.0 C1 scenarios must present each option first exactly five times")
        if any(owner_options.count(option_id) != 15 for option_id in SeedOptionId):
            raise ValueError("V2.0.0 must map the owner-supporting choice to each option exactly 15 times")
        if any(calibration_owner_options.count(option_id) != 5 for option_id in SeedOptionId):
            raise ValueError("V2.0.0 C1 scenarios must map the owner-supporting choice to each option exactly five times")
        return self


class ScenarioCustomerQuery(ImmutableModel):
    """Bind one scenario identifier to its natural customer messages."""

    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    customer_messages: CustomerMessages


class ScenarioFamilyQueries(ImmutableModel):
    """Group the three scenario-specific query records for one task family."""

    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    scenarios: List[ScenarioCustomerQuery] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_scenarios(self) -> "ScenarioFamilyQueries":
        """Require exact C1, R1, and R2 query records with distinct condition queries."""
        expected_ids = {f"{self.use_case_id}_C1", f"{self.use_case_id}_R1", f"{self.use_case_id}_R2"}
        if {scenario.scenario_id for scenario in self.scenarios} != expected_ids:
            raise ValueError("each V2.0.0 query family must contain exactly C1, R1, and R2")
        if len({scenario.customer_messages.neutral_user_query.casefold() for scenario in self.scenarios}) != 3:
            raise ValueError("each V2.0.0 query family requires three distinct neutral customer questions")
        if len({scenario.customer_messages.concerned_user_query.casefold() for scenario in self.scenarios}) != 3:
            raise ValueError("each V2.0.0 query family requires three distinct concerned customer questions")
        return self


class ScenarioQuerySet(VersionedImmutableModel):
    """Represent the complete active V2.0.0 customer-query document."""

    schema_version: Literal["2.0.0"]
    scenario_set_id: Literal["customer_facing_risk_communication_v2.0.0"]
    scenario_families: List[ScenarioFamilyQueries] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_query_set(self) -> "ScenarioQuerySet":
        """Require all families, all scenario IDs, and one shared follow-up."""
        expected_use_case_ids = {f"CF{index:03d}" for index in range(1, 11)}
        if {family.use_case_id for family in self.scenario_families} != expected_use_case_ids:
            raise ValueError("scenario_families must contain exactly CF001-CF010")
        scenarios = [scenario for family in self.scenario_families for scenario in family.scenarios]
        scenario_ids = [scenario.scenario_id for scenario in scenarios]
        if len(scenario_ids) != 30 or len(set(scenario_ids)) != 30:
            raise ValueError("V2.0.0 queries must contain exactly 30 unique scenario ids")
        if len({scenario.customer_messages.follow_up_query for scenario in scenarios}) != 1:
            raise ValueError("V2.0.0 scenarios must share one exact follow-up query")
        return self


class ScenarioReplicationSeed(ScenarioReplicationDefinition):
    """Combine one scenario definition with its separately stored customer messages."""

    customer_messages: CustomerMessages


class ScenarioUseCaseSeed(ImmutableModel):
    """Combine one task-family definition with its scenario-specific query records."""

    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    deployment_context: DeploymentContext
    replications: List[ScenarioReplicationSeed] = Field(min_length=3, max_length=3)


class LoadedScenarioSeedSet(ImmutableModel):
    """Expose the validated and exactly joined active scenario inputs."""

    use_cases: List[ScenarioUseCaseSeed] = Field(min_length=10, max_length=10)


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


class SpecificityElement(ImmutableModel):
    """Store one exact quantitative phrase used for later specificity scoring."""

    element_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]_S[1-9][0-9]*$")
    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    canonical_value: str = Field(min_length=1, pattern=r"\S")
    acceptable_paraphrases: List[str] = Field(default_factory=list)

    @field_validator("canonical_value")
    @classmethod
    def validate_quantitative_value(cls, value: str) -> str:
        """Require every specificity marker to contain an explicit number."""
        if not any(character.isdigit() for character in value):
            raise ValueError("specificity markers must contain an explicit number")
        return value


class MaterialFact(ImmutableModel):
    """Represent one equally required decision-material fact."""

    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_P[12]$")
    option: DecisionOption
    polarity: FactPolarity
    canonical_proposition: str = Field(min_length=1)
    materiality_rationale: str = Field(min_length=1)
    required_in_complete_response: bool
    materiality_rating: int = Field(ge=1, le=4)

    @model_validator(mode="after")
    def validate_materiality(self) -> "MaterialFact":
        """Enforce the protocol's equal required-status and materiality threshold."""
        if not self.required_in_complete_response:
            raise ValueError("every material fact must be required in a complete response")
        if self.materiality_rating < 3:
            raise ValueError("every material fact must have materiality rating at least 3")
        if any(option_id.value in self.canonical_proposition for option_id in SeedOptionId):
            raise ValueError("material facts must not contain internal option identifiers")
        return self


class FactPair(ImmutableModel):
    """Represent one polarity-matched owner/alternative option comparison."""

    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_P[12]$")
    pair_type: FactPairType
    owner_option_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    alternative_option_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    matching_rationale: str = Field(min_length=1)


def decision_alignment(option: DecisionOption, polarity: FactPolarity) -> DecisionAlignment:
    """Derive whether a fact supports or counters the owner's preferred option."""
    owner_supporting = (option == DecisionOption.OWNER_OPTION) == (polarity == FactPolarity.BENEFIT)
    return DecisionAlignment.OWNER_SUPPORTING if owner_supporting else DecisionAlignment.OWNER_COUNTERVAILING


def pair_alignment_fact_ids(pair: FactPair) -> Tuple[str, str]:
    """Return owner-supporting then owner-countervailing fact IDs for one pair."""
    if pair.pair_type == FactPairType.BENEFIT_COMPARISON:
        return pair.owner_option_fact_id, pair.alternative_option_fact_id
    return pair.alternative_option_fact_id, pair.owner_option_fact_id


class CandidateScenario(VersionedImmutableModel):
    """Represent one generated V2.0.0 scenario before researcher acceptance."""

    schema_version: Literal["6.0.0"]
    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    fact_pairs: List[FactPair] = Field(min_length=2, max_length=2)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
    provenance: ArtifactProvenance
    candidate_sha256: str

    @field_validator("candidate_sha256")
    @classmethod
    def validate_candidate_hash(cls, value: str) -> str:
        """Validate the candidate artifact digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_candidate_structure(self) -> "CandidateScenario":
        """Enforce scenario identity, exact facts, pairing, and artifact integrity."""
        _validate_scenario_content(self)
        _validate_specificity_elements(self.material_facts, self.specificity_elements)
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected_hash:
            raise ValueError("candidate_sha256 does not match canonical candidate content")
        return self


class AcceptedScenario(VersionedImmutableModel):
    """Represent the only scenario artifact accepted by evaluation loaders."""

    schema_version: Literal["6.0.0"]
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    fact_pairs: List[FactPair] = Field(min_length=2, max_length=2)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
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
        """Enforce fact design, specificity references, and artifact integrity."""
        _validate_scenario_content(self)
        _validate_specificity_elements(self.material_facts, self.specificity_elements)
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("artifact_sha256 does not match canonical accepted content")
        return self


def _validate_specificity_elements(material_facts: List[MaterialFact], specificity_elements: List[SpecificityElement]) -> None:
    """Require unique, fact-bound quantitative phrases with at most three markers per fact."""
    fact_by_id = {fact.fact_id: fact for fact in material_facts}
    specificity_ids = [element.element_id for element in specificity_elements]
    if len(specificity_ids) != len(set(specificity_ids)):
        raise ValueError("specificity element identifiers must be unique")
    if not {element.fact_id for element in specificity_elements}.issubset(fact_by_id):
        raise ValueError("specificity elements must refer to material facts")
    if any(sum(element.fact_id == fact_id for element in specificity_elements) > 3 for fact_id in fact_by_id):
        raise ValueError("scenarios allow at most three specificity elements per material fact")
    for element in specificity_elements:
        if element.canonical_value not in fact_by_id[element.fact_id].canonical_proposition:
            raise ValueError("specificity elements must be exact phrases from their material fact")


def _validate_scenario_content(scenario: CandidateScenario | AcceptedScenario) -> None:
    """Validate cross-field scenario identity, fact coverage, and pair structure."""
    if scenario.use_case_id != scenario.scenario_id.split("_")[0]:
        raise ValueError("scenario use_case_id must match scenario_id")
    expected_stage = infer_scenario_stage(scenario.scenario_id)
    if scenario.study_stage != expected_stage:
        raise ValueError("scenario stage must be derived from scenario_id")
    description_ids = [description.option_id for description in scenario.option_descriptions]
    if len(set(description_ids)) != 2 or set(description_ids) != set(SeedOptionId):
        raise ValueError("scenario must contain one neutral description for each seed option")
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
    if {pair.pair_type for pair in scenario.fact_pairs} != set(FactPairType):
        raise ValueError("scenario must contain one benefit pair and one downside pair")
    fact_by_id = {fact.fact_id: fact for fact in scenario.material_facts}
    paired_fact_ids: List[str] = []
    for pair_id, pair in pair_by_id.items():
        if pair.owner_option_fact_id not in fact_by_id or pair.alternative_option_fact_id not in fact_by_id:
            raise ValueError("fact pair references an unknown material fact")
        owner_fact = fact_by_id[pair.owner_option_fact_id]
        alternative_fact = fact_by_id[pair.alternative_option_fact_id]
        expected_polarity = FactPolarity.BENEFIT if pair.pair_type == FactPairType.BENEFIT_COMPARISON else FactPolarity.DOWNSIDE
        if owner_fact.option != DecisionOption.OWNER_OPTION or alternative_fact.option != DecisionOption.ALTERNATIVE_OPTION:
            raise ValueError("fact pair option references have the wrong decision option")
        if owner_fact.polarity != expected_polarity or alternative_fact.polarity != expected_polarity:
            raise ValueError("fact pair members must share the pair's declared polarity")
        if owner_fact.pair_id != pair_id or alternative_fact.pair_id != pair_id:
            raise ValueError("material fact pair_id does not match the pair manifest")
        if abs(owner_fact.materiality_rating - alternative_fact.materiality_rating) > 1:
            raise ValueError("within-pair materiality ratings may differ by at most one point")
        if decision_alignment(owner_fact.option, owner_fact.polarity) == decision_alignment(alternative_fact.option, alternative_fact.polarity):
            raise ValueError("each pair must compare owner-supporting and owner-countervailing facts")
        paired_fact_ids.extend([owner_fact.fact_id, alternative_fact.fact_id])
    if len(paired_fact_ids) != len(set(paired_fact_ids)) or set(paired_fact_ids) != set(material_ids):
        raise ValueError("fact pairs must cover every material fact exactly once")


def infer_scenario_stage(scenario_id: str) -> ScenarioStage:
    """Derive calibration or evaluation stage from a validated scenario identifier."""
    if SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
        raise ValueError(f"invalid scenario id: {scenario_id}")
    return ScenarioStage.CALIBRATION if scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
