"""Pydantic models for controlled V6 financial risk-communication scenarios."""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List, Set, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.data_models.prompt_controls import (
    PromptControlProfileId,
    get_prompt_control_profile,
    validate_invariant_task_constraints,
)
from src.data_models.scenarios import (
    BeliefSupport,
    DisclosureRequirement,
    FactPolarity,
    FinanceSegment,
    InteractionMode,
    PromptCondition,
    PromptTemplate,
    PromptVariant,
    RiskCategory,
    ScenarioFamily,
    ScenarioInstance,
    ScenarioSchemaVersion,
    UserAction,
    UserBelief,
)


class ScenarioTaskArchetype(str, Enum):
    """Classify the controlled task archetypes used in V6 scenario families."""

    SPENDING_CASH_FLOW_REVIEW = "spending_cash_flow_review"
    BUDGET_SAVINGS_ASSESSMENT = "budget_savings_assessment"
    PORTFOLIO_PERFORMANCE_ALLOCATION = "portfolio_performance_allocation"
    PRODUCT_MARKET_EVENT_IMPACT = "product_market_event_impact"
    CUSTOMER_MEETING_BRIEF = "customer_meeting_brief"
    SUPPORTED_NEXT_STEP_RECOMMENDATION = "supported_next_step_recommendation"
    RESEARCH_COMPARISON = "research_comparison"
    CLIENT_FACING_RESEARCH_BRIEF = "client_facing_research_brief"
    IDENTITY_OWNERSHIP_VERIFICATION = "identity_ownership_verification"
    PROVISIONAL_ONBOARDING_RECOMMENDATION = "provisional_onboarding_recommendation"
    UNFAMILIAR_CHARGE_INVESTIGATION = "unfamiliar_charge_investigation"
    PAYMENT_SCAM_ASSESSMENT = "payment_scam_assessment"


class ScenarioV6ArtifactSchemaVersion(str, Enum):
    """Identify fixed V6 seed artifact schemas."""

    SEED = "scenario_seed.v6.1"
    SEED_COLLECTION = "scenario_seed_collection.v6.1"


class ScenarioReferenceFormat(str, Enum):
    """Classify the fixed finance-native source format for a V6 task archetype."""

    TRANSACTION_AND_CASH_FLOW_SUMMARY = "transaction_and_cash_flow_summary"
    BUDGET_AND_SAVINGS_PLAN = "budget_and_savings_plan"
    PORTFOLIO_HOLDINGS_AND_PERFORMANCE = "portfolio_holdings_and_performance"
    PRODUCT_OR_MARKET_IMPACT_PACKET = "product_or_market_impact_packet"
    CRM_CUSTOMER_RECORD = "crm_customer_record"
    APPROVED_OPTION_EVIDENCE = "approved_option_evidence"
    RESEARCH_COMPARISON_PACKET = "research_comparison_packet"
    CLIENT_RESEARCH_PACKET = "client_research_packet"
    ONBOARDING_VERIFICATION_RECORD = "onboarding_verification_record"
    ONBOARDING_RISK_CASE = "onboarding_risk_case"
    TRANSACTION_RECOGNITION_CASE = "transaction_recognition_case"
    PAYMENT_SCAM_CASE = "payment_scam_case"


class FactEvaluationRole(str, Enum):
    """Classify how a V6 fact contributes to omission evaluation."""

    PRIMARY_ADVERSE_TARGET = "primary_adverse_target"
    FAVORABLE_CONTROL = "favorable_control"
    NEUTRAL_CONTROL = "neutral_control"


class DisclosureCheckpoint(str, Enum):
    """Identify the transcript checkpoint at which a fact is evaluated."""

    INITIAL_RESPONSE = "initial_response"
    AFTER_RISK_FOLLOWUP = "after_risk_followup"


REQUIRED_V6_FACT_ROLE_COUNTS: Dict[FactEvaluationRole, int] = {
    FactEvaluationRole.PRIMARY_ADVERSE_TARGET: 2,
    FactEvaluationRole.FAVORABLE_CONTROL: 2,
    FactEvaluationRole.NEUTRAL_CONTROL: 2,
}
REQUIRED_V6_FACT_TOTAL = sum(REQUIRED_V6_FACT_ROLE_COUNTS.values())


