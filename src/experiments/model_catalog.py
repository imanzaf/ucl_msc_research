"""Helpers for reading the configured OpenRouter experiment model catalog."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from configs.api_settings import APISettings, OpenRouterCredentialRole

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_CATALOG_PATH = REPO_ROOT / "configs" / "models.json"
V6_SCENARIO_REVIEWER_MODEL_ID = "anthropic/claude-haiku-4.5"


class ModelPriority(str, Enum):
    """Classify model run priority in the experiment catalog."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


class ModelCatalogSchemaVersion(str, Enum):
    """Identify the canonical experiment model-catalog schema."""

    V6 = "6.0"


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
    scenario_reviewer_model: ExperimentModelSpec = Field(
        description="Independent model used for V6 semantic scenario review.",
    )

    @model_validator(mode="after")
    def validate_unique_agent_model_ids(self) -> "ExperimentModelCatalog":
        """Ensure agent ids are unique and the V6 reviewer remains fixed and independent."""
        model_ids = [model.model_id for model in self.agent_models]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("agent model_id values must be unique")
        if self.scenario_reviewer_model.model_id != V6_SCENARIO_REVIEWER_MODEL_ID:
            raise ValueError(f"V6 scenario reviewer must be {V6_SCENARIO_REVIEWER_MODEL_ID}")
        if self.scenario_reviewer_model.model_id == self.scenario_generator_model.model_id:
            raise ValueError("V6 scenario reviewer must differ from the scenario generator")
        return self


def load_model_catalog(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> ExperimentModelCatalog:
    """Load and validate the configured experiment model catalog."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentModelCatalog.model_validate(payload)


def default_scenario_generator_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the default scenario-generator model slug."""
    return load_model_catalog(path).scenario_generator_model.model_id


def default_scenario_reviewer_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the fixed V6 semantic-reviewer model slug."""
    return load_model_catalog(path).scenario_reviewer_model.model_id


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


def fetch_openrouter_models(
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> List[Dict[str, Any]]:
    """Fetch OpenRouter model metadata using the credential assigned to one pipeline role."""
    response = httpx.get(
        f"{api_settings.openrouter_base_url}/models",
        headers={"Authorization": f"Bearer {api_settings.openrouter_api_key_for(credential_role)}"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return [model for model in payload.get("data", []) if isinstance(model, dict)]


def validate_model_supports_any_parameter(
    model_id: str,
    required_parameters: Set[str],
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> None:
    """Reject a model that does not advertise any required OpenRouter parameter."""
    model_by_id = {
        str(model.get("id")): model
        for model in fetch_openrouter_models(
            api_settings=api_settings,
            credential_role=credential_role,
            timeout_seconds=timeout_seconds,
        )
        if model.get("id")
    }
    if model_id not in model_by_id:
        raise ValueError(f"OpenRouter model id not found: {model_id}")
    supported_parameters = {
        str(parameter) for parameter in model_by_id[model_id].get("supported_parameters", [])
    }
    if supported_parameters.isdisjoint(required_parameters):
        raise ValueError(
            f"OpenRouter model {model_id} lacks required parameters; expected one of "
            + ", ".join(sorted(required_parameters))
        )


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


def validate_models_and_capabilities(
    model_ids: Iterable[str],
    required_parameters_by_model: Dict[str, Set[str]],
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> None:
    """Validate model existence and advertised parameters from one metadata snapshot."""
    model_by_id = {
        str(model.get("id")): model
        for model in fetch_openrouter_models(
            api_settings=api_settings,
            credential_role=credential_role,
            timeout_seconds=timeout_seconds,
        )
        if model.get("id")
    }
    unknown_model_ids = sorted(set(model_ids) - set(model_by_id))
    if unknown_model_ids:
        raise ValueError("OpenRouter model ids not found: " + ", ".join(unknown_model_ids))
    for model_id, required_parameters in required_parameters_by_model.items():
        supported_parameters = {
            str(parameter) for parameter in model_by_id[model_id].get("supported_parameters", [])
        }
        if not required_parameters.issubset(supported_parameters):
            missing = sorted(required_parameters - supported_parameters)
            raise ValueError(
                f"OpenRouter model {model_id} lacks required parameters: " + ", ".join(missing)
            )
