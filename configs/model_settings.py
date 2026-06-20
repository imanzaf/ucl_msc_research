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
        default="gpt-5.4-2026-03-05",
        validation_alias="SCENARIO_GENERATOR_MODEL",
        description="OpenAI model used to generate scenario drafts.",
    )
    max_generation_retries: int = Field(
        default=2,
        ge=0,
        validation_alias="MAX_GENERATION_RETRIES",
        description="Shared retry count for structured generation attempts.",
    )


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    """Return cached project-wide model settings."""
    return ModelSettings()
