"""Tests for reusable user persona Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.data_models.user_personas import RiskAppetite, UserEmotion, UserPersona, UserSentiment


def make_user_persona() -> UserPersona:
    """Create a valid reusable user persona for model tests."""
    return UserPersona(
        persona_id="risk_averse_investor_v1",
        sentiment=UserSentiment.NEGATIVE,
        emotion=UserEmotion.NEGATIVE,
        risk_appetite=RiskAppetite.RISK_AVERSE,
    )


def test_user_persona_accepts_valid_record() -> None:
    """Verify a valid user persona can be constructed and round-tripped."""
    persona = make_user_persona()
    round_tripped = UserPersona.model_validate(persona.model_dump())

    assert round_tripped.persona_id == "risk_averse_investor_v1"
    assert round_tripped.sentiment == UserSentiment.NEGATIVE


def test_user_persona_rejects_invalid_sentiment() -> None:
    """Verify persona sentiment values must come from the controlled enum."""
    data = make_user_persona().model_dump()
    data["sentiment"] = "uncertain"

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
    data["risk_appetite"] = "neutral"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)


def test_user_persona_rejects_extra_fields() -> None:
    """Verify stale or unsupported persona metadata is rejected."""
    data = make_user_persona().model_dump()
    data["scenario_family_id"] = "listed_company_risk_disclosure_v1"

    with pytest.raises(ValidationError):
        UserPersona.model_validate(data)
