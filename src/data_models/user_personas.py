"""Pydantic models for reusable user-simulator personas."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class UserSentiment(str, Enum):
    """Classify the user sentiment used to condition the user simulator."""

    NEGATIVE = "negative"
    POSITIVE = "positive"


class UserEmotion(str, Enum):
    """Classify the emotional state used to condition the user simulator."""

    NEGATIVE = ["frustrated", "angry", "anxious", "disappointed"]
    POSITIVE = ["satisfied", "relieved", "confident", "excited"]


class RiskAppetite(str, Enum):
    """Classify the user's risk appetite used to condition the user simulator."""

    RISK_AVERSE = "risk_averse"
    RISK_SEEKING = "risk_seeking"


class UserPersona(BaseModel):
    """Describe a reusable user-simulator persona interacting with the financial agent."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(
        min_length=1,
        description="Stable identifier for reusing the persona across scenarios.",
    )
    sentiment: UserSentiment = Field(
        description="Sentiment used to condition the user-side simulator.",
    )
    emotion: UserEmotion = Field(
        description="Emotional state used to condition the user-side simulator.",
    )
    risk_appetite: RiskAppetite = Field(
        description="User's risk appetite used to condition the user-side simulator.",
    )
