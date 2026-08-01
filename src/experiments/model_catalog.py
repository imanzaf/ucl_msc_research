"""Strict draft/frozen model catalog with family and independence gates."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import httpx
from pydantic import Field, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel
from src.data_models.manifests import FreezeStatus, ModelWeightType
from src.settings.api_settings import APISettings, OpenRouterCredentialRole

DEFAULT_MODEL_CATALOG_PATH = Path(__file__).resolve().parents[1] / "settings" / "models.json"


class ModelPriority(str, Enum):
    """Classify configured model priority before the freeze gate."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


class ExperimentModelSpec(ImmutableModel):
    """Describe one exact model candidate or pipeline support model."""

    name: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_url: str = Field(min_length=1)
    access: str = Field(min_length=1)
    weight_type: ModelWeightType
    priority: ModelPriority


class ExperimentModelCatalog(VersionedImmutableModel):
    """Describe evaluated candidates and independent generation and scoring roles."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    description: str = Field(min_length=1)
    freeze_status: FreezeStatus
    evaluated_models: List[ExperimentModelSpec] = Field(min_length=3, max_length=3)
    scoring_models: List[ExperimentModelSpec] = Field(min_length=1)
    scenario_generator_model: ExperimentModelSpec

    @model_validator(mode="after")
    def validate_role_independence(self) -> "ExperimentModelCatalog":
        """Require model diversity and an independent scoring role."""
        evaluated_ids = [model.model_id for model in self.evaluated_models]
        if len(evaluated_ids) != len(set(evaluated_ids)):
            raise ValueError("evaluated model ids must be unique")
        if len({model.family for model in self.evaluated_models}) != 3:
            raise ValueError("evaluated candidates must span three families")
        if len({model.provider for model in self.evaluated_models}) < 2:
            raise ValueError("evaluated candidates must span at least two providers")
        if not any(model.weight_type == ModelWeightType.OPEN for model in self.evaluated_models):
            raise ValueError("evaluated candidates require at least one open-weight family")
        if not any(model.model_id not in set(evaluated_ids) for model in self.scoring_models):
            raise ValueError("evaluated models cannot be their own sole scoring judge")
        return self


def load_model_catalog(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> ExperimentModelCatalog:
    """Load and strictly validate the configured model catalog."""
    return ExperimentModelCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))


def resolve_evaluated_model_ids(
    catalog: ExperimentModelCatalog,
    requested_model_ids: Optional[Sequence[str]],
    require_frozen: bool = True,
) -> List[str]:
    """Resolve only configured evaluated ids and optionally enforce the model-freeze gate."""
    if require_frozen and catalog.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("evaluated model snapshots must be frozen before model-generated calibration or execution")
    configured_ids = [model.model_id for model in catalog.evaluated_models]
    if requested_model_ids is None:
        return configured_ids
    if len(requested_model_ids) != len(set(requested_model_ids)):
        raise ValueError("requested evaluated model ids must be unique")
    unknown = sorted(set(requested_model_ids) - set(configured_ids))
    if unknown:
        raise ValueError("unconfigured evaluated model ids: " + ", ".join(unknown))
    return list(requested_model_ids)


def default_scenario_generator_model_id(path: Path = DEFAULT_MODEL_CATALOG_PATH) -> str:
    """Return the configured scenario-generator model id."""
    return load_model_catalog(path).scenario_generator_model.model_id


def fetch_openrouter_models(
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> List[Dict[str, Any]]:
    """Fetch the provider model metadata used to create a frozen snapshot."""
    response = httpx.get(
        f"{api_settings.openrouter_base_url}/models",
        headers={"Authorization": f"Bearer {api_settings.openrouter_api_key_for(credential_role)}"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return [model for model in payload.get("data", []) if isinstance(model, dict)]


def validate_model_ids_against_openrouter(
    model_ids: Iterable[str],
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> None:
    """Reject configured ids missing from one provider metadata snapshot."""
    available = {str(model["id"]) for model in fetch_openrouter_models(api_settings, credential_role, timeout_seconds) if "id" in model}
    unknown = sorted(set(model_ids) - available)
    if unknown:
        raise ValueError("OpenRouter model ids not found: " + ", ".join(unknown))


def validate_model_supports_any_parameter(
    model_id: str,
    required_parameters: Set[str],
    api_settings: APISettings,
    credential_role: OpenRouterCredentialRole,
    timeout_seconds: float,
) -> None:
    """Require a provider model to advertise at least one required parameter."""
    models = {str(model.get("id")): model for model in fetch_openrouter_models(api_settings, credential_role, timeout_seconds)}
    if model_id not in models:
        raise ValueError(f"OpenRouter model id not found: {model_id}")
    supported = {str(value) for value in models[model_id].get("supported_parameters", [])}
    if supported.isdisjoint(required_parameters):
        raise ValueError(f"OpenRouter model {model_id} lacks any required parameter: {sorted(required_parameters)}")
