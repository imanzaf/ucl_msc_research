"""Model-catalog loading and operational-freeze validation."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import List, Literal

from pydantic import Field, model_validator

from src.common import ImmutableModel, artifact_sha256
from src.models.enums import LicenceCategory, ModelAccess
from src.models.experiments import GenerationControls, ProviderSnapshot


class CatalogEntry(ImmutableModel):
    """Store a declared model and controls before or after provider preflight."""

    model_slug: str
    model_access: ModelAccess
    licence_category: LicenceCategory
    total_parameters: str | None
    active_parameters: str | None
    provider_name: str
    provider_endpoint: str
    routing_policy: str
    generation_controls: GenerationControls

    def snapshot(self, returned_model_version: str | None = None, preflight_passed: bool = False) -> ProviderSnapshot:
        """Build a hash-bound provider snapshot from the catalog entry."""
        metadata = self.model_dump(mode="json")
        return ProviderSnapshot(
            **self.model_dump(exclude={"generation_controls"}),
            returned_model_version=returned_model_version,
            metadata_snapshot_sha256=artifact_sha256(metadata),
            preflight_passed=preflight_passed,
        )


class CompletedWorkflowModel(ImmutableModel):
    """Record the model and immutable provenance for a completed model workflow."""

    workflow: Literal["scenario_fact_generation_v1"]
    model_slug: str
    returned_model_version: str
    model_access: ModelAccess
    licence_category: LicenceCategory
    provider_name: str
    provider_endpoint: str
    routing_policy: str
    preflight_passed: Literal[True]
    run_config_path: str
    run_results_path: str


class ModelCatalog(ImmutableModel):
    """Represent the generator, seven evaluated models, and scoring judge."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    description: str
    scenario_generation_model: CompletedWorkflowModel
    evaluated_models: List[CatalogEntry] = Field(min_length=7, max_length=7)
    scoring_model: CatalogEntry

    @model_validator(mode="after")
    def validate_unique_models(self) -> "ModelCatalog":
        """Require seven unique evaluated models and a distinct scoring judge."""
        slugs = [entry.model_slug for entry in self.evaluated_models]
        if len(set(slugs)) != 7 or self.scoring_model.model_slug in slugs:
            raise ValueError("model catalog must contain seven unique evaluated models and a distinct judge")
        return self


def load_model_catalog() -> ModelCatalog:
    """Load the package-owned model catalog used by the study."""
    catalog_path = files("src.settings").joinpath("models.json")
    return ModelCatalog.model_validate(json.loads(catalog_path.read_text(encoding="utf-8")))
