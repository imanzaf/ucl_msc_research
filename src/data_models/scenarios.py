"""Pydantic models for financial deception scenario design."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaterialityLevel(str, Enum):
    """Classify how decision-relevant a risk fact is expected to be."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEUTRAL = "neutral"


class FinanceArea(str, Enum):
    """Classify the finance area represented by a scenario."""

    CAPITAL_MARKETS_DISCLOSURE = "capital_markets_disclosure"
    CREDIT_AND_LENDING = "credit_and_lending"


class NudgeLevel(str, Enum):
    """Classify how strongly the prompt pushes the model toward deception."""

    HIGH = "high"
    LOW = "low"
    ZERO = "zero"


class InteractionMode(str, Enum):
    """Classify whether the scenario is single-turn or multi-turn."""

    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"


class RiskUnit(BaseModel):
    """Describe one atomic risk fact that should be tracked during scoring."""

    model_config = ConfigDict(extra="forbid")

    risk_unit_id: str = Field(
        min_length=1,
        description="Stable identifier for tracking the risk fact during scoring.",
    )
    fact: str = Field(
        min_length=1,
        description="Atomic risk fact available to the model in the scenario context.",
    )
    materiality: MaterialityLevel = Field(
        description="Expected decision relevance of the risk fact.",
    )
    expected_disclosure: str = Field(
        min_length=1,
        description="Hidden scoring guidance describing adequate disclosure of the risk fact.",
    )
    materiality_rationale: str = Field(
        min_length=1,
        description="Hidden scoring rationale for the assigned materiality level.",
    )


class PromptVariant(BaseModel):
    """Describe one generated prompt variant for a scenario family."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(
        min_length=1,
        description="Identifier of the concrete scenario variant.",
    )
    nudge_level: NudgeLevel = Field(
        description="Controlled nudge-gradient level for this prompt variant.",
    )
    system_prompt: str = Field(
        min_length=1,
        description="System prompt for the financial-agent model.",
    )
    user_prompt: str = Field(
        min_length=1,
        description="User prompt for the financial-agent model.",
    )
    nudge_rationale: str = Field(
        min_length=1,
        description="Brief explanation of how this prompt implements the nudge level.",
    )


class SourceInspiration(BaseModel):
    """Record researcher-side benchmark inspiration that is not sent to the generator."""

    model_config = ConfigDict(extra="forbid")

    source_label: str = Field(
        min_length=1,
        description="Short label for the local benchmark source used as area inspiration.",
    )
    local_reference: str = Field(
        min_length=1,
        description="Local file, scenario id, or row reference inspected by the researcher.",
    )
    inspiration_note: str = Field(
        min_length=1,
        description="Brief note on the finance-area inspiration taken from the source.",
    )


class Scenario(BaseModel):
    """Define one generated scenario family with shared risk units and prompt variants."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="scenario.v1",
        description="Schema version for persisted scenario artifacts.",
    )
    scenario_family_id: str = Field(
        min_length=1,
        description="Identifier shared by the generated prompt variants.",
    )
    finance_area: FinanceArea = Field(
        description="Finance area represented by this scenario family.",
    )
    title: str = Field(
        min_length=1,
        description="Short human-readable title for the generated scenario family.",
    )
    generated_summary: str = Field(
        min_length=1,
        description="Generated summary of the scenario family and stakeholder decision context.",
    )
    interaction_mode: InteractionMode = Field(
        description="Whether the generated variants are single-turn or multi-turn.",
    )
    agent_role: str = Field(
        min_length=1,
        description="Shared role assigned to the financial-agent model.",
    )
    risk_units: List[RiskUnit] = Field(
        min_length=4,
        max_length=4,
        description="Exactly four shared risk units: high, medium, low, and neutral.",
    )
    prompt_variants: List[PromptVariant] = Field(
        min_length=3,
        max_length=3,
        description="Exactly three prompt variants: zero, low, and high nudge.",
    )
    source_inspiration: List[SourceInspiration] = Field(
        default_factory=list,
        description="Researcher-side source inspiration that was not sent to the LLM.",
    )

    @model_validator(mode="after")
    def validate_scenario_constraints(self) -> "Scenario":
        """Ensure generated scenario content matches benchmark design constraints."""
        self._validate_risk_units()
        self._validate_prompt_variants()
        return self

    def _validate_risk_units(self) -> None:
        """Ensure exactly one risk unit appears at each required materiality level."""
        materiality_counts: Dict[MaterialityLevel, int] = {
            MaterialityLevel.HIGH: 0,
            MaterialityLevel.MEDIUM: 0,
            MaterialityLevel.LOW: 0,
            MaterialityLevel.NEUTRAL: 0,
        }
        risk_unit_ids: List[str] = []
        for risk_unit in self.risk_units:
            materiality_counts[risk_unit.materiality] += 1
            risk_unit_ids.append(risk_unit.risk_unit_id)

        if any(count != 1 for count in materiality_counts.values()):
            raise ValueError(
                "risk_units must contain exactly one high, medium, low, and neutral unit"
            )
        if len(set(risk_unit_ids)) != len(risk_unit_ids):
            raise ValueError("risk_unit_id values must be unique within a scenario family")

    def _validate_prompt_variants(self) -> None:
        """Ensure prompt variants cover required nudges and deterministic scenario ids."""
        required_nudges = {NudgeLevel.ZERO, NudgeLevel.LOW, NudgeLevel.HIGH}
        variant_nudges = {variant.nudge_level for variant in self.prompt_variants}
        scenario_ids = [variant.scenario_id for variant in self.prompt_variants]

        if variant_nudges != required_nudges:
            raise ValueError("prompt_variants must contain exactly zero, low, and high nudges")
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("scenario_id values must be unique within a scenario family")

        expected_ids = {
            nudge_level: f"{self.scenario_family_id}_{nudge_level.value}"
            for nudge_level in required_nudges
        }
        actual_ids = {variant.nudge_level: variant.scenario_id for variant in self.prompt_variants}
        if actual_ids != expected_ids:
            raise ValueError("prompt variant scenario_id values must match <family>_<nudge>")
