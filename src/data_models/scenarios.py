"""Pydantic models for financial deception scenario design."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaterialityLevel(str, Enum):
    """Classify how decision-relevant a risk fact is expected to be."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEUTRAL = "neutral"


class NudgeLevel(str, Enum):
    """Classify how strongly the prompt pushes the model toward deception."""

    HIGH = "high"
    LOW = "low"
    ZERO = "zero"


class FalsifiabilityLevel(str, Enum):
    """Classify the controlled scenario variant on the deception falsifiability gradient."""

    NOT_APPLICABLE = "not_applicable"
    FALSE_CLAIM = "false_claim"
    SELECTIVE_OMISSION = "selective_omission"
    MISLEADING_FRAMING = "misleading_framing"


class UserEmotion(str, Enum):
    """Classify the emotional state used to condition the user simulator."""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    EXCITED = "excited"
    ANXIOUS = "anxious"
    FRUSTRATED = "frustrated"
    ANGRY = "angry"


class EmotionIntensity(str, Enum):
    """Classify the intensity of the user simulator's emotional state."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PersonalityTrait(str, Enum):
    """Classify personality traits used to condition the user simulator."""

    NEUTRAL = "neutral"
    TRUSTING = "trusting"
    SKEPTICAL = "skeptical"
    RISK_AVERSE = "risk_averse"
    RISK_SEEKING = "risk_seeking"
    DETAIL_ORIENTED = "detail_oriented"
    TIME_PRESSURED = "time_pressured"
    OVERCONFIDENT = "overconfident"


class InteractionMode(str, Enum):
    """Classify whether the scenario is single-turn or multi-turn."""

    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"


class BenchmarkSource(str, Enum):
    """Classify the external benchmark or origin used to derive a scenario."""

    # TODO: verify and confirm benchmark sources
    ORIGINAL = "original"


class UserPersona(BaseModel):
    """Describe a reusable user-simulator persona interacting with the financial agent."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(
        min_length=1,
        description="Stable identifier for reusing the persona across scenarios.",
    )
    stakeholder_role: str = Field(
        min_length=1,
        description="Audience whose beliefs or decisions may be affected by the output.",
    )
    emotion: UserEmotion = Field(
        description="Emotional state used to condition the user-side simulator.",
    )
    emotion_intensity: EmotionIntensity = Field(
        description="Intensity of the user-side simulator's emotional state.",
    )
    primary_personality_trait: PersonalityTrait = Field(
        description="Primary personality trait used to condition the user-side simulator.",
    )
    secondary_personality_traits: List[PersonalityTrait] = Field(
        default_factory=list,
        description="Additional personality traits used to condition the user-side simulator.",
    )
    user_goal: str = Field(
        min_length=1,
        description="Goal the user-side simulator pursues during the scenario.",
    )
    communication_style: str = Field(
        min_length=1,
        description="How the user-side simulator should phrase messages.",
    )


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


class PromptExecutionSpec(BaseModel):
    """Describe the prompt context used to execute a scenario."""

    model_config = ConfigDict(extra="forbid")

    agent_role: str = Field(
        min_length=1,
        description="Role assigned to the financial-agent model.",
    )
    max_turns: int = Field(
        ge=1,
        description="Maximum number of conversation turns for executing the scenario.",
    )


class BenchmarkProvenance(BaseModel):
    """Describe whether and how a scenario was derived from an existing benchmark."""

    model_config = ConfigDict(extra="forbid")

    source: BenchmarkSource = Field(
        default=BenchmarkSource.ORIGINAL,
        description="Benchmark or origin that the scenario is derived from.",
    )
    source_id: Optional[str] = Field(
        default=None,
        description="Original benchmark row, task, paper identifier, or scenario id if available.",
    )
    adaptation_notes: Optional[str] = Field(
        default=None,
        description="Brief note on how the original source was transformed for this benchmark.",
    )


class ScenarioSpec(BaseModel):
    """Define one controlled scenario variant for the financial deception benchmark."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="scenario_spec.v1",
        description="Schema version for persisted scenario records.",
    )
    scenario_id: str = Field(
        min_length=1,
        description="Unique identifier for this concrete scenario variant.",
    )
    scenario_family_id: str = Field(
        min_length=1,
        description="Identifier shared by paired variants built from the same underlying scenario.",
    )
    title: str = Field(
        min_length=1,
        description="Short human-readable scenario title.",
    )
    interaction_mode: InteractionMode = Field(
        description="Whether the scenario is single-turn or multi-turn.",
    )
    user_persona: UserPersona = Field(
        description="Persona details for the user interacting with the agent.",
    )
    prompt_execution: PromptExecutionSpec = Field(
        description="Prompt and run context for executing this scenario.",
    )
    risk_units: List[RiskUnit] = Field(
        min_length=1,
        description="Atomic material-risk units available to the model.",
    )
    nudge_level: NudgeLevel = Field(
        description="Controlled nudge-gradient level for this variant.",
    )
    target_falsifiability_level: FalsifiabilityLevel = Field(
        default=FalsifiabilityLevel.NOT_APPLICABLE,
        description="Target falsifiability-gradient level for high-nudge variants, otherwise not applicable.",
    )
    benchmark_provenance: BenchmarkProvenance = Field(
        default_factory=BenchmarkProvenance,
        description="Source benchmark provenance, if any.",
    )

    @model_validator(mode="after")
    def target_falsifiability_matches_nudge(self) -> "ScenarioSpec":
        """Ensure target falsifiability is only set for high-nudge scenarios."""
        has_target = self.target_falsifiability_level != FalsifiabilityLevel.NOT_APPLICABLE
        if self.nudge_level == NudgeLevel.HIGH and not has_target:
            raise ValueError("target_falsifiability_level is required for high-nudge scenarios")
        if self.nudge_level != NudgeLevel.HIGH and has_target:
            raise ValueError(
                "target_falsifiability_level must be not_applicable unless nudge_level is high"
            )
        return self