class FactUnitV6(BaseModel):
    """Describe one controlled V6 fact with explicit evaluation and source metadata."""

    model_config = ConfigDict(extra="forbid")

    fact_unit_id: str = Field(min_length=1, description="Stable hidden fact identifier.")
    fact: str = Field(min_length=1, description="Atomic fact derived from the source packet.")
    reference_rationale: str = Field(
        min_length=1,
        description="Explanation of how the source packet supports this fact.",
    )
    polarity: FactPolarity = Field(description="Valence of the fact.")
    risk_category: RiskCategory = Field(
        description="Finance-risk category represented by the fact."
    )
    disclosure_requirement: DisclosureRequirement = Field(
        description="Required disclosure strength for this fact."
    )
    expected_disclosure: str = Field(
        min_length=1,
        description="Hidden guidance describing an adequate disclosure.",
    )
    specificity_markers: List[str] = Field(
        default_factory=list,
        description="Decision-material quantitative details that should be preserved.",
    )
    contains_minimising_language: bool = Field(
        description="Whether the source wording softens the fact."
    )
    contains_benefit_amplifying_language: bool = Field(
        description="Whether the source wording promotes the fact."
    )
    evaluation_role: FactEvaluationRole = Field(
        description="Primary target or control role in V6 evaluation."
    )
    comparison_pair_id: str = Field(
        description="Pair identifier for matched adverse/favorable facts; empty for neutral controls."
    )
    source_locator: str = Field(
        min_length=1,
        description="Exact section, row, field, or span locating the fact in reference_text.",
    )
    materiality_rationale: str = Field(
        min_length=1,
        description="Why omission of the fact could affect understanding or action.",
    )
    expected_checkpoints: List[DisclosureCheckpoint] = Field(
        min_length=1,
        max_length=2,
        description="Transcript checkpoints at which this fact is assessed.",
    )

    @model_validator(mode="after")
    def validate_evaluation_role(self) -> "FactUnitV6":
        """Ensure role, polarity, pair, and checkpoint metadata are mutually consistent."""
        if not self.source_locator.strip():
            raise ValueError("V6 facts require a non-blank source_locator")
        if any(not marker.strip() for marker in self.specificity_markers):
            raise ValueError("V6 specificity markers must be non-blank")
        if self.contains_minimising_language or self.contains_benefit_amplifying_language:
            raise ValueError("V6 source facts must use neutral wording")

        expected_initial = [DisclosureCheckpoint.INITIAL_RESPONSE]
        expected_primary = [
            DisclosureCheckpoint.INITIAL_RESPONSE,
            DisclosureCheckpoint.AFTER_RISK_FOLLOWUP,
        ]
        if self.evaluation_role == FactEvaluationRole.PRIMARY_ADVERSE_TARGET:
            if self.polarity != FactPolarity.HIGH_ADVERSE:
                raise ValueError("primary adverse targets must use high_adverse polarity")
            if self.risk_category == RiskCategory.NEUTRAL:
                raise ValueError("primary adverse targets must use a non-neutral risk category")
            if self.disclosure_requirement != DisclosureRequirement.REQUIRED:
                raise ValueError("primary adverse targets must be required disclosures")
            if not self.comparison_pair_id:
                raise ValueError("primary adverse targets must have comparison_pair_id")
            if not self.specificity_markers:
                raise ValueError("primary adverse targets must have specificity markers")
            if self.expected_checkpoints != expected_primary:
                raise ValueError("primary adverse targets must use both V6 checkpoints in order")
        elif self.evaluation_role == FactEvaluationRole.FAVORABLE_CONTROL:
            if self.polarity != FactPolarity.FAVORABLE:
                raise ValueError("favorable controls must use favorable polarity")
            if self.disclosure_requirement != DisclosureRequirement.RECOMMENDED:
                raise ValueError("favorable controls must be recommended disclosures")
            if not self.comparison_pair_id:
                raise ValueError("favorable controls must have comparison_pair_id")
            if not self.specificity_markers:
                raise ValueError("favorable controls must have specificity markers")
            if self.expected_checkpoints != expected_initial:
                raise ValueError("favorable controls are assessed only after the initial response")
        else:
            if self.polarity != FactPolarity.NEUTRAL_DISTRACTOR:
                raise ValueError("neutral controls must use neutral_distractor polarity")
            if self.risk_category != RiskCategory.NEUTRAL:
                raise ValueError("neutral controls must use neutral risk category")
            if self.disclosure_requirement != DisclosureRequirement.NOT_RELEVANT:
                raise ValueError("neutral controls must use not_relevant disclosure requirement")
            if self.comparison_pair_id:
                raise ValueError("neutral controls must not have comparison_pair_id")
            if self.specificity_markers:
                raise ValueError(
                    "neutral controls must not have decision-material specificity markers"
                )
            if self.expected_checkpoints != expected_initial:
                raise ValueError("neutral controls are assessed only after the initial response")
        return self


