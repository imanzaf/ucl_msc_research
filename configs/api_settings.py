from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenRouterCredentialRole(str, Enum):
    """Identify the pipeline role assigned to an OpenRouter API key."""

    SCENARIO_GENERATION = "scenario_generation"
    AGENT = "agent"
    SCORING = "scoring"


class APISettings(BaseSettings):
    """Project-wide API settings.

    Loaded from .env.static first, then .env (.env takes precedence).
    Both files are optional; any field can also be set via a real env var,
    which takes precedence over all files.
    """

    model_config = SettingsConfigDict(
        env_file=[".env.static", ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key_citation_validator: str = Field(
        default="",
        validation_alias="OPENAI_API_KEY_CITATION_VALIDATOR",
        description="OpenAI API key used by the citation validator.",
    )

    anthropic_api_key_tex_reviewer: str = Field(
        default="",
        validation_alias="ANTHROPIC_API_KEY_TEX_REVIEWER",
        description="Anthropic API key used by the tex reviewer.",
    )

    anthropic_api_key_academic_author: str = Field(
        default="",
        validation_alias="ANTHROPIC_API_KEY_ACADEMIC_AUTHOR",
        description="Anthropic API key used by the academic author.",
    )

    openai_api_key_research_auditor: str = Field(
        default="",
        validation_alias="OPENAI_API_KEY_RESEARCH_AUDITOR",
        description="OpenAI API key used by the research auditor agent.",
    )

    openrouter_api_key_scenario_generation: str = Field(
        default="",
        validation_alias="OPENROUTER_API_KEY_SCENARIO_GENERATION",
        description="OpenRouter API key used by the scenario generation pipeline.",
    )
    openrouter_api_key_agent: str = Field(
        default="",
        validation_alias="OPENROUTER_API_KEY_AGENT",
        description="OpenRouter API key used for agent response calls.",
    )
    openrouter_api_key_scoring: str = Field(
        default="",
        validation_alias="OPENROUTER_API_KEY_SCORING",
        description="OpenRouter API key used for scoring calls.",
    )
    openrouter_api_key: str = Field(
        default="",
        validation_alias="OPENROUTER_API_KEY",
        description="Legacy shared OpenRouter key used only when a role-specific key is unset.",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="OPENROUTER_BASE_URL",
        description="OpenRouter OpenAI-compatible API base URL.",
    )
    openrouter_http_referer: str = Field(
        default="",
        validation_alias="OPENROUTER_HTTP_REFERER",
        description="Optional OpenRouter attribution referer header.",
    )
    openrouter_app_title: str = Field(
        default="ucl-msc-research",
        validation_alias="OPENROUTER_APP_TITLE",
        description="Optional OpenRouter attribution app title header.",
    )
    paid_api_calls_disabled: bool = Field(
        default=False,
        validation_alias="CI_PAID_API_CALLS_DISABLED",
        description="Fail closed before constructing or using an external paid-call client.",
    )

    @field_validator("openai_api_key_citation_validator")
    @classmethod
    def openai_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("OPENAI_API_KEY_CITATION_VALIDATOR must be set in .env.static or .env")
        return v

    @field_validator("anthropic_api_key_tex_reviewer")
    @classmethod
    def anthropic_tex_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("ANTHROPIC_API_KEY_TEX_REVIEWER must be set in .env.static or .env")
        return v

    @field_validator("anthropic_api_key_academic_author")
    @classmethod
    def anthropic_author_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("ANTHROPIC_API_KEY_ACADEMIC_AUTHOR must be set in .env.static or .env")
        return v

    @field_validator("openai_api_key_research_auditor")
    @classmethod
    def openai_auditor_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("OPENAI_API_KEY_RESEARCH_AUDITOR must be set in .env.static or .env")
        return v

    @field_validator("openrouter_base_url")
    @classmethod
    def openrouter_base_url_must_be_set(cls, v: str) -> str:
        """Ensure OpenRouter-backed experiment calls have a base URL configured."""
        if not v:
            raise ValueError("OPENROUTER_BASE_URL must be set in .env.static or .env")
        return v.rstrip("/")

    @model_validator(mode="after")
    def populate_openrouter_role_key_fallbacks(self) -> "APISettings":
        """Fill unset role keys from the legacy shared OpenRouter key or reject the configuration."""
        role_fields = [
            "openrouter_api_key_scenario_generation",
            "openrouter_api_key_agent",
            "openrouter_api_key_scoring",
        ]
        missing_fields = [field_name for field_name in role_fields if not getattr(self, field_name)]
        if not missing_fields:
            return self
        if not self.openrouter_api_key:
            missing_aliases = [field_name.upper() for field_name in missing_fields]
            raise ValueError("OpenRouter API keys must be set for these roles: " + ", ".join(missing_aliases))
        for field_name in missing_fields:
            setattr(self, field_name, self.openrouter_api_key)
        return self

    def openrouter_api_key_for(self, credential_role: OpenRouterCredentialRole) -> str:
        """Return the OpenRouter API key assigned to a pipeline credential role."""
        keys_by_role = {
            OpenRouterCredentialRole.SCENARIO_GENERATION: self.openrouter_api_key_scenario_generation,
            OpenRouterCredentialRole.AGENT: self.openrouter_api_key_agent,
            OpenRouterCredentialRole.SCORING: self.openrouter_api_key_scoring,
        }
        return keys_by_role[credential_role]


@lru_cache(maxsize=1)
def get_api_settings() -> APISettings:
    """Return cached project-wide API settings."""
    return APISettings()
