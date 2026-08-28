"""Transport and safety settings for model calls."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseSettings):
    """Configure transport retries and request timeout."""

    model_config = SettingsConfigDict(env_file=[".env.static", ".env"], env_file_encoding="utf-8", extra="ignore")

    transport_retry_limit: int = Field(default=2, ge=0, le=5, validation_alias="OPENROUTER_TRANSPORT_RETRY_LIMIT")
    request_timeout_seconds: float = Field(default=180.0, gt=0, validation_alias="OPENROUTER_REQUEST_TIMEOUT_SECONDS")


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    """Return cached model settings."""
    return ModelSettings()