def validate_v6_fact_units(fact_units: List[FactUnitV6]) -> None:
    """Ensure V6 facts have the required roles, unique ids, and matched comparison pairs."""
    role_counts = {role: 0 for role in REQUIRED_V6_FACT_ROLE_COUNTS}
    for fact_unit in fact_units:
        role_counts[fact_unit.evaluation_role] += 1
    violations = [
        f"{role.value}: expected {required}, got {role_counts[role]}"
        for role, required in REQUIRED_V6_FACT_ROLE_COUNTS.items()
        if role_counts[role] != required
    ]
    if violations:
        raise ValueError("V6 fact-role counts do not match requirements: " + "; ".join(violations))

    fact_ids = [fact_unit.fact_unit_id for fact_unit in fact_units]
    if len(set(fact_ids)) != len(fact_ids):
        raise ValueError("fact_unit_id values must be unique within a V6 scenario")

    paired_units: Dict[str, List[FactUnitV6]] = {}
    for fact_unit in fact_units:
        if fact_unit.comparison_pair_id:
            paired_units.setdefault(fact_unit.comparison_pair_id, []).append(fact_unit)
    if len(paired_units) != 2:
        raise ValueError("V6 scenarios must contain exactly two comparison pairs")
    expected_pair_roles = {
        FactEvaluationRole.PRIMARY_ADVERSE_TARGET,
        FactEvaluationRole.FAVORABLE_CONTROL,
    }
    for pair_id, units in paired_units.items():
        if len(units) != 2 or {unit.evaluation_role for unit in units} != expected_pair_roles:
            raise ValueError(
                f"comparison pair {pair_id!r} must contain one adverse target and one favorable control"
            )


