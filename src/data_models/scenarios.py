"""Pydantic models for current financial risk-communication scenarios."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Dict, List, Set

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from src.data_models.prompt_controls import COMMON_INTEGRITY_INSTRUCTIONS, validate_task_constraints
from src.prompts.scenarios.agent_source_reference import SYSTEM_TEMPLATE


class FactPolarity(str, Enum):
    """Classify the valence and disclosure materiality of a generated fact unit."""

    HIGH_ADVERSE = "high_adverse"
    LOW_ADVERSE = "low_adverse"
    FAVORABLE = "favorable"
    NEUTRAL_DISTRACTOR = "neutral_distractor"


class FinanceSegment(str, Enum):
    """Classify the finance area represented by a scenario family."""

    RETAIL_WEALTH = "retail_wealth"
    PERSONAL_FINANCIAL_MANAGEMENT = "personal_financial_management"
    BRANCH_RELATIONSHIP_MANAGEMENT = "branch_relationship_management"
    INVESTMENT_RESEARCH = "investment_research"
    BANKING_ONBOARDING = "banking_onboarding"
    FRAUD_AND_SCAM = "fraud_and_scam"


class InteractionMode(str, Enum):
    """Classify whether the scenario is single-turn or multi-turn."""

    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"


class PromptCondition(str, Enum):
    """Classify the agent prompt condition used in the run matrix."""

    NEUTRAL = "neutral"
    PRODUCTION_BASELINE = "production_baseline"
    PRODUCTION_INTEGRITY = "production_integrity"


class RiskCategory(str, Enum):
    """Classify the broad financial risk category represented by a fact unit."""

    LIQUIDITY = "liquidity"
    MARKET = "market"
    CREDIT = "credit"
    CONCENTRATION = "concentration"
    SUITABILITY = "suitability"
    FEES_COSTS = "fees_costs"
    COMPLIANCE_LEGAL = "compliance_legal"
    OPERATIONAL = "operational"
    FRAUD = "fraud"
    PERFORMANCE = "performance"
    NEUTRAL = "neutral"


class DisclosureRequirement(str, Enum):
    """Classify how strongly a fact unit should be disclosed to preserve decision quality."""

    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    NOT_RELEVANT = "not_relevant"


class BeliefSupport(str, Enum):
    """Classify whether a possible user belief is supported by the generated fact pool."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"


class ScenarioTaskArchetype(str, Enum):
    """Classify the controlled task archetypes used in scenario families."""

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


class ScenarioReferenceFormat(str, Enum):
    """Classify the fixed finance-native source format for a task archetype."""

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
    """Classify how a fact contributes to omission evaluation."""

    PRIMARY_ADVERSE_TARGET = "primary_adverse_target"
    FAVORABLE_CONTROL = "favorable_control"
    NEUTRAL_CONTROL = "neutral_control"


class DisclosureCheckpoint(str, Enum):
    """Identify the transcript checkpoint at which a fact is evaluated."""

    INITIAL_RESPONSE = "initial_response"
    AFTER_RISK_FOLLOWUP = "after_risk_followup"


REQUIRED_FACT_ROLE_COUNTS: Dict[FactEvaluationRole, int] = {
    FactEvaluationRole.PRIMARY_ADVERSE_TARGET: 2,
    FactEvaluationRole.FAVORABLE_CONTROL: 2,
    FactEvaluationRole.NEUTRAL_CONTROL: 2,
}
REQUIRED_FACT_TOTAL = sum(REQUIRED_FACT_ROLE_COUNTS.values())


def normalize_instruction_list(value: object) -> object:
    """Convert legacy string instructions to the list representation used by current scenarios."""
    if not isinstance(value, str):
        return value
    if not value.strip():
        return []
    return [value.strip()]


def render_instruction_list(instructions: List[str]) -> str:
    """Render prompt instructions as a Markdown-style bullet list."""
    return "\n".join(f"- {instruction}" for instruction in instructions)


def validate_instruction_list(instructions: List[str]) -> List[str]:
    """Reject blank instruction items that would create malformed prompt lists."""
    if any(not instruction.strip() for instruction in instructions):
        raise ValueError("prompt instruction items must not be blank")
    return instructions


InstructionList = Annotated[
    List[str],
    BeforeValidator(normalize_instruction_list),
    AfterValidator(validate_instruction_list),
]


class PromptInstructions(BaseModel):
    """Separate the agent identity, task, and condition-specific guidance."""

    model_config = ConfigDict(extra="forbid")

    agent_role: str = Field(min_length=1, description="Role assigned to the agent model.")
    model_owner: str = Field(min_length=1, description="Organization operating the agent model.")
    agent_task: str = Field(min_length=1, description="Task the agent model should perform.")
    guidance: InstructionList = Field(
        default_factory=list,
        description="Condition-specific guidance; empty for the neutral prompt condition.",
    )
    integrity_instructions: InstructionList = Field(
        default_factory=list,
        description="Integrity instructions added only to the production-integrity condition.",
    )


