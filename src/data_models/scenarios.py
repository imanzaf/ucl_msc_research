"""Pydantic models for canonical financial risk-communication scenario generation."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Dict, List

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from src.prompts.scenarios.agent_source_reference import SYSTEM_TEMPLATE


class FactPolarity(str, Enum):
    """Classify the valence and disclosure materiality of a generated fact unit."""

    HIGH_ADVERSE = "high_adverse"
    LOW_ADVERSE = "low_adverse"
    FAVORABLE = "favorable"
    NEUTRAL_DISTRACTOR = "neutral_distractor"


REQUIRED_FACT_UNIT_COUNTS: Dict[FactPolarity, int] = {
    FactPolarity.HIGH_ADVERSE: 2,
    FactPolarity.LOW_ADVERSE: 2,
    FactPolarity.FAVORABLE: 2,
    FactPolarity.NEUTRAL_DISTRACTOR: 2,
}
REQUIRED_FACT_UNIT_TOTAL = sum(REQUIRED_FACT_UNIT_COUNTS.values())

REQUIRED_PERSONA_PROMPT_KEYS = [
    "neutral_baseline",
    "anxious_risk_averse",
    "positive_risk_seeking",
]


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


def validate_required_fact_units(fact_units: List["FactUnit"]) -> None:
    """Ensure fact units match the required polarity counts and have unique identifiers."""
    polarity_counts: Dict[FactPolarity, int] = {
        polarity: 0 for polarity in REQUIRED_FACT_UNIT_COUNTS
    }
    fact_unit_ids: List[str] = []
    for fact_unit in fact_units:
        if fact_unit.polarity not in polarity_counts:
            raise ValueError(f"unexpected fact unit polarity: {fact_unit.polarity!r}")
        polarity_counts[fact_unit.polarity] += 1
        fact_unit_ids.append(fact_unit.fact_unit_id)

    violations = [
        f"{polarity.value}: expected {required}, got {polarity_counts[polarity]}"
        for polarity, required in REQUIRED_FACT_UNIT_COUNTS.items()
        if polarity_counts[polarity] != required
    ]
    if violations:
        raise ValueError("fact-unit counts do not match requirements: " + "; ".join(violations))
    if len(set(fact_unit_ids)) != len(fact_unit_ids):
        raise ValueError("fact_unit_id values must be unique within a scenario instance")


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
    """Classify the agent prompt condition used in the 3x3 run matrix."""

    NEUTRAL = "neutral"
    PRODUCTION_BASELINE = "production_baseline"
    PRODUCTION_INTEGRITY = "production_integrity"


class ScenarioSchemaVersion(str, Enum):
    """Identify the canonical persisted scenario-family schema."""

    V5 = "scenario_family.v5"
    V6 = "scenario_family.v6"


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


class FactUnit(BaseModel):
    """Describe one hidden atomic fact derived from the scenario agent context."""

    model_config = ConfigDict(extra="forbid")

    fact_unit_id: str = Field(
        min_length=1,
        description="Stable identifier for tracking the fact during scoring.",
    )
    fact: str = Field(
        min_length=1,
        description="Atomic fact derived from the agent context.",
    )
    reference_rationale: str = Field(
        min_length=1,
        description="Hidden rationale identifying where and how the agent context supports the fact.",
    )
    polarity: FactPolarity = Field(
        description="Valence and disclosure materiality of the fact unit.",
    )
    risk_category: RiskCategory = Field(
        description="Broad finance-risk category represented by the fact unit.",
    )
    disclosure_requirement: DisclosureRequirement = Field(
        description="Controlled disclosure label used during hidden scoring.",
    )
    expected_disclosure: str = Field(
        min_length=1,
        description="Hidden scoring guidance describing adequate disclosure of the fact.",
    )
    specificity_markers: List[str] = Field(
        default_factory=list,
        description=(
            "Risk-material quantitative details that should be preserved for accurate disclosure, "
            "such as amounts, percentages, rates, ratios, counts, limits, thresholds, balances, or durations."
        ),
    )
    contains_minimising_language: bool = Field(
        description="Whether the reference wording supporting this fact uses risk-softening language.",
    )
    contains_benefit_amplifying_language: bool = Field(
        description="Whether the reference wording supporting this fact uses promotional wording.",
    )


class PromptInstructions(BaseModel):
    """Separate the agent role, task, and condition-specific guidance."""

    model_config = ConfigDict(extra="forbid")

    agent_role: str = Field(
        min_length=1,
        description="Role assigned to the agent model.",
    )
    agent_task: str = Field(
        min_length=1,
        description="Task the agent model should perform.",
    )
    guidance: InstructionList = Field(
        default_factory=list,
        description="Condition-specific guidance; empty for the neutral prompt condition.",
    )
    integrity_instructions: InstructionList = Field(
        default_factory=list,
        description="Seed-owned integrity instructions added only to the production-integrity condition.",
    )


class PromptVariant(BaseModel):
    """Describe one code-owned agent prompt condition."""

    model_config = ConfigDict(extra="forbid")

    prompt_variant_id: str = Field(
        default="",
        description="Identifier derived from family id and prompt condition.",
    )
    condition: PromptCondition = Field(
        description="Prompt condition represented by this variant.",
    )
    system_prompt: PromptInstructions = Field(
        description="Structured system-prompt instructions rendered at execution time.",
    )


class PromptTemplate(BaseModel):
    """Render agent prompts with one scenario-level context packet."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(
        default="single_reference_prompt_v2",
        description="Stable identifier for the canonical prompt rendering template.",
    )
    system_template: str = Field(
        default=SYSTEM_TEMPLATE,
        description="System prompt template populated with role, task, guidance, and references.",
    )

    @model_validator(mode="after")
    def validate_template_placeholders(self) -> "PromptTemplate":
        """Ensure templates contain the placeholders required for deterministic rendering."""
        for placeholder in [
            "{agent_role}",
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

    def render_system_prompt(
        self,
        instructions: PromptInstructions,
        reference_text: str,
    ) -> str:
        """Render a system prompt by injecting the complete scenario agent context."""
        return self.system_template.format(
            agent_role=instructions.agent_role,
            agent_task=instructions.agent_task,
            guidance_block=self.render_guidance_block(instructions),
            reference_text=reference_text,
        )


class UserAction(BaseModel):
    """Describe one action option available for downstream user-harm measurement."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(
        min_length=1,
        description="Stable identifier for this possible user action.",
    )
    label: str = Field(
        min_length=1,
        description="Short action label.",
    )
    description: str = Field(
        min_length=1,
        description="Plain-language description of the possible action.",
    )
    is_harmful: bool = Field(
        description="Whether taking this action would be harmful given the full fact pool.",
    )


class UserBelief(BaseModel):
    """Describe one belief option available for downstream user-harm measurement."""

    model_config = ConfigDict(extra="forbid")

    belief_id: str = Field(
        min_length=1,
        description="Stable identifier for this possible user belief.",
    )
    belief: str = Field(
        min_length=1,
        description="Belief the user might reasonably hold after a conversation.",
    )
    supported_by_fact_pool: BeliefSupport = Field(
        description="Whether the full generated fact pool supports the belief.",
    )


class InitialUserPrompt(BaseModel):
    """Describe persona-matched first user prompts for one generated scenario instance."""

    model_config = ConfigDict(extra="forbid")

    neutral_baseline: str = Field(
        min_length=1,
        description="First user prompt for the neutral baseline persona.",
    )
    anxious_risk_averse: str = Field(
        min_length=1,
        description="First user prompt for the anxious risk-averse persona.",
    )
    positive_risk_seeking: str = Field(
        min_length=1,
        description="First user prompt for the positive risk-seeking persona.",
    )


class GeneratedScenarioInstance(BaseModel):
    """Define LLM-generated fields for one scenario instance before seed metadata is added."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1,
        description="Short human-readable title for this scenario instance.",
    )
    generated_summary: str = Field(
        min_length=1,
        description="One- to two-sentence summary of the user goal and decision context.",
    )
    reference_text: str = Field(
        min_length=1,
        description="Complete agent-visible source context in its realistic native presentation.",
    )
    fact_units: List[FactUnit] = Field(
        min_length=REQUIRED_FACT_UNIT_TOTAL,
        max_length=REQUIRED_FACT_UNIT_TOTAL,
        description="Exactly the number of fact units required by REQUIRED_FACT_UNIT_COUNTS.",
    )
    user_facing_context: List[str] = Field(
        min_length=1,
        description="Context known to the user simulator but not directly shown to the agent.",
    )
    possible_user_actions: List[UserAction] = Field(
        min_length=2,
        description="Action options used later to measure user harm.",
    )
    possible_user_beliefs: List[UserBelief] = Field(
        min_length=3,
        description="Belief options used later to measure user harm.",
    )
    initial_user_prompt: InitialUserPrompt = Field(
        description="Persona-matched first user prompts keyed by reusable persona id.",
    )

    @model_validator(mode="after")
    def validate_generated_instance_constraints(self) -> "GeneratedScenarioInstance":
        """Ensure generated scenario-instance content matches canonical benchmark constraints."""
        validate_required_fact_units(self.fact_units)
        self._validate_reference_excludes_fact_unit_ids()
        self._validate_user_harm_spaces()
        self._validate_initial_user_prompt()
        return self

    def _validate_reference_excludes_fact_unit_ids(self) -> None:
        """Prevent hidden fact identifiers from leaking into the agent-visible source context."""
        for fact_unit in self.fact_units:
            identifier_pattern = (
                rf"(?<![A-Za-z0-9_]){re.escape(fact_unit.fact_unit_id)}(?![A-Za-z0-9_])"
            )
            if re.search(identifier_pattern, self.reference_text, flags=re.IGNORECASE):
                raise ValueError("reference_text must not expose hidden fact_unit_id values")

    def _validate_user_harm_spaces(self) -> None:
        """Ensure generated action and belief spaces are useful for downstream harm measurement."""
        action_ids = [action.action_id for action in self.possible_user_actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action_id values must be unique within a scenario instance")

        action_harm_values = {action.is_harmful for action in self.possible_user_actions}
        if action_harm_values != {False, True}:
            raise ValueError("possible_user_actions must include harmful and non-harmful options")

        belief_ids = [belief.belief_id for belief in self.possible_user_beliefs]
        if len(set(belief_ids)) != len(belief_ids):
            raise ValueError("belief_id values must be unique within a scenario instance")

        belief_support_values = {
            belief.supported_by_fact_pool for belief in self.possible_user_beliefs
        }
        required_support_values = {
            BeliefSupport.SUPPORTED,
            BeliefSupport.PARTIALLY_SUPPORTED,
            BeliefSupport.UNSUPPORTED,
        }
        if belief_support_values != required_support_values:
            raise ValueError(
                "possible_user_beliefs must include supported, partially_supported, and unsupported beliefs"
            )

    def _validate_initial_user_prompt(self) -> None:
        """Ensure first-user prompts are keyed exactly by the reusable persona ids."""
        prompt_values = self.initial_user_prompt.model_dump()
        actual_keys = set(prompt_values)
        expected_keys = set(REQUIRED_PERSONA_PROMPT_KEYS)
        if actual_keys != expected_keys:
            raise ValueError(
                "initial_user_prompt must contain exactly neutral_baseline, anxious_risk_averse, and positive_risk_seeking"
            )
        empty_keys = [key for key, value in prompt_values.items() if not value.strip()]
        if empty_keys:
            raise ValueError("initial_user_prompt values must be non-empty")


class ScenarioInstance(GeneratedScenarioInstance):
    """Define one persisted scenario instance with seed-owned user goal metadata."""

    scenario_id: str = Field(
        min_length=1,
        description="Identifier for this generated scenario instance.",
    )
    user_goal: str = Field(
        min_length=1,
        description="Seed-owned user goal that conditions this scenario instance.",
    )


class ScenarioFamily(BaseModel):
    """Define one persisted canonical scenario family containing five generated instances."""

    model_config = ConfigDict(extra="forbid")

    schema_version: ScenarioSchemaVersion = Field(
        default=ScenarioSchemaVersion.V5,
        description="Schema version for persisted canonical scenario-family artifacts.",
    )
    scenario_family_id: str = Field(
        min_length=1,
        description="Identifier shared by all generated scenario instances.",
    )
    segment: FinanceSegment = Field(
        description="Finance area represented by this scenario family.",
    )
    interaction_mode: InteractionMode = Field(
        description="Whether the generated instances are single-turn or multi-turn.",
    )
    tool_using: bool = Field(
        description="Whether this scenario family requires tool-use scaffolding.",
    )
    agent_role: str = Field(
        min_length=1,
        description="Role assigned to the agent model.",
    )
    agent_task: str = Field(
        min_length=1,
        description="Task the agent model should perform.",
    )
    task_guidance: InstructionList = Field(
        min_length=1,
        description="Seed-owned production-baseline guidance.",
    )
    integrity_instructions: InstructionList = Field(
        min_length=1,
        description="Seed-owned integrity instructions for the production-integrity condition.",
    )
    user_role: str = Field(
        min_length=1,
        description="Role assigned to the user-side simulator.",
    )
    scenario_instances: List[ScenarioInstance] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five generated scenario instances for this family.",
    )
    prompt_variants: List[PromptVariant] = Field(
        min_length=3,
        max_length=3,
        description="Exactly three prompt conditions: neutral, production baseline, and production integrity.",
    )
    prompt_template: PromptTemplate = Field(
        default_factory=PromptTemplate,
        description="Code-owned template used to render prompt variants with the scenario reference.",
    )

    @model_validator(mode="after")
    def validate_family_constraints(self) -> "ScenarioFamily":
        """Ensure the persisted family artifact matches the canonical scenario-generation design."""
        self._validate_prompt_variants()
        self._validate_scenario_instance_ids()
        self._validate_prompt_fields_exclude_generated_evidence()
        return self

    def _validate_prompt_variants(self) -> None:
        """Ensure prompt variants cover the three required prompt conditions."""
        required_conditions = {
            PromptCondition.NEUTRAL,
            PromptCondition.PRODUCTION_BASELINE,
            PromptCondition.PRODUCTION_INTEGRITY,
        }
        variant_conditions = {variant.condition for variant in self.prompt_variants}
        if variant_conditions != required_conditions:
            raise ValueError(
                "prompt_variants must contain exactly neutral, production_baseline, and production_integrity"
            )
        variants_by_condition = {variant.condition: variant for variant in self.prompt_variants}
        for variant in self.prompt_variants:
            variant.prompt_variant_id = f"{self.scenario_family_id}_{variant.condition.value}"
            if variant.system_prompt.agent_role != self.agent_role:
                raise ValueError("prompt variant agent_role must match the scenario family")
            if variant.system_prompt.agent_task != self.agent_task:
                raise ValueError("prompt variant agent_task must match the scenario family")

        neutral = variants_by_condition[PromptCondition.NEUTRAL].system_prompt
        baseline = variants_by_condition[PromptCondition.PRODUCTION_BASELINE].system_prompt
        integrity = variants_by_condition[PromptCondition.PRODUCTION_INTEGRITY].system_prompt
        if neutral.guidance or neutral.integrity_instructions:
            raise ValueError(
                "neutral prompt variant must not contain guidance or integrity instructions"
            )
        if baseline.guidance != self.task_guidance or baseline.integrity_instructions:
            raise ValueError("production-baseline prompt must contain only family task guidance")
        if (
            integrity.guidance != self.task_guidance
            or integrity.integrity_instructions != self.integrity_instructions
        ):
            raise ValueError("production-integrity prompt must contain all family instructions")

    def _validate_scenario_instance_ids(self) -> None:
        """Ensure generated scenario instance ids are unique within the family."""
        scenario_ids = [instance.scenario_id for instance in self.scenario_instances]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("scenario_id values must be unique within a scenario family")

    def _validate_prompt_fields_exclude_generated_evidence(self) -> None:
        """Ensure prompt variants do not inline generated evidence or hidden fact identifiers."""
        prompt_texts: List[str] = []
        for variant in self.prompt_variants:
            prompt_texts.extend(
                [
                    variant.system_prompt.agent_role,
                    variant.system_prompt.agent_task,
                    *variant.system_prompt.guidance,
                    *variant.system_prompt.integrity_instructions,
                ]
            )
        combined_prompt_text = "\n".join(prompt_texts)
        for instance in self.scenario_instances:
            if instance.reference_text in combined_prompt_text:
                raise ValueError("prompt variants must not inline scenario reference text")
            for fact_unit in instance.fact_units:
                if (
                    fact_unit.fact_unit_id in combined_prompt_text
                    or fact_unit.fact in combined_prompt_text
                    or fact_unit.reference_rationale in combined_prompt_text
                ):
                    raise ValueError("prompt variants must not inline hidden fact-unit metadata")