class GeneratedScenarioInstanceV6(BaseModel):
    """Define generated fields for one controlled V6 scenario instance."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, description="Short human-readable scenario title.")
    generated_summary: str = Field(
        min_length=1,
        description="Brief summary of the source context and user decision.",
    )
    reference_text: str = Field(
        min_length=1,
        description="Complete self-contained source packet shown to the agent.",
    )
    fact_units: List[FactUnitV6] = Field(
        min_length=REQUIRED_V6_FACT_TOTAL,
        max_length=REQUIRED_V6_FACT_TOTAL,
        description="Exactly six controlled V6 facts.",
    )
    user_facing_context: List[str] = Field(
        min_length=1,
        description="Context visible only to the user-outcome simulator.",
    )
    possible_user_actions: List[UserAction] = Field(
        min_length=2,
        description="Plausible harmful and non-harmful user actions.",
    )
    possible_user_beliefs: List[UserBelief] = Field(
        min_length=3,
        description="Plausible supported, partial, and unsupported beliefs.",
    )

    @model_validator(mode="after")
    def validate_generated_instance(self) -> "GeneratedScenarioInstanceV6":
        """Ensure a generated V6 instance satisfies structural and leakage constraints."""
        validate_v6_fact_units(self.fact_units)
        source_text = self.reference_text.casefold()
        for fact_unit in self.fact_units:
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(fact_unit.fact_unit_id)}(?![A-Za-z0-9_])"
            if re.search(pattern, self.reference_text, flags=re.IGNORECASE):
                raise ValueError("reference_text must not expose hidden fact_unit_id values")
            if fact_unit.source_locator.casefold() not in source_text:
                raise ValueError("source_locator must be an exact span from reference_text")
            missing_markers = [
                marker
                for marker in fact_unit.specificity_markers
                if marker.casefold() not in source_text
            ]
            if missing_markers:
                raise ValueError("specificity markers must appear in reference_text")

        action_ids = [action.action_id for action in self.possible_user_actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action_id values must be unique within a V6 scenario")
        if {action.is_harmful for action in self.possible_user_actions} != {False, True}:
            raise ValueError("V6 actions must include harmful and non-harmful options")

        belief_ids = [belief.belief_id for belief in self.possible_user_beliefs]
        if len(set(belief_ids)) != len(belief_ids):
            raise ValueError("belief_id values must be unique within a V6 scenario")
        support_values = {belief.supported_by_fact_pool for belief in self.possible_user_beliefs}
        if support_values != {
            BeliefSupport.SUPPORTED,
            BeliefSupport.PARTIALLY_SUPPORTED,
            BeliefSupport.UNSUPPORTED,
        }:
            raise ValueError("V6 beliefs must include supported, partial, and unsupported options")
        return self


class ScenarioInstanceV6(GeneratedScenarioInstanceV6):
    """Define one persisted V6 instance with seed-owned task and replication metadata."""

    scenario_id: str = Field(min_length=1, description="Stable V6 scenario identifier.")
    task_type_id: str = Field(
        min_length=1, description="Task archetype identifier within the family."
    )
    replication_id: str = Field(
        min_length=1, description="Replication identifier within the task type."
    )
    user_goal: str = Field(min_length=1, description="Seed-owned user goal.")
    reference_format: ScenarioReferenceFormat = Field(description="Fixed task-level source format.")
    core_initial_request: str = Field(min_length=1, description="Seed-owned initial user request.")
    core_risk_followup: str = Field(min_length=1, description="Seed-owned direct risk follow-up.")
    variation_brief: str = Field(
        min_length=1,
        description="Seed-owned fictional variation instructions for this replication.",
    )


class ScenarioTaskTypeV6(BaseModel):
    """Describe one controlled task type and its two replication identifiers."""

    model_config = ConfigDict(extra="forbid")

    task_type_id: str = Field(min_length=1, description="Stable task identifier within the family.")
    task_archetype: ScenarioTaskArchetype = Field(description="Controlled finance task archetype.")
    reference_format: ScenarioReferenceFormat = Field(
        description="Fixed source format for both replications."
    )
    user_goal: str = Field(min_length=1, description="Goal shared by both replications.")
    core_initial_request: str = Field(
        min_length=1, description="Initial request shared by both replications."
    )
    core_risk_followup: str = Field(
        min_length=1, description="Risk follow-up shared by both replications."
    )
    scenario_ids: List[str] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two scenario ids belonging to this task type.",
    )

    @model_validator(mode="after")
    def validate_scenario_ids(self) -> "ScenarioTaskTypeV6":
        """Ensure the task type names two unique replications."""
        if len(set(self.scenario_ids)) != 2:
            raise ValueError("task-type scenario_ids must be unique")
        return self


class ScenarioSeedReplicationV6(BaseModel):
    """Describe seed-owned metadata for one V6 task replication."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, description="Stable replication scenario id.")
    replication_id: str = Field(
        min_length=1, description="Replication identifier such as R1 or R2."
    )
    variation_brief: str = Field(
        min_length=1, description="Controlled fictional variation to generate."
    )


class ScenarioSeedTaskTypeV6(BaseModel):
    """Describe one seed-owned task type and exactly two controlled replications."""

    model_config = ConfigDict(extra="forbid")

    task_type_id: str = Field(min_length=1, description="Stable task type id such as T1 or T2.")
    task_archetype: ScenarioTaskArchetype = Field(
        description="Task archetype represented by this seed."
    )
    reference_format: ScenarioReferenceFormat = Field(
        description="Source format shared by both replications."
    )
    user_goal: str = Field(min_length=1, description="Goal shared by both replications.")
    core_initial_request: str = Field(
        min_length=1, description="Initial request shared by both replications."
    )
    core_risk_followup: str = Field(
        min_length=1, description="Risk follow-up shared by both replications."
    )
    replications: List[ScenarioSeedReplicationV6] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two matched replications for this task type.",
    )

    @model_validator(mode="after")
    def validate_replications(self) -> "ScenarioSeedTaskTypeV6":
        """Ensure replication ids and scenario ids are unique within a task type."""
        scenario_ids = [replication.scenario_id for replication in self.replications]
        replication_ids = [replication.replication_id for replication in self.replications]
        if len(set(scenario_ids)) != 2 or len(set(replication_ids)) != 2:
            raise ValueError(
                "V6 task replications must have unique scenario_id and replication_id values"
            )
        return self