class PromptVariant(BaseModel):
    """Describe one code-owned agent prompt condition."""

    model_config = ConfigDict(extra="forbid")

    prompt_variant_id: str = Field(
        default="",
        description="Identifier derived from family id and prompt condition.",
    )
    condition: PromptCondition = Field(description="Prompt condition represented by this variant.")
    system_prompt: PromptInstructions = Field(
        description="Structured system-prompt instructions rendered at execution time."
    )


class PromptTemplate(BaseModel):
    """Render agent prompts with one scenario-level context packet."""

    model_config = ConfigDict(extra="forbid")

    system_template: str = Field(
        default=SYSTEM_TEMPLATE,
        description="System prompt template populated with identity, task, guidance, and references.",
    )

    @model_validator(mode="after")
    def validate_template_placeholders(self) -> "PromptTemplate":
        """Ensure templates contain the placeholders required for deterministic rendering."""
        for placeholder in [
            "{agent_role}",
            "{model_owner}",
            "{agent_task}",
            "{guidance_block}",
            "{reference_text}",
        ]:
            if placeholder not in self.system_template:
                raise ValueError(f"system_template must contain {placeholder}")
        return self

    def render_guidance_block(self, instructions: PromptInstructions) -> str:
        """Render optional guidance and integrity blocks as prompt-ready lists."""
        blocks: List[str] = []
        if instructions.guidance:
            blocks.append(f"Guidance:\n{render_instruction_list(instructions.guidance)}")
        if instructions.integrity_instructions:
            blocks.append(
                "Integrity instructions:\n"
                f"{render_instruction_list(instructions.integrity_instructions)}"
            )
        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n\n"

    def render_system_prompt(self, instructions: PromptInstructions, reference_text: str) -> str:
        """Render a system prompt by injecting the complete scenario agent context."""
        return self.system_template.format(
            agent_role=instructions.agent_role,
            model_owner=instructions.model_owner,
            agent_task=instructions.agent_task,
            guidance_block=self.render_guidance_block(instructions),
            reference_text=reference_text,
        )


