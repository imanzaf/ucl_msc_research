"""Strict V3.0.0 seed and option-information scenario models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Literal, Optional, Tuple

from pydantic import Field, ValidationInfo, field_validator, model_validator

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
    seed_version: Literal["v2.1.0", "v3.0.0"]
    generation_protocol_version: Literal["v1.0.11", "v1.1.0", "v1.1.1"]
    scenario_set_id: Literal["customer_facing_risk_communication_v2.1.0", "customer_facing_risk_communication_v3.0.0"]
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
        expected_set_id = f"customer_facing_risk_communication_{self.seed_version}"
        if self.scenario_set_id != expected_set_id:
            raise ValueError("scenario generation run seed version and set identifier must match")
        return self


class ScenarioGenerationInvocationConfig(VersionedImmutableModel):
    """Record one resumable command invocation within a logical generation run."""

    schema_version: Literal["1.0.0"]
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
    invocation_id: str = Field(pattern=r"^\d{8}T\d{12}Z$")
    stage: ScenarioStage
    scenario_ids: List[str] = Field(min_length=1, max_length=20)
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


class SeedOptionId(str, Enum):
    """Identify one neutrally labelled option in a generation seed."""

    OPTION_A = "OPTION_A"
    OPTION_B = "OPTION_B"


class ComparisonScope(str, Enum):
    """Identify whether both options belong to the provider or one is external."""

    INTRA_PROVIDER = "intra_provider"
    PROVIDER_VS_EXTERNAL = "provider_vs_external"


def alternative_seed_option(owner_supporting_option: SeedOptionId) -> SeedOptionId:
    """Return the non-owner-supporting option in a two-option seed decision."""
    return SeedOptionId.OPTION_B if owner_supporting_option == SeedOptionId.OPTION_A else SeedOptionId.OPTION_A


class FinanceEntityType(str, Enum):
    """Identify the generic finance-domain entity deploying the evaluated assistant."""

    RETAIL_BANK = "retail bank"
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


class ScenarioFactInformation(ImmutableModel):
    """Store one customer-facing directional fact and its quantitative phrases."""

    fact_text: str = Field(min_length=1, max_length=400, pattern=r"\S")
    specificity_markers: List[str] = Field(max_length=3)

    @field_validator("specificity_markers", mode="before")
    @classmethod
    def retain_exact_quantitative_markers(cls, values: Any, info: ValidationInfo) -> Any:
        """Discard qualitative markers and markers not copied exactly from the fact."""
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            return values
        fact_text = info.data.get("fact_text")
        return [
            value for value in values if any(character.isdigit() for character in value) and (not isinstance(fact_text, str) or value in fact_text)
        ]

    @field_validator("specificity_markers")
    @classmethod
    def validate_specificity_markers(cls, values: List[str]) -> List[str]:
        """Require unique, trimmed quantitative phrases."""
        if len(values) != len(set(values)):
            raise ValueError("specificity markers must be unique")
        if any(value != value.strip() or not value for value in values):
            raise ValueError("specificity markers must be nonblank and trimmed")
        return values


class ScenarioOptionInformation(ImmutableModel):
    """Store the visible description and directional facts for one option."""

    option_id: SeedOptionId
    description: str = Field(min_length=1, max_length=400, pattern=r"\S")
    favourable_fact: ScenarioFactInformation
    adverse_fact: ScenarioFactInformation

    @model_validator(mode="after")
    def validate_private_identifiers_absent(self) -> "ScenarioOptionInformation":
        """Keep internal option identifiers out of all customer-facing prose."""
        text_fields = [self.description, self.favourable_fact.fact_text, self.adverse_fact.fact_text]
        if any(option_id.value in text for option_id in SeedOptionId for text in text_fields):
            raise ValueError("scenario option text must not contain internal option identifiers")
        return self


@dataclass(frozen=True)
class ScenarioFactCoordinate:
    """Identify one scenario fact for scoring without duplicating its content."""

    fact_id: str
    pair_id: str
    option: DecisionOption
    polarity: FactPolarity


class ScenarioHiddenDesign(ImmutableModel):
    """Store one decision's research-only ownership mapping and display order."""

    decision_type: str = Field(min_length=1, pattern=r"\S")
    options: List[ScenarioOptionDefinition] = Field(min_length=2, max_length=2)
    owner_supporting_option: SeedOptionId
    owner_benefit_mechanism: str = Field(min_length=1, pattern=r"\S")
    presentation_order: List[SeedOptionId] = Field(min_length=2, max_length=2)
    comparison_scope: Optional[ComparisonScope] = Field(default=None, exclude_if=lambda value: value is None)
    external_option_id: Optional[SeedOptionId] = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_options(self) -> "ScenarioHiddenDesign":
        """Require two distinct options, one owner preference, and a complete order."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("V2.0.0 decisions require exactly OPTION_A and OPTION_B")
        if len({option.option_name.casefold() for option in self.options}) != 2:
            raise ValueError("V2.0.0 option names must be distinct")
        if set(self.presentation_order) != set(SeedOptionId):
            raise ValueError("presentation_order must contain OPTION_A and OPTION_B exactly once")
        if self.comparison_scope is None:
            if self.external_option_id is not None:
                raise ValueError("legacy hidden designs cannot identify an external option without a comparison scope")
            return self
        if self.comparison_scope == ComparisonScope.INTRA_PROVIDER and self.external_option_id is not None:
            raise ValueError("intra-provider comparisons cannot identify an external option")
        if self.comparison_scope == ComparisonScope.PROVIDER_VS_EXTERNAL:
            if self.external_option_id is None:
                raise ValueError("provider-versus-external comparisons must identify the external option")
            if self.external_option_id == self.owner_supporting_option:
                raise ValueError("the provider owner cannot benefit from the external option")
        return self


class ScenarioReplicationDefinition(ScenarioHiddenDesign):
    """Define one calibration or held-out decision without customer queries."""

    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    comparison_scope: ComparisonScope
    external_option_id: Optional[SeedOptionId]

    @model_validator(mode="after")
    def validate_stage_scope(self) -> "ScenarioReplicationDefinition":
        """Require R1 to compare internal options and R2 to compare the provider with an external option."""
        if self.scenario_id.endswith("_R1") and self.comparison_scope != ComparisonScope.INTRA_PROVIDER:
            raise ValueError("R1 must compare two options from the same provider")
        if self.scenario_id.endswith("_R2") and self.comparison_scope != ComparisonScope.PROVIDER_VS_EXTERNAL:
            raise ValueError("R2 must compare the current provider with one external option")
        return self


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
    """Represent the complete active V3.0.0 scenario-definition document."""

    schema_version: Literal["3.0.0"]
    scenario_set_id: Literal["customer_facing_risk_communication_v3.0.0"]
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
    """Represent the complete active V3.0.0 customer-query document."""

    schema_version: Literal["3.0.0"]
    scenario_set_id: Literal["customer_facing_risk_communication_v3.0.0"]
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


def decision_alignment(option: DecisionOption, polarity: FactPolarity) -> DecisionAlignment:
    """Derive whether a fact supports or counters the owner's preferred option."""
    owner_supporting = (option == DecisionOption.OWNER_OPTION) == (polarity == FactPolarity.BENEFIT)
    return DecisionAlignment.OWNER_SUPPORTING if owner_supporting else DecisionAlignment.OWNER_COUNTERVAILING


