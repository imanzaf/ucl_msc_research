"""Tests for role-specific API credential settings."""

from __future__ import annotations

from typing import Dict

import pytest
from pydantic import ValidationError

from configs.api_settings import APISettings, OpenRouterCredentialRole


def api_setting_values() -> Dict[str, str]:
    """Return complete API setting aliases with distinct OpenRouter role keys."""
    return {
        "OPENAI_API_KEY_CITATION_VALIDATOR": "citation-key",
        "ANTHROPIC_API_KEY_TEX_REVIEWER": "review-key",
        "ANTHROPIC_API_KEY_ACADEMIC_AUTHOR": "author-key",
        "OPENAI_API_KEY_RESEARCH_AUDITOR": "audit-key",
        "OPENROUTER_API_KEY_SCENARIO_GENERATION": "scenario-generation-key",
        "OPENROUTER_API_KEY_AGENT": "agent-key",
        "OPENROUTER_API_KEY_USER_SIMULATOR": "user-simulator-key",
        "OPENROUTER_API_KEY_SCORING": "scoring-key",
        "OPENROUTER_API_KEY": "",
    }


def make_api_settings() -> APISettings:
    """Create complete API settings with distinct OpenRouter role keys."""
    return APISettings(**api_setting_values())


def test_openrouter_keys_are_selected_by_pipeline_role() -> None:
    """Verify each pipeline role resolves only its assigned OpenRouter key."""
    settings = make_api_settings()

    assert (
        settings.openrouter_api_key_for(OpenRouterCredentialRole.SCENARIO_GENERATION)
        == "scenario-generation-key"
    )
    assert settings.openrouter_api_key_for(OpenRouterCredentialRole.AGENT) == "agent-key"
    assert (
        settings.openrouter_api_key_for(OpenRouterCredentialRole.USER_SIMULATOR)
        == "user-simulator-key"
    )
    assert settings.openrouter_api_key_for(OpenRouterCredentialRole.SCORING) == "scoring-key"


def test_all_openrouter_role_keys_are_required() -> None:
    """Verify a missing role key fails configuration instead of falling back to another key."""
    settings_data = api_setting_values()

    for field_name in [
        "OPENROUTER_API_KEY_SCENARIO_GENERATION",
        "OPENROUTER_API_KEY_AGENT",
        "OPENROUTER_API_KEY_USER_SIMULATOR",
        "OPENROUTER_API_KEY_SCORING",
    ]:
        invalid_settings = dict(settings_data)
        invalid_settings[field_name] = ""
        with pytest.raises(ValidationError):
            APISettings(**invalid_settings)


def test_legacy_openrouter_key_fills_only_unset_roles() -> None:
    """Verify the shared legacy key provides a migration fallback without overriding role keys."""
    settings_data = api_setting_values()
    settings_data["OPENROUTER_API_KEY"] = "legacy-key"
    settings_data["OPENROUTER_API_KEY_AGENT"] = "agent-key"
    settings_data["OPENROUTER_API_KEY_SCENARIO_GENERATION"] = ""
    settings_data["OPENROUTER_API_KEY_USER_SIMULATOR"] = ""
    settings_data["OPENROUTER_API_KEY_SCORING"] = ""

    settings = APISettings(**settings_data)

    assert settings.openrouter_api_key_for(OpenRouterCredentialRole.AGENT) == "agent-key"
    assert (
        settings.openrouter_api_key_for(OpenRouterCredentialRole.SCENARIO_GENERATION)
        == "legacy-key"
    )
    assert settings.openrouter_api_key_for(OpenRouterCredentialRole.USER_SIMULATOR) == "legacy-key"
    assert settings.openrouter_api_key_for(OpenRouterCredentialRole.SCORING) == "legacy-key"
