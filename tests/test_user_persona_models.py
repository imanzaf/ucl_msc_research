"""Tests for reusable V4 user persona Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.data_models.user_personas import (
    CommunicationStyle,
    EmotionIntensity,
    RiskAppetite,
    UserEmotion,
    UserPersona,
    UserPersonaId,
)


def make_user_persona() -> UserPersona:
    """Create a valid reusable user persona for model tests."""
    return UserPersona(
        persona_id=UserPersonaId.ANXIOUS_RISK_AVERSE,
        emotion=UserEmotion.ANXIOUS,
        emotion_intensity=EmotionIntensity.HIGH,
        risk_appetite=RiskAppetite.RISK_AVERSE,
        communication_style=CommunicationStyle.DETAIL_ORIENTED,
    )


def test_user_persona_accepts_valid_record() -> None:
    """Verify a valid user persona can be constructed and round-tripped."""
    persona = make_user_persona()
    round_tripped = UserPersona.model_validate(persona.model_dump())

    assert round_tripped.persona_id == UserPersonaId.ANXIOUS_RISK_AVERSE
    assert round_tripped.emotion == UserEmotion.ANXIOUS
    assert round_tripped.emotion_intensity == EmotionIntensity.HIGH


def test_user_persona_rejects_invalid_persona_id() -> None:
    """Verify persona ids must come from the controlled reusable set."""
    data = make_user_persona().model_dump()
    data["persona_id"] = "uncertain_user"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_invalid_emotion() -> None:
    """Verify persona emotion values must come from the controlled enum."""
    data = make_user_persona().model_dump()
    data["emotion"] = "panicked"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_invalid_risk_appetite() -> None:
    """Verify persona risk appetite values must come from the controlled enum."""
    data = make_user_persona().model_dump()
    data["risk_appetite"] = "reckless"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_mismatched_persona_traits() -> None:
    """Verify each reusable persona id has the approved V4 trait combination."""
    data = make_user_persona().model_dump()
    data["emotion_intensity"] = EmotionIntensity.MEDIUM.value

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_extra_fields() -> None:
    """Verify stale or unsupported persona metadata is rejected."""
    data = make_user_persona().model_dump()
    data["scenario_family_id"] = "RW001"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)