class UserAction(BaseModel):
    """Describe one action option available for downstream user-harm measurement."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(
        min_length=1, description="Stable identifier for this possible user action."
    )
    label: str = Field(min_length=1, description="Short action label.")
    description: str = Field(
        min_length=1, description="Plain-language description of the possible action."
    )
    is_harmful: bool = Field(
        description="Whether taking this action would be harmful given the full fact pool."
    )


class UserBelief(BaseModel):
    """Describe one belief option available for downstream user-harm measurement."""

    model_config = ConfigDict(extra="forbid")

    belief_id: str = Field(
        min_length=1, description="Stable identifier for this possible user belief."
    )
    belief: str = Field(
        min_length=1, description="Belief the user might reasonably hold after a conversation."
    )
    supported_by_fact_pool: BeliefSupport = Field(
        description="Whether the full generated fact pool supports the belief."
    )


class FactUnit(BaseModel):
    """Describe one controlled fact with explicit evaluation and source metadata."""

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
        description="Primary target or control role in evaluation."
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
    def validate_evaluation_role(self) -> "FactUnit":
        """Ensure role, polarity, pair, and checkpoint metadata are mutually consistent."""
        if not self.source_locator.strip():
            raise ValueError("facts require a non-blank source_locator")
        if any(not marker.strip() for marker in self.specificity_markers):
            raise ValueError("specificity markers must be non-blank")
        if self.contains_minimising_language or self.contains_benefit_amplifying_language:
            raise ValueError("source facts must use neutral wording")

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
                raise ValueError("primary adverse targets must use both checkpoints in order")
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


def validate_fact_units(fact_units: List[FactUnit]) -> None:
    """Ensure facts have the required roles, unique ids, and matched comparison pairs."""
    role_counts = {role: 0 for role in REQUIRED_FACT_ROLE_COUNTS}
    for fact_unit in fact_units:
        role_counts[fact_unit.evaluation_role] += 1
    violations = [
        f"{role.value}: expected {required}, got {role_counts[role]}"
        for role, required in REQUIRED_FACT_ROLE_COUNTS.items()
        if role_counts[role] != required
    ]
    if violations:
        raise ValueError("fact-role counts do not match requirements: " + "; ".join(violations))

    fact_ids = [fact_unit.fact_unit_id for fact_unit in fact_units]
    if len(set(fact_ids)) != len(fact_ids):
        raise ValueError("fact_unit_id values must be unique within a scenario")

    paired_units: Dict[str, List[FactUnit]] = {}
    for fact_unit in fact_units:
        if fact_unit.comparison_pair_id:
            paired_units.setdefault(fact_unit.comparison_pair_id, []).append(fact_unit)
    if len(paired_units) != 2:
        raise ValueError("scenarios must contain exactly two comparison pairs")
    expected_pair_roles = {
        FactEvaluationRole.PRIMARY_ADVERSE_TARGET,
        FactEvaluationRole.FAVORABLE_CONTROL,
    }
    for pair_id, units in paired_units.items():
        if len(units) != 2 or {unit.evaluation_role for unit in units} != expected_pair_roles:
            raise ValueError(
                f"comparison pair {pair_id!r} must contain one adverse target and one favorable control"
            )


class GeneratedScenarioInstance(BaseModel):
    """Define generated fields for one controlled scenario instance."""

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
    fact_units: List[FactUnit] = Field(
        min_length=REQUIRED_FACT_TOTAL,
        max_length=REQUIRED_FACT_TOTAL,
        description="Exactly six controlled facts.",
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
    def validate_generated_instance(self) -> "GeneratedScenarioInstance":
        """Ensure a generated instance satisfies structural and leakage constraints."""
        validate_fact_units(self.fact_units)
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
            raise ValueError("action_id values must be unique within a scenario")
        if {action.is_harmful for action in self.possible_user_actions} != {False, True}:
            raise ValueError("actions must include harmful and non-harmful options")

        belief_ids = [belief.belief_id for belief in self.possible_user_beliefs]
        if len(set(belief_ids)) != len(belief_ids):
            raise ValueError("belief_id values must be unique within a scenario")
        support_values = {belief.supported_by_fact_pool for belief in self.possible_user_beliefs}
        if support_values != {
            BeliefSupport.SUPPORTED,
            BeliefSupport.PARTIALLY_SUPPORTED,
            BeliefSupport.UNSUPPORTED,
        }:
            raise ValueError("beliefs must include supported, partial, and unsupported options")
        return self


class ScenarioInstance(GeneratedScenarioInstance):
    """Define one persisted instance with seed-owned task and replication metadata."""

    scenario_id: str = Field(min_length=1, description="Stable scenario identifier.")
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


class ScenarioTaskType(BaseModel):
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
    def validate_scenario_ids(self) -> "ScenarioTaskType":
        """Ensure the task type names two unique replications."""
        if len(set(self.scenario_ids)) != 2:
            raise ValueError("task-type scenario_ids must be unique")
        return self


class ScenarioSeedReplication(BaseModel):
    """Describe seed-owned metadata for one task replication."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, description="Stable replication scenario id.")
    replication_id: str = Field(
        min_length=1, description="Replication identifier such as R1 or R2."
    )
    variation_brief: str = Field(
        min_length=1, description="Controlled fictional variation to generate."
    )


class ScenarioSeedTaskType(BaseModel):
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
    replications: List[ScenarioSeedReplication] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two matched replications for this task type.",
    )

    @model_validator(mode="after")
    def validate_replications(self) -> "ScenarioSeedTaskType":
        """Ensure replication ids and scenario ids are unique within a task type."""
        scenario_ids = [replication.scenario_id for replication in self.replications]
        replication_ids = [replication.replication_id for replication in self.replications]
        if len(set(scenario_ids)) != 2 or len(set(replication_ids)) != 2:
            raise ValueError(
                "task replications must have unique scenario_id and replication_id values"
            )
        return self


class ScenarioSeed(BaseModel):
    """Describe seed-owned inputs shared by the current four-scenario protocol."""

    model_config = ConfigDict(extra="forbid")

    scenario_family_id: str = Field(min_length=1, description="Stable family identifier.")
    segment: FinanceSegment = Field(description="Finance segment represented by the family.")
    interaction_mode: InteractionMode = Field(description="Interaction mode used by the family.")
    tool_using: bool = Field(description="Whether tool-use scaffolding is required.")
    agent_role: str = Field(min_length=1, description="Role assigned to the agent model.")
    model_owner: str = Field(min_length=1, description="Organization operating the agent model.")
    agent_task: str = Field(min_length=1, description="Task assigned to the agent model.")
    task_constraints: List[str] = Field(
        min_length=2,
        max_length=2,
        description="Domain and authority constraints included in both production conditions.",
    )
    user_role: str = Field(min_length=1, description="Role represented by the simulated user.")
    task_types: List[ScenarioSeedTaskType] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two controlled task types.",
    )

    @model_validator(mode="after")
    def validate_seed(self) -> "ScenarioSeed":
        """Require unique task identifiers, scenario identifiers, and valid task constraints."""
        validate_task_constraints(self.task_constraints)
        task_ids = [task_type.task_type_id for task_type in self.task_types]
        if len(set(task_ids)) != 2:
            raise ValueError("task_type_id values must be unique")
        scenario_ids = [
            replication.scenario_id
            for task_type in self.task_types
            for replication in task_type.replications
        ]
        if len(set(scenario_ids)) != 4:
            raise ValueError("scenario_id values must be unique across the family")
        return self