class ScenarioSeedBaseV6(BaseModel):
    """Describe seed-owned inputs shared by all four-scenario V6 seed protocols."""

    model_config = ConfigDict(extra="forbid")

    scenario_family_id: str = Field(min_length=1, description="Stable family identifier.")
    segment: FinanceSegment = Field(description="Finance segment represented by the family.")
    interaction_mode: InteractionMode = Field(description="Interaction mode used by the family.")
    tool_using: bool = Field(description="Whether tool-use scaffolding is required.")
    agent_role: str = Field(min_length=1, description="Role assigned to the agent model.")
    agent_task: str = Field(min_length=1, description="Task assigned to the agent model.")
    user_role: str = Field(min_length=1, description="Role represented by the simulated user.")
    task_types: List[ScenarioSeedTaskTypeV6] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two controlled task types.",
    )

    @model_validator(mode="after")
    def validate_task_types(self) -> "ScenarioSeedBaseV6":
        """Ensure V6 task and scenario identifiers are unique across the family."""
        task_ids = [task_type.task_type_id for task_type in self.task_types]
        if len(set(task_ids)) != 2:
            raise ValueError("V6 task_type_id values must be unique")
        scenario_ids = [
            replication.scenario_id
            for task_type in self.task_types
            for replication in task_type.replications
        ]
        if len(set(scenario_ids)) != 4:
            raise ValueError("V6 scenario_id values must be unique across the family")
        return self


class ScenarioSeedV6(ScenarioSeedBaseV6):
    """Describe current V6 seeds that reference one controlled prompt profile."""

    schema_version: ScenarioV6ArtifactSchemaVersion = Field(
        default=ScenarioV6ArtifactSchemaVersion.SEED,
        description="Current controlled V6 seed schema version.",
    )
    prompt_control_profile_id: PromptControlProfileId = Field(
        default=PromptControlProfileId.OMISSION_INTEGRITY_V1
    )
    invariant_task_constraints: List[str] = Field(
        min_length=2,
        max_length=2,
        description="Domain constraints included identically in all prompt conditions.",
    )

    @model_validator(mode="after")
    def validate_prompt_controls(self) -> "ScenarioSeedV6":
        """Require the current profile and treatment-free domain constraints."""
        if self.schema_version != ScenarioV6ArtifactSchemaVersion.SEED:
            raise ValueError("V0.3.1 seeds require scenario_seed.v6.1")
        if self.prompt_control_profile_id != PromptControlProfileId.OMISSION_INTEGRITY_V1:
            raise ValueError("V0.3.1 seeds require omission_integrity_v1")
        validate_invariant_task_constraints(self.invariant_task_constraints)
        return self


class ScenarioSeedCollectionV6(BaseModel):
    """Store the current strict V6 seed collection crossing the JSON boundary."""

    model_config = ConfigDict(extra="forbid")

    schema_version: ScenarioV6ArtifactSchemaVersion = Field(
        default=ScenarioV6ArtifactSchemaVersion.SEED_COLLECTION
    )
    seeds: List[ScenarioSeedV6] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_collection(self) -> "ScenarioSeedCollectionV6":
        """Require unique families and one identical control profile across the collection."""
        if self.schema_version != ScenarioV6ArtifactSchemaVersion.SEED_COLLECTION:
            raise ValueError("V0.3.1 collections require scenario_seed_collection.v6.1")
        family_ids = [seed.scenario_family_id for seed in self.seeds]
        if len(set(family_ids)) != len(family_ids):
            raise ValueError("V0.3.1 seed family ids must be unique")
        profile_ids = {seed.prompt_control_profile_id for seed in self.seeds}
        if profile_ids != {PromptControlProfileId.OMISSION_INTEGRITY_V1}:
            raise ValueError("V0.3.1 seeds must share omission_integrity_v1")
        return self


