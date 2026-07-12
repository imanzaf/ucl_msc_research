"""Helpers for reading the configured OpenRouter experiment model catalog."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from configs.api_settings import APISettings, OpenRouterCredentialRole

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_CATALOG_PATH = REPO_ROOT / "configs" / "models.json"


class ModelPriority(str, Enum):
    """Classify model run priority in the experiment catalog."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


class ModelCatalogSchemaVersion(str, Enum):
    """Identify the canonical experiment model-catalog schema."""

    V5 = "5.0"


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

    schema_version: ModelCatalogSchemaVersion = Field(
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

    @model_validator(mode="after")
    def validate_unique_agent_model_ids(self) -> "ExperimentModelCatalog":
        """Ensure the set of agent models under test does not contain duplicate ids."""
        model_ids = [model.model_id for model in self.agent_models]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("agent model_id values must be unique")
        return self


def load_model_catalog(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> ExperimentModelCatalog:
    """Load and validate the configured experiment model catalog."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentModelCatalog.model_validate(payload)


def default_scenario_generator_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the default scenario-generator model slug."""
    return load_model_catalog(path).scenario_generator_model.model_id


def resolve_agent_model_ids(
    catalog: ExperimentModelCatalog,
    requested_model_ids: Optional[Sequence[str]],
) -> List[str]:
    """Resolve an optional agent subset while restricting ids to the canonical catalog."""
    configured_model_ids = [model.model_id for model in catalog.agent_models]
    if requested_model_ids is None:
        return configured_model_ids
    if len(set(requested_model_ids)) != len(requested_model_ids):
        raise ValueError("agent model ids must not contain duplicates")
    unknown_model_ids = sorted(set(requested_model_ids) - set(configured_model_ids))
    if unknown_model_ids:
        raise ValueError(
            "agent model ids are not configured in configs/models.json: "
            + ", ".join(unknown_model_ids)
        )
    return list(requested_model_ids)


def fetch_openrouter_model_ids(
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> Set[str]:
    """Fetch available model ids using the key assigned to one pipeline role."""
    response = httpx.get(
        f"{api_settings.openrouter_base_url}/models",
        headers={"Authorization": f"Bearer {api_settings.openrouter_api_key_for(credential_role)}"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return {str(model["id"]) for model in payload.get("data", []) if "id" in model}


def validate_model_ids_against_openrouter(
    model_ids: Iterable[str],
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> None:
    """Reject configured model ids that are absent from OpenRouter's model list."""
    available_model_ids = fetch_openrouter_model_ids(
        api_settings=api_settings,
        credential_role=credential_role,
        timeout_seconds=timeout_seconds,
    )
    unknown_model_ids = sorted(set(model_ids) - available_model_ids)
    if unknown_model_ids:
        raise ValueError("OpenRouter model ids not found: " + ", ".join(unknown_model_ids))
