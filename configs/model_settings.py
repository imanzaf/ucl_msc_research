from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseSettings):
    """Project-wide generation settings for OpenRouter calls."""

    model_config = SettingsConfigDict(
        env_file=[".env.static", ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
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


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    """Return cached project-wide model settings."""
    return ModelSettings()
