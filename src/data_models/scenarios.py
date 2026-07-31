"""Strict V2.0.0 seed and option-information scenario models."""

from __future__ import annotations

import re
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
    seed_version: Literal["v2.0.0"]
    generation_protocol_version: Literal["v1.0.10"]
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


class ScenarioMigrationEntry(ImmutableModel):
    """Bind one migrated candidate to its approved source-run artifact."""

    scenario_id: str = Field(pattern=SCENARIO_ID_REGEX)
    source_run_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
    source_round_id: str = Field(pattern=r"^\d{8}T\d{12}Z$")
    source_candidate_sha256: str
    migrated_candidate_sha256: str
    researcher_review_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    source_automated_review_sha256: str

    @field_validator("source_candidate_sha256", "migrated_candidate_sha256", "source_automated_review_sha256")
    @classmethod
    def validate_migration_hashes(cls, value: str) -> str:
        """Validate every source and migrated artifact digest."""
        return validate_sha256(value)


class ScenarioMigrationManifest(VersionedImmutableModel):
    """Record a complete approved calibration-set schema migration."""

    schema_version: Literal["1.0.0"]
    target_run_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
    source_run_ids: List[str] = Field(min_length=1)
    entries: List[ScenarioMigrationEntry] = Field(min_length=10, max_length=10)
    migrated_at: datetime
    manifest_sha256: str

    @field_validator("manifest_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        """Validate the migration-manifest digest format."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_migration_manifest(self) -> "ScenarioMigrationManifest":
        """Require all ten C1 scenarios and a valid manifest self-hash."""
        expected_ids = {f"CF{index:03d}_C1" for index in range(1, 11)}
        scenario_ids = [entry.scenario_id for entry in self.entries]
        if set(scenario_ids) != expected_ids or len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("migration manifest must contain every C1 scenario exactly once")
        if set(self.source_run_ids) != {entry.source_run_id for entry in self.entries}:
            raise ValueError("migration source run ids must match the entry sources")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected_hash:
            raise ValueError("migration manifest digest does not match canonical content")
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
    """Represent one decision-material fact at a derived option-polarity coordinate."""

    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_P[12]$")
    option: DecisionOption
    polarity: FactPolarity
    canonical_proposition: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_proposition(self) -> "MaterialFact":
        """Keep research-only option identifiers out of evaluated fact text."""
        if any(option_id.value in self.canonical_proposition for option_id in SeedOptionId):
            raise ValueError("material facts must not contain internal option identifiers")
        return self


def decision_alignment(option: DecisionOption, polarity: FactPolarity) -> DecisionAlignment:
    """Derive whether a fact supports or counters the owner's preferred option."""
    owner_supporting = (option == DecisionOption.OWNER_OPTION) == (polarity == FactPolarity.BENEFIT)
    return DecisionAlignment.OWNER_SUPPORTING if owner_supporting else DecisionAlignment.OWNER_COUNTERVAILING


def material_fact_pairs(material_facts: List[MaterialFact]) -> List[Tuple[MaterialFact, MaterialFact]]:
    """Return benefit then downside pairs, each ordered owner option then alternative."""
    fact_by_coordinate = {(fact.option, fact.polarity): fact for fact in material_facts}
    expected_coordinates = {(option, polarity) for option in DecisionOption for polarity in FactPolarity}
    if len(fact_by_coordinate) != len(material_facts) or set(fact_by_coordinate) != expected_coordinates:
        raise ValueError("material facts must contain one fact in every option-by-polarity cell")
    return [
        (
            fact_by_coordinate[(DecisionOption.OWNER_OPTION, polarity)],
            fact_by_coordinate[(DecisionOption.ALTERNATIVE_OPTION, polarity)],
        )
        for polarity in FactPolarity
    ]


def pair_alignment_fact_ids(owner_option_fact: MaterialFact, alternative_option_fact: MaterialFact) -> Tuple[str, str]:
    """Return owner-supporting then owner-countervailing fact IDs for one derived pair."""
    if decision_alignment(owner_option_fact.option, owner_option_fact.polarity) == DecisionAlignment.OWNER_SUPPORTING:
        return owner_option_fact.fact_id, alternative_option_fact.fact_id
    return alternative_option_fact.fact_id, owner_option_fact.fact_id


def derived_option_descriptions(options: List[ScenarioOptionInformation]) -> List[OptionDescription]:
    """Derive the legacy neutral-description view used by rendering and analysis."""
    return [OptionDescription(option_id=option.option_id, description=option.description) for option in options]


def derived_material_facts(
    scenario_id: str,
    hidden_design: ScenarioHiddenDesign,
    options: List[ScenarioOptionInformation],
) -> List[MaterialFact]:
    """Derive stable scoring facts from option ownership and directional slots."""
    information_by_option = {option.option_id: option for option in options}
    option_mapping = {
        DecisionOption.OWNER_OPTION: hidden_design.owner_supporting_option,
        DecisionOption.ALTERNATIVE_OPTION: alternative_seed_option(hidden_design.owner_supporting_option),
    }
    facts: List[MaterialFact] = []
    for pair_number, polarity in enumerate(FactPolarity, start=1):
        pair_id = f"{scenario_id}_P{pair_number}"
        for offset, decision_option in enumerate(DecisionOption):
            information = information_by_option[option_mapping[decision_option]]
            directional_fact = information.favourable_fact if polarity == FactPolarity.BENEFIT else information.adverse_fact
            facts.append(
                MaterialFact(
                    fact_id=f"{scenario_id}_F{(pair_number - 1) * 2 + offset + 1}",
                    pair_id=pair_id,
                    option=decision_option,
                    polarity=polarity,
                    canonical_proposition=directional_fact.fact_text,
                )
            )
    return facts


def derived_specificity_elements(
    scenario_id: str,
    hidden_design: ScenarioHiddenDesign,
    options: List[ScenarioOptionInformation],
) -> List[SpecificityElement]:
    """Derive stable marker identifiers and scoring records from option facts."""
    fact_by_coordinate = {(fact.option, fact.polarity): fact for fact in derived_material_facts(scenario_id, hidden_design, options)}
    decision_option_by_option_id = {
        hidden_design.owner_supporting_option: DecisionOption.OWNER_OPTION,
        alternative_seed_option(hidden_design.owner_supporting_option): DecisionOption.ALTERNATIVE_OPTION,
    }
    elements: List[SpecificityElement] = []
    for option in options:
        decision_option = decision_option_by_option_id[option.option_id]
        for polarity, directional_fact in (
            (FactPolarity.BENEFIT, option.favourable_fact),
            (FactPolarity.DOWNSIDE, option.adverse_fact),
        ):
            fact_id = fact_by_coordinate[(decision_option, polarity)].fact_id
            elements.extend(
                SpecificityElement(
                    element_id=f"{fact_id}_S{index}",
                    fact_id=fact_id,
                    canonical_value=marker,
                )
                for index, marker in enumerate(directional_fact.specificity_markers, start=1)
            )
    return sorted(elements, key=lambda element: element.element_id)


class CandidateScenario(VersionedImmutableModel):
    """Represent one generated V2.0.0 scenario before researcher acceptance."""

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

    @property
    def option_descriptions(self) -> List[OptionDescription]:
        """Derive neutral option descriptions for existing consumers."""
        return derived_option_descriptions(self.options)

    @property
    def material_facts(self) -> List[MaterialFact]:
        """Derive the four stable scoring facts for existing consumers."""
        return derived_material_facts(self.scenario_id, self.hidden_design, self.options)

    @property
    def specificity_elements(self) -> List[SpecificityElement]:
        """Derive stable specificity records for existing consumers."""
        return derived_specificity_elements(self.scenario_id, self.hidden_design, self.options)

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

    @property
    def option_descriptions(self) -> List[OptionDescription]:
        """Derive neutral option descriptions for existing consumers."""
        return derived_option_descriptions(self.options)

    @property
    def material_facts(self) -> List[MaterialFact]:
        """Derive the four stable scoring facts for existing consumers."""
        return derived_material_facts(self.scenario_id, self.hidden_design, self.options)

    @property
    def specificity_elements(self) -> List[SpecificityElement]:
        """Derive stable specificity records for existing consumers."""
        return derived_specificity_elements(self.scenario_id, self.hidden_design, self.options)

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
    """Validate scenario identity and deterministic option coverage."""
    if scenario.use_case_id != scenario.scenario_id.split("_")[0]:
        raise ValueError("scenario use_case_id must match scenario_id")
    expected_stage = infer_scenario_stage(scenario.scenario_id)
    if scenario.study_stage != expected_stage:
        raise ValueError("scenario stage must be derived from scenario_id")
    option_ids = [option.option_id for option in scenario.options]
    if option_ids != scenario.hidden_design.presentation_order:
        raise ValueError("scenario options must follow the hidden presentation order")
    material_facts = scenario.material_facts
    _validate_specificity_elements(material_facts, scenario.specificity_elements)
    material_fact_pairs(material_facts)


def infer_scenario_stage(scenario_id: str) -> ScenarioStage:
    """Derive calibration or evaluation stage from a validated scenario identifier."""
    if SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
        raise ValueError(f"invalid scenario id: {scenario_id}")
    return ScenarioStage.CALIBRATION if scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
