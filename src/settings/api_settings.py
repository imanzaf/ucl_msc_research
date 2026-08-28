"""Role-scoped API configuration for provider calls."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CredentialRole(str, Enum):
    """Identify the narrowly scoped provider credential needed by a workflow."""

    SCENARIO_GENERATION = "scenario_generation"
    EVALUATED_MODEL = "evaluated_model"
    SCORING = "scoring"


class APISettings(BaseSettings):
    """Load API settings from committed defaults and local overrides."""

    model_config = SettingsConfigDict(env_file=[".env.static", ".env"], env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key_scenario_generation: str = Field(default="", validation_alias="OPENROUTER_API_KEY_SCENARIO_GENERATION")
    openrouter_api_key_agent: str = Field(default="", validation_alias="OPENROUTER_API_KEY_AGENT")
    openrouter_api_key_scoring: str = Field(default="", validation_alias="OPENROUTER_API_KEY_SCORING")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL")
    openrouter_http_referer: str = Field(default="", validation_alias="OPENROUTER_HTTP_REFERER")
    openrouter_app_title: str = Field(default="ucl-msc-research", validation_alias="OPENROUTER_APP_TITLE")
    paid_api_calls_disabled: bool = Field(default=False, validation_alias="CI_PAID_API_CALLS_DISABLED")

    def key_for(self, role: CredentialRole) -> str:
        """Return a role-specific key, using the shared key only as an explicit fallback."""
        keys = {
            CredentialRole.SCENARIO_GENERATION: self.openrouter_api_key_scenario_generation,
            CredentialRole.EVALUATED_MODEL: self.openrouter_api_key_agent,
            CredentialRole.SCORING: self.openrouter_api_key_scoring,
        }
        key = keys[role] or self.openrouter_api_key
        if not key:
            raise ValueError(f"no OpenRouter API key is configured for role {role.value}")
        return key


@lru_cache(maxsize=1)
def get_api_settings() -> APISettings:
    """Return cached API settings."""
    return APISettings()
