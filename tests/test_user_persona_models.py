"""Tests for reusable user persona Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.data_models.user_personas import (
    EmotionIntensity,
    PersonalityTrait,
    UserEmotion,
    UserPersona,
)


def make_user_persona() -> UserPersona:
    """Create a valid reusable user persona for model tests."""
    return UserPersona(
        persona_id="neutral_stakeholder_v1",
        stakeholder_role="finance_decision_maker",
        emotion=UserEmotion.NEUTRAL,
        emotion_intensity=EmotionIntensity.LOW,
        primary_personality_trait=PersonalityTrait.NEUTRAL,
        secondary_personality_traits=[PersonalityTrait.DETAIL_ORIENTED],
        user_goal="Review whether the financial communication is balanced.",
        communication_style="Ask for concise, professional information.",
    )


def test_user_persona_accepts_valid_record() -> None:
    """Verify a valid user persona can be constructed and round-tripped."""
    persona = make_user_persona()
    round_tripped = UserPersona.model_validate(persona.model_dump())

    assert round_tripped.persona_id == "neutral_stakeholder_v1"
    assert round_tripped.emotion == UserEmotion.NEUTRAL


def test_user_persona_rejects_invalid_emotion() -> None:
    """Verify persona emotion values must come from the controlled enum."""
    data = make_user_persona().model_dump()
    data["emotion"] = "panicked"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_invalid_personality_trait() -> None:
    """Verify persona personality values must come from the controlled enum."""
    data = make_user_persona().model_dump()
    data["primary_personality_trait"] = "impulsive"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_extra_fields() -> None:
    """Verify stale or unsupported persona metadata is rejected."""
    data = make_user_persona().model_dump()
    data["scenario_family_id"] = "listed_company_risk_disclosure_v1"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)