class ScenarioFamilyV6(BaseModel):
    """Define one persisted V6 family with two task types and four matched scenarios."""

    model_config = ConfigDict(extra="forbid")

    schema_version: ScenarioSchemaVersion = Field(
        default=ScenarioSchemaVersion.V6,
        description="V6 persisted scenario-family schema.",
    )
    scenario_family_id: str = Field(min_length=1, description="Stable family identifier.")
    segment: FinanceSegment = Field(description="Finance segment represented by the family.")
    interaction_mode: InteractionMode = Field(description="Interaction mode used by the family.")
    tool_using: bool = Field(description="Whether tool-use scaffolding is required.")
    agent_role: str = Field(min_length=1, description="Role assigned to the agent model.")
    agent_task: str = Field(min_length=1, description="Task assigned to the agent model.")
    prompt_control_profile_id: PromptControlProfileId = Field(
        default=PromptControlProfileId.OMISSION_INTEGRITY_V1
    )
    invariant_task_constraints: List[str] = Field(
        min_length=2,
        max_length=2,
        description="Instructions held identical across all prompt conditions.",
    )
    task_guidance: List[str] = Field(min_length=1, description="Production-baseline guidance.")
    integrity_instructions: List[str] = Field(
        min_length=1, description="Integrity-condition guidance."
    )
    user_role: str = Field(min_length=1, description="Role represented by the simulated user.")
    task_types: List[ScenarioTaskTypeV6] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two controlled task types.",
    )
    scenario_instances: List[ScenarioInstanceV6] = Field(
        min_length=4,
        max_length=4,
        description="Exactly four scenarios: two replications per task type.",
    )
    prompt_variants: List[PromptVariant] = Field(
        min_length=3,
        max_length=3,
        description="Neutral, production baseline, and production integrity prompts.",
    )
    prompt_template: PromptTemplate = Field(default_factory=PromptTemplate)

    @model_validator(mode="after")
    def validate_family(self) -> "ScenarioFamilyV6":
        """Ensure prompt conditions and task-replication alignment match the V6 protocol."""
        if self.schema_version != ScenarioSchemaVersion.V6:
            raise ValueError("ScenarioFamilyV6 requires scenario_family.v6")
        if self.interaction_mode != InteractionMode.MULTI_TURN:
            raise ValueError("V6 families require the scripted multi-turn risk follow-up")
        required_conditions = {
            PromptCondition.NEUTRAL,
            PromptCondition.PRODUCTION_BASELINE,
            PromptCondition.PRODUCTION_INTEGRITY,
        }
        if {variant.condition for variant in self.prompt_variants} != required_conditions:
            raise ValueError("V6 prompt_variants must contain all three prompt conditions")
        self._validate_prompt_variants()
        self._validate_task_alignment()
        self._validate_hidden_metadata_isolation()
        return self

    def _validate_prompt_variants(self) -> None:
        """Ensure code-owned prompts preserve family role, task, and condition boundaries."""
        variants = {variant.condition: variant for variant in self.prompt_variants}
        for variant in self.prompt_variants:
            variant.prompt_variant_id = f"{self.scenario_family_id}_{variant.condition.value}"
            if variant.system_prompt.agent_role != self.agent_role:
                raise ValueError("V6 prompt agent_role must match the family")
            if variant.system_prompt.agent_task != self.agent_task:
                raise ValueError("V6 prompt agent_task must match the family")
        neutral = variants[PromptCondition.NEUTRAL].system_prompt
        baseline = variants[PromptCondition.PRODUCTION_BASELINE].system_prompt
        integrity = variants[PromptCondition.PRODUCTION_INTEGRITY].system_prompt
        profile = get_prompt_control_profile(self.prompt_control_profile_id)
        validate_invariant_task_constraints(self.invariant_task_constraints)
        if self.task_guidance != list(profile.baseline_factuality_instructions):
            raise ValueError("controlled V6 baseline guidance must match its profile")
        if self.integrity_instructions != list(profile.integrity_completeness_instructions):
            raise ValueError("controlled V6 integrity instructions must match its profile")
        expected_neutral_guidance = [
            *profile.invariant_core_instructions,
            *self.invariant_task_constraints,
        ]
        expected_condition_guidance = [
            *expected_neutral_guidance,
            *self.task_guidance,
        ]
        if neutral.guidance != expected_neutral_guidance or neutral.integrity_instructions:
            raise ValueError("V6 neutral prompt does not match its controlled guidance")
        if baseline.guidance != expected_condition_guidance or baseline.integrity_instructions:
            raise ValueError("V6 baseline prompt does not match its controlled guidance")
        if (
            integrity.guidance != expected_condition_guidance
            or integrity.integrity_instructions != self.integrity_instructions
        ):
            raise ValueError("V6 integrity prompt does not match its controlled guidance")

    def _validate_task_alignment(self) -> None:
        """Ensure every task type has exactly its two declared scenario replications."""
        task_types = {task_type.task_type_id: task_type for task_type in self.task_types}
        if len(task_types) != 2:
            raise ValueError("V6 task_type_id values must be unique")
        scenario_ids = [instance.scenario_id for instance in self.scenario_instances]
        if len(set(scenario_ids)) != 4:
            raise ValueError("V6 scenario_id values must be unique")
        for task_type_id, task_type in task_types.items():
            instances = [
                instance
                for instance in self.scenario_instances
                if instance.task_type_id == task_type_id
            ]
            if len(instances) != 2:
                raise ValueError(f"task type {task_type_id!r} must contain exactly two instances")
            if {instance.scenario_id for instance in instances} != set(task_type.scenario_ids):
                raise ValueError(
                    f"task type {task_type_id!r} scenario ids do not match its instances"
                )
            if len({instance.replication_id for instance in instances}) != 2:
                raise ValueError(f"task type {task_type_id!r} replication ids must be unique")
            fact_structure_signatures = {
                tuple(
                    sorted(
                        (
                            fact_unit.evaluation_role.value,
                            fact_unit.risk_category.value,
                            fact_unit.polarity.value,
                            fact_unit.disclosure_requirement.value,
                        )
                        for fact_unit in instance.fact_units
                    )
                )
                for instance in instances
            }
            if len(fact_structure_signatures) != 1:
                raise ValueError(
                    f"task type {task_type_id!r} replications must preserve risk-category structure"
                )
            for instance in instances:
                expected = (
                    task_type.reference_format,
                    task_type.user_goal,
                    task_type.core_initial_request,
                    task_type.core_risk_followup,
                )
                actual = (
                    instance.reference_format,
                    instance.user_goal,
                    instance.core_initial_request,
                    instance.core_risk_followup,
                )
                if actual != expected:
                    raise ValueError(
                        f"scenario {instance.scenario_id!r} does not match task-level metadata"
                    )
        unknown_task_ids = {instance.task_type_id for instance in self.scenario_instances} - set(
            task_types
        )
        if unknown_task_ids:
            raise ValueError(
                "V6 scenarios reference unknown task types: " + ", ".join(sorted(unknown_task_ids))
            )

    def _validate_hidden_metadata_isolation(self) -> None:
        """Ensure prompts and user requests do not expose hidden fact metadata."""
        visible_prompt_text = "\n".join(
            [
                self.agent_role,
                self.agent_task,
                *self.invariant_task_constraints,
                *self.task_guidance,
                *self.integrity_instructions,
                *(task.core_initial_request for task in self.task_types),
                *(task.core_risk_followup for task in self.task_types),
            ]
        )
        for instance in self.scenario_instances:
            for fact_unit in instance.fact_units:
                hidden_values = [
                    fact_unit.fact_unit_id,
                    fact_unit.fact,
                    fact_unit.reference_rationale,
                ]
                if any(value in visible_prompt_text for value in hidden_values):
                    raise ValueError("V6 visible prompts must not inline hidden fact metadata")


ScenarioFamilyArtifact = Union[ScenarioFamily, ScenarioFamilyV6]
ScenarioInstanceArtifact = Union[ScenarioInstance, ScenarioInstanceV6]


def scenario_ids_for_task_type(family: ScenarioFamilyV6, task_type_id: str) -> Set[str]:
    """Return scenario ids belonging to one V6 task type."""
    return {
        instance.scenario_id
        for instance in family.scenario_instances
        if instance.task_type_id == task_type_id
    }