class CandidateScenario(VersionedImmutableModel):
    """Represent one generated scenario before researcher publication."""

    schema_version: Literal["9.0.0"]
    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    options: List[ScenarioOptionInformation] = Field(min_length=2, max_length=2)
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
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected_hash:
            raise ValueError("candidate_sha256 does not match canonical candidate content")
        return self


class AcceptedScenario(VersionedImmutableModel):
    """Represent the only scenario artifact accepted by evaluation loaders."""

    schema_version: Literal["9.0.0"]
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    use_case_id: str = Field(pattern=USE_CASE_ID_REGEX)
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    options: List[ScenarioOptionInformation] = Field(min_length=2, max_length=2)
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
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("artifact_sha256 does not match canonical accepted content")
        return self


ScenarioFactItem = Tuple[ScenarioFactCoordinate, ScenarioFactInformation]


def scenario_fact_items(scenario: CandidateScenario | AcceptedScenario) -> List[ScenarioFactItem]:
    """Associate each canonical fact object with deterministic scoring coordinates."""
    information_by_option = {option.option_id: option for option in scenario.options}
    seed_option_by_decision_option = {
        DecisionOption.OWNER_OPTION: scenario.hidden_design.owner_supporting_option,
        DecisionOption.ALTERNATIVE_OPTION: alternative_seed_option(scenario.hidden_design.owner_supporting_option),
    }
    items: List[ScenarioFactItem] = []
    for pair_number, polarity in enumerate(FactPolarity, start=1):
        for offset, decision_option in enumerate(DecisionOption):
            option = information_by_option[seed_option_by_decision_option[decision_option]]
            information = option.favourable_fact if polarity == FactPolarity.BENEFIT else option.adverse_fact
            coordinate = ScenarioFactCoordinate(
                fact_id=f"{scenario.scenario_id}_F{(pair_number - 1) * 2 + offset + 1}",
                pair_id=f"{scenario.scenario_id}_P{pair_number}",
                option=decision_option,
                polarity=polarity,
            )
            items.append((coordinate, information))
    return items


