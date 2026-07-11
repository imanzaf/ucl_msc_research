"""Helpers for reading the configured OpenRouter experiment model catalog."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Set

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from configs.api_settings import APISettings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_CATALOG_PATH = REPO_ROOT / "configs" / "models.json"


class ModelPriority(str, Enum):
    """Classify model run priority in the experiment catalog."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


class ExperimentModelSpec(BaseModel):
    """Describe one OpenRouter model configured for a pipeline role."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        description="Human-readable model name.",
    )
    model_id: str = Field(
        min_length=1,
        description="OpenRouter model slug.",
    )
    provider: str = Field(
        min_length=1,
        description="Model provider.",
    )
    provider_url: str = Field(
        min_length=1,
        description="Provider or model URL.",
    )
    access: str = Field(
        min_length=1,
        description="Access route for this model.",
    )
    weight_type: str = Field(
        min_length=1,
        description="Open or closed weight classification.",
    )
    priority: ModelPriority = Field(
        description="Default experiment run priority.",
    )


class ExperimentModelCatalog(BaseModel):
    """Describe role-specific models used by the experiment pipeline."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        min_length=1,
        description="Catalog schema version.",
    )
    description: str = Field(
        min_length=1,
        description="Human-readable catalog description.",
    )
    agent_models: List[ExperimentModelSpec] = Field(
        min_length=1,
        description="Agent models under test.",
    )
    user_model: ExperimentModelSpec = Field(
        description="Model used for user-simulator turns and outcomes.",
    )
    scoring_model: ExperimentModelSpec = Field(
        description="Model used for scoring extraction and judge calls.",
    )
    scenario_generator_model: ExperimentModelSpec = Field(
        description="Model used for scenario draft generation.",
    )

    def all_model_specs(self) -> List[ExperimentModelSpec]:
        """Return every configured model spec across all pipeline roles."""
        return self.agent_models + [
            self.user_model,
            self.scoring_model,
            self.scenario_generator_model,
        ]

    @model_validator(mode="after")
    def validate_unique_role_model_ids(self) -> "ExperimentModelCatalog":
        """Ensure each configured role model has a unique OpenRouter id."""
        model_ids = [model.model_id for model in self.all_model_specs()]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("model_id values must be unique across configured pipeline roles")
        return self


def load_model_catalog(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> ExperimentModelCatalog:
    """Load and validate the configured experiment model catalog."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentModelCatalog.model_validate(payload)


def default_agent_model_ids(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> List[str]:
    """Return agent model slugs used when no CLI agent models are provided."""
    return [model.model_id for model in load_model_catalog(path).agent_models]


def default_user_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the default user-simulator model slug."""
    return load_model_catalog(path).user_model.model_id


def default_scenario_generator_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the default scenario-generator model slug."""
    return load_model_catalog(path).scenario_generator_model.model_id


def default_scoring_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the default scoring model slug."""
    return load_model_catalog(path).scoring_model.model_id


def fetch_openrouter_model_ids(
    api_settings: APISettings,
    timeout_seconds: float,
) -> Set[str]:
    """Fetch available model ids from OpenRouter's models endpoint."""
    response = httpx.get(
        f"{api_settings.openrouter_base_url}/models",
        headers={"Authorization": f"Bearer {api_settings.openrouter_api_key}"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return {str(model["id"]) for model in payload.get("data", []) if "id" in model}


def validate_model_ids_against_openrouter(
    model_ids: Iterable[str],
    api_settings: APISettings,
    timeout_seconds: float,
) -> None:
    """Reject configured model ids that are absent from OpenRouter's model list."""
    available_model_ids = fetch_openrouter_model_ids(
        api_settings=api_settings,
        timeout_seconds=timeout_seconds,
    )
    unknown_model_ids = sorted(set(model_ids) - available_model_ids)
    if unknown_model_ids:
        raise ValueError("OpenRouter model ids not found: " + ", ".join(unknown_model_ids))
