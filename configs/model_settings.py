from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseSettings):
    """Project-wide model selection and generation settings."""

    model_config = SettingsConfigDict(
        env_file=[".env.static", ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    scenario_generator_model: str = Field(
        default="openai/gpt-5.4",
        validation_alias="SCENARIO_GENERATOR_MODEL",
        description="OpenRouter model slug used to generate scenario drafts.",
    )
    user_simulator_model: str = Field(
        default="google/gemini-3.1-flash-lite",
        validation_alias="USER_SIMULATOR_MODEL",
        description="OpenRouter model slug used for user-simulator turns and outcomes.",
    )
    scoring_model: str = Field(
        default="openai/gpt-5.4-mini",
        validation_alias="SCORING_MODEL",
        description="OpenRouter model slug used for scoring extraction and judge calls.",
    )
    max_generation_retries: int = Field(
        default=2,
        ge=0,
        validation_alias="MAX_GENERATION_RETRIES",
        description="Shared retry count for structured generation attempts.",
    )
    openrouter_request_timeout_seconds: float = Field(
        default=120.0,
        gt=0.0,
        validation_alias="OPENROUTER_REQUEST_TIMEOUT_SECONDS",
        description="Timeout for OpenRouter API requests.",
    )
    openrouter_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias="OPENROUTER_TEMPERATURE",
        description="Default sampling temperature for OpenRouter API requests.",
    )
    openrouter_seed: int = Field(
        default=7,
        validation_alias="OPENROUTER_SEED",
        description="Default deterministic seed passed to OpenRouter when supported.",
    )
    max_followup_turns: int = Field(
        default=3,
        ge=1,
        le=3,
        validation_alias="MAX_USER_SIMULATOR_FOLLOWUP_TURNS",
        description="Maximum generated user follow-up turns in multi-turn runs.",
    )


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    """Return cached project-wide model settings."""
    return ModelSettings()