def scenario_facts(scenario: CandidateScenario | AcceptedScenario) -> List[ScenarioFactInformation]:
    """Return the four canonical fact objects in stable scoring-ID order."""
    return [information for _, information in scenario_fact_items(scenario)]


def scenario_fact_pairs(scenario: CandidateScenario | AcceptedScenario) -> List[Tuple[ScenarioFactItem, ScenarioFactItem]]:
    """Return benefit then downside pairs, each ordered owner option then alternative."""
    items = scenario_fact_items(scenario)
    item_by_coordinate = {(item[0].option, item[0].polarity): item for item in items}
    return [
        (
            item_by_coordinate[(DecisionOption.OWNER_OPTION, polarity)],
            item_by_coordinate[(DecisionOption.ALTERNATIVE_OPTION, polarity)],
        )
        for polarity in FactPolarity
    ]


def pair_alignment_fact_ids(
    owner_option_coordinate: ScenarioFactCoordinate,
    alternative_option_coordinate: ScenarioFactCoordinate,
) -> Tuple[str, str]:
    """Return owner-supporting then owner-countervailing IDs for one fact pair."""
    if decision_alignment(owner_option_coordinate.option, owner_option_coordinate.polarity) == DecisionAlignment.OWNER_SUPPORTING:
        return owner_option_coordinate.fact_id, alternative_option_coordinate.fact_id
    return alternative_option_coordinate.fact_id, owner_option_coordinate.fact_id


def _validate_scenario_content(scenario: CandidateScenario | AcceptedScenario) -> None:
    """Validate scenario identity and deterministic option coverage."""
    if scenario.use_case_id != scenario.scenario_id.split("_")[0]:
        raise ValueError("scenario use_case_id must match scenario_id")
    expected_stage = infer_scenario_stage(scenario.scenario_id)
    if scenario.study_stage != expected_stage:
        raise ValueError("scenario stage must be derived from scenario_id")
    option_ids = [option.option_id for option in scenario.options]
    if option_ids != scenario.hidden_design.presentation_order:
        raise ValueError("scenario options must follow the hidden presentation order")
    if len(scenario_fact_items(scenario)) != 4:
        raise ValueError("scenarios must contain exactly four directional facts")


def infer_scenario_stage(scenario_id: str) -> ScenarioStage:
    """Derive calibration or evaluation stage from a validated scenario identifier."""
    if SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
        raise ValueError(f"invalid scenario id: {scenario_id}")
    return ScenarioStage.CALIBRATION if scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
