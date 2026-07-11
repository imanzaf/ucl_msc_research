"""Tests for the OpenRouter model catalog helpers."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from configs.api_settings import APISettings
from src.experiments.model_catalog import (
    default_agent_model_ids,
    default_scenario_generator_model_id,
    default_scoring_model_id,
    default_user_model_id,
    load_model_catalog,
    validate_model_ids_against_openrouter,
)


class FakeModelResponse:
    """Fake HTTP response for OpenRouter model-list tests."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        """Store the response payload."""
        self.payload = payload

    def raise_for_status(self) -> None:
        """Pretend the request succeeded."""
        return None

    def json(self) -> Dict[str, Any]:
        """Return the fake JSON payload."""
        return self.payload


def make_api_settings() -> APISettings:
    """Create API settings with placeholder keys for validator tests."""
    return APISettings(
        OPENAI_API_KEY_CITATION_VALIDATOR="openai",
        ANTHROPIC_API_KEY_TEX_REVIEWER="anthropic",
        ANTHROPIC_API_KEY_ACADEMIC_AUTHOR="anthropic",
        OPENAI_API_KEY_RESEARCH_AUDITOR="openai",
        OPENAI_API_KEY_SCENARIO_GENERATOR="openai",
        OPENROUTER_API_KEY="openrouter",
    )


def test_default_agent_models_use_configured_agent_models() -> None:
    """Verify default agent models come from the top-level agent model list."""
    assert default_agent_model_ids() == [
        "openai/gpt-5.5",
        "anthropic/claude-sonnet-5",
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
    ]


def test_role_specific_model_fields_are_available() -> None:
    """Verify role-specific model specs are available from the model catalog."""
    catalog = load_model_catalog()

    assert catalog.schema_version == "4.0"
    assert [model.name for model in catalog.agent_models] == [
        "GPT 5.5",
        "Claude Sonnet 5",
        "Llama 3.3 70B Instruct",
        "Qwen 2.5 72B Instruct",
    ]
    assert default_user_model_id() == "google/gemini-3.1-flash-lite"
    assert default_scenario_generator_model_id() == "openai/gpt-5.4"
    assert default_scoring_model_id() == "openai/gpt-5.4-mini"
    assert catalog.user_model.name == "Gemini 3.1 Flash Lite"
    assert catalog.scoring_model.name == "GPT 5.4 Mini"
    assert catalog.scenario_generator_model.name == "GPT 5.4"


def test_validate_model_ids_against_openrouter_rejects_unknown_ids(monkeypatch) -> None:
    """Verify model validation uses OpenRouter's model-list response."""

    def fake_get(*args: Any, **kwargs: Any) -> FakeModelResponse:
        """Return a minimal fake OpenRouter model list."""
        return FakeModelResponse({"data": [{"id": "openai/gpt-5.5"}]})

    monkeypatch.setattr("src.experiments.model_catalog.httpx.get", fake_get)

    validate_model_ids_against_openrouter(
        model_ids=["openai/gpt-5.5"],
        api_settings=make_api_settings(),
        timeout_seconds=1.0,
    )
    with pytest.raises(ValueError):
        validate_model_ids_against_openrouter(
            model_ids=["missing/model"],
            api_settings=make_api_settings(),
            timeout_seconds=1.0,
        )