class ScenarioSeedCollection(BaseModel):
    """Store the current seed collection crossing the JSON boundary."""

    model_config = ConfigDict(extra="forbid")

    seeds: List[ScenarioSeed] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_collection(self) -> "ScenarioSeedCollection":
        """Require unique families across the seed collection."""
        family_ids = [seed.scenario_family_id for seed in self.seeds]
        if len(set(family_ids)) != len(family_ids):
            raise ValueError("seed family ids must be unique")
        return self


class ScenarioFamily(BaseModel):
    """Define one persisted family with two task types and four matched scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenario_family_id: str = Field(min_length=1, description="Stable family identifier.")
    segment: FinanceSegment = Field(description="Finance segment represented by the family.")
    interaction_mode: InteractionMode = Field(description="Interaction mode used by the family.")
    tool_using: bool = Field(description="Whether tool-use scaffolding is required.")
    agent_role: str = Field(min_length=1, description="Role assigned to the agent model.")
    model_owner: str = Field(min_length=1, description="Organization operating the agent model.")
    agent_task: str = Field(min_length=1, description="Task assigned to the agent model.")
    task_constraints: List[str] = Field(
        min_length=2,
        max_length=2,
        description="Domain and authority constraints shared by both production conditions.",
    )
    integrity_instructions: List[str] = Field(
        min_length=1, description="Integrity-condition guidance."
    )
    user_role: str = Field(min_length=1, description="Role represented by the simulated user.")
    task_types: List[ScenarioTaskType] = Field(
        min_length=2,
        max_length=2,
        description="Exactly two controlled task types.",
    )
    scenario_instances: List[ScenarioInstance] = Field(
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
    def validate_family(self) -> "ScenarioFamily":
        """Ensure prompt conditions and task-replication alignment match the current protocol."""
        if self.interaction_mode != InteractionMode.MULTI_TURN:
            raise ValueError("families require the scripted multi-turn risk follow-up")
        required_conditions = {
            PromptCondition.NEUTRAL,
            PromptCondition.PRODUCTION_BASELINE,
            PromptCondition.PRODUCTION_INTEGRITY,
        }
        if {variant.condition for variant in self.prompt_variants} != required_conditions:
            raise ValueError("prompt_variants must contain all three prompt conditions")
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
                raise ValueError("prompt agent_role must match the family")
            if variant.system_prompt.model_owner != self.model_owner:
                raise ValueError("prompt model_owner must match the family")
            if variant.system_prompt.agent_task != self.agent_task:
                raise ValueError("prompt agent_task must match the family")
        neutral = variants[PromptCondition.NEUTRAL].system_prompt
        baseline = variants[PromptCondition.PRODUCTION_BASELINE].system_prompt
        integrity = variants[PromptCondition.PRODUCTION_INTEGRITY].system_prompt
        validate_task_constraints(self.task_constraints)
        if self.integrity_instructions != list(COMMON_INTEGRITY_INSTRUCTIONS):
            raise ValueError("controlled integrity instructions must match the common block")
        if neutral.guidance or neutral.integrity_instructions:
            raise ValueError("neutral prompt does not match its controlled guidance")
        if baseline.guidance != self.task_constraints or baseline.integrity_instructions:
            raise ValueError("baseline prompt does not match its controlled guidance")
        if (
            integrity.guidance != self.task_constraints
            or integrity.integrity_instructions != self.integrity_instructions
        ):
            raise ValueError("integrity prompt does not match its controlled guidance")

    def _validate_task_alignment(self) -> None:
        """Ensure every task type has exactly its two declared scenario replications."""
        task_types = {task_type.task_type_id: task_type for task_type in self.task_types}
        if len(task_types) != 2:
            raise ValueError("task_type_id values must be unique")
        scenario_ids = [instance.scenario_id for instance in self.scenario_instances]
        if len(set(scenario_ids)) != 4:
            raise ValueError("scenario_id values must be unique")
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
                "scenarios reference unknown task types: " + ", ".join(sorted(unknown_task_ids))
            )

    def _validate_hidden_metadata_isolation(self) -> None:
        """Ensure prompts and user requests do not expose hidden fact metadata."""
        visible_prompt_text = "\n".join(
            [
                self.agent_role,
                self.model_owner,
                self.agent_task,
                *self.task_constraints,
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
                    raise ValueError("visible prompts must not inline hidden fact metadata")


def scenario_ids_for_task_type(family: ScenarioFamily, task_type_id: str) -> Set[str]:
    """Return scenario ids belonging to one task type."""
    return {
        instance.scenario_id
        for instance in family.scenario_instances
        if instance.task_type_id == task_type_id
    }
