"""Pydantic models for reusable user-simulator personas."""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


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
