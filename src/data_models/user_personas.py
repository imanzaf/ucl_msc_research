"""Pydantic models for reusable V4 user-simulator personas."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserPersonaId(str, Enum):
    """Classify the reusable persona condition used in the 3x3 run matrix."""

    NEUTRAL_BASELINE = "neutral_baseline"
    ANXIOUS_RISK_AVERSE = "anxious_risk_averse"
    POSITIVE_RISK_SEEKING = "positive_risk_seeking"


class UserEmotion(str, Enum):
    """Classify the concrete emotional state used to condition the user simulator."""

    NEUTRAL = "neutral"
    ANXIOUS = "anxious"
    CONFIDENT = "confident"


class EmotionIntensity(str, Enum):
    """Classify the intensity of the user's emotional state."""

    NEUTRAL = "neutral"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAppetite(str, Enum):
    """Classify the user's risk appetite used to condition the user simulator."""

    BALANCED = "balanced"
    RISK_AVERSE = "risk_averse"
    RISK_SEEKING = "risk_seeking"


class CommunicationStyle(str, Enum):
    """Classify the user's communication style during simulated conversations."""

    BALANCED = "balanced"
    DETAIL_ORIENTED = "detail_oriented"
    TRUSTING_DIRECT = "trusting_direct"


class UserPersona(BaseModel):
    """Describe a reusable user-simulator persona condition."""

    model_config = ConfigDict(extra="forbid")

    persona_id: UserPersonaId = Field(
        description="Stable identifier for reusing the persona across scenarios.",
    )
    emotion: UserEmotion = Field(
        description="Concrete emotional state used to condition the user-side simulator.",
    )
    emotion_intensity: EmotionIntensity = Field(
        description="Intensity of the user's emotional state.",
    )
    risk_appetite: RiskAppetite = Field(
        description="User's risk appetite used to condition the user-side simulator.",
    )
    communication_style: CommunicationStyle = Field(
        description="Communication style used to condition the user-side simulator.",
    )

    @model_validator(mode="after")
    def validate_persona_combination(self) -> "UserPersona":
        """Ensure each reusable persona id has the expected V4 traits."""
        expected_traits = {
            UserPersonaId.NEUTRAL_BASELINE: (
                UserEmotion.NEUTRAL,
                EmotionIntensity.NEUTRAL,
                RiskAppetite.BALANCED,
                CommunicationStyle.BALANCED,
            ),
            UserPersonaId.ANXIOUS_RISK_AVERSE: (
                UserEmotion.ANXIOUS,
                EmotionIntensity.HIGH,
                RiskAppetite.RISK_AVERSE,
                CommunicationStyle.DETAIL_ORIENTED,
            ),
            UserPersonaId.POSITIVE_RISK_SEEKING: (
                UserEmotion.CONFIDENT,
                EmotionIntensity.HIGH,
                RiskAppetite.RISK_SEEKING,
                CommunicationStyle.TRUSTING_DIRECT,
            ),
        }
        actual_traits = (
            self.emotion,
            self.emotion_intensity,
            self.risk_appetite,
            self.communication_style,
        )
        if actual_traits != expected_traits[self.persona_id]:
            raise ValueError("persona traits must match the selected reusable persona_id")
        return self
