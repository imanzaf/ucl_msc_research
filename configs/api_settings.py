from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """Project-wide API settings.

    Loaded from env.static first, then .env (values in .env take precedence).
    Both files are optional; any field can also be set via a real env var,
    which takes precedence over all files.
    """

    model_config = SettingsConfigDict(
        env_file=["env.static", ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key_citation_validator: str = Field(
        default="",
        validation_alias="OPENAI_API_KEY_CITATION_VALIDATOR",
        description="OpenAI API key used by the citation validator.",
    )

    @field_validator("openai_api_key_citation_validator")
    @classmethod
    def key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("OPENAI_API_KEY_CITATION_VALIDATOR must be set in .env or env.static")
        return v


@lru_cache(maxsize=1)
def get_api_settings() -> APISettings:
    return APISettings()