class ScenarioSeedScenario(BaseModel):
    """Describe one seed-owned user goal for a generated scenario instance."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(
        min_length=1,
        description="Identifier for the generated scenario instance.",
    )
    user_goal: str = Field(
        min_length=1,
        description="Seed-owned goal the user pursues in this scenario instance.",
    )


class ScenarioSeed(BaseModel):
    """Describe seed data that is allowed to condition canonical scenario generation."""

    model_config = ConfigDict(extra="forbid")

    scenario_family_id: str = Field(
        min_length=1,
        description="Scenario family identifier.",
    )
    segment: FinanceSegment = Field(
        description="Hardcoded segment for this scenario family.",
    )
    interaction_mode: InteractionMode = Field(
        description="Hardcoded interaction mode for this scenario family.",
    )
    tool_using: bool = Field(
        description="Whether this seed requires tool-use scaffolding.",
    )
    agent_role: str = Field(
        min_length=1,
        description="Seed-controlled role assigned to the agent model.",
    )
    agent_task: str = Field(
        min_length=1,
        description="Seed-controlled task used in all prompt conditions.",
    )
    task_guidance: InstructionList = Field(
        min_length=1,
        description="Seed-owned production-baseline guidance.",
    )
    integrity_instructions: InstructionList = Field(
        min_length=1,
        description="Seed-owned integrity instructions for the production-integrity condition.",
    )
    user_role: str = Field(
        min_length=1,
        description="Seed-controlled stakeholder role for the user-side simulator.",
    )
    scenarios: List[ScenarioSeedScenario] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five seed-owned user goals for this scenario family.",
    )
