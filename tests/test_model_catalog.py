"""Tests for the OpenRouter model catalog helpers."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from configs.api_settings import APISettings, OpenRouterCredentialRole
from configs.model_settings import ModelSettings
from src.experiments.model_catalog import (
    default_scenario_generator_model_id,
    load_model_catalog,
    resolve_agent_model_ids,
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
        OPENROUTER_API_KEY_SCENARIO_GENERATION="scenario-generation-key",
        OPENROUTER_API_KEY_AGENT="agent-key",
        OPENROUTER_API_KEY_USER_SIMULATOR="user-simulator-key",
        OPENROUTER_API_KEY_SCORING="scoring-key",
    )


def test_role_specific_model_fields_are_available() -> None:
    """Verify role-specific model specs are available from the model catalog."""
    catalog = load_model_catalog()

    assert catalog.schema_version.value == "5.0"
    assert [model.name for model in catalog.agent_models] == [
        "Llama 3.3 70B Instruct",
        "Qwen 2.5 72B Instruct",
    ]
    assert catalog.user_model.model_id == "google/gemma-4-26b-a4b-it"
    assert default_scenario_generator_model_id() == "openai/gpt-5.4-mini"
    assert catalog.scoring_model.model_id == "google/gemini-3.1-flash-lite"
    assert catalog.user_model.name == "Gemma 4 26B A4B"
    assert catalog.scoring_model.name == "Gemini 3.1 Flash Lite"
    assert catalog.scenario_generator_model.name == "GPT 5.4 Mini"


def test_model_selection_is_not_environment_configurable() -> None:
    """Verify role-specific model ids have a single source of truth in the model catalog."""
    model_fields = set(ModelSettings.model_fields)

    assert "scenario_generator_model" not in model_fields
    assert "user_simulator_model" not in model_fields
    assert "scoring_model" not in model_fields


def test_agent_model_selection_is_restricted_to_catalog() -> None:
    """Verify CLI agent subsets cannot introduce model ids outside the canonical catalog."""
    catalog = load_model_catalog()

    assert resolve_agent_model_ids(catalog, ["meta-llama/llama-3.3-70b-instruct"]) == [
        "meta-llama/llama-3.3-70b-instruct"
    ]
    with pytest.raises(ValueError):
        resolve_agent_model_ids(catalog, ["unconfigured/model"])
    with pytest.raises(ValueError):
        resolve_agent_model_ids(
            catalog,
            ["meta-llama/llama-3.3-70b-instruct", "meta-llama/llama-3.3-70b-instruct"],
        )


def test_validate_model_ids_against_openrouter_rejects_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify model validation uses OpenRouter's model-list response."""
    authorization_headers = []

    def fake_get(*args: Any, **kwargs: Any) -> FakeModelResponse:
        """Return a minimal fake OpenRouter model list."""
        authorization_headers.append(kwargs["headers"]["Authorization"])
        return FakeModelResponse({"data": [{"id": "openai/gpt-5.5"}]})

    monkeypatch.setattr("src.experiments.model_catalog.httpx.get", fake_get)

    validate_model_ids_against_openrouter(
        model_ids=["openai/gpt-5.5"],
        api_settings=make_api_settings(),
        credential_role=OpenRouterCredentialRole.AGENT,
        timeout_seconds=1.0,
    )
    with pytest.raises(ValueError):
        validate_model_ids_against_openrouter(
            model_ids=["missing/model"],
            api_settings=make_api_settings(),
            credential_role=OpenRouterCredentialRole.AGENT,
            timeout_seconds=1.0,
        )

    assert authorization_headers == ["Bearer agent-key", "Bearer agent-key"]
