"""Final model preflight and protocol-manifest freezing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from pydantic import Field

from src.common import ImmutableModel, artifact_sha256, utc_now
from src.experiments.matrix import ACTIVE_RESPONSE_COUNTS
from src.models.catalog import CatalogEntry, ModelCatalog
from src.models.experiments import GenerationControls, ProviderSnapshot
from src.models.manifests import ProtocolManifest
from src.storage import write_json


class PreflightResult(ImmutableModel):
    """Record one operational compatibility result before model freezing."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    model_slug: str
    returned_model_version: str
    provider_name: str
    provider_endpoint: str
    accepted_controls: List[str]
    rejected_controls: List[str]
    semantic_response_received: bool
    completed_at: datetime
    provider_request_id: str


def _preflighted_snapshot(entry: CatalogEntry, result: PreflightResult) -> ProviderSnapshot:
    """Join a declared model entry to its successful operational probe."""
    if entry.model_slug != result.model_slug or not result.semantic_response_received:
        raise ValueError(f"unsuccessful or mismatched preflight for {entry.model_slug}")
    metadata = {
        **entry.model_dump(mode="json"),
        "returned_model_version": result.returned_model_version,
        "provider_name": result.provider_name,
        "provider_endpoint": result.provider_endpoint,
        "accepted_controls": sorted(result.accepted_controls),
        "rejected_controls": sorted(result.rejected_controls),
        "preflight_completed_at": result.completed_at.isoformat(),
        "provider_request_id": result.provider_request_id,
    }
    uses_default_routing = entry.routing_policy == "openrouter_default_require_parameters"
    return ProviderSnapshot(
        model_slug=entry.model_slug,
        returned_model_version=result.returned_model_version,
        model_access=entry.model_access,
        licence_category=entry.licence_category,
        total_parameters=entry.total_parameters,
        active_parameters=entry.active_parameters,
        provider_name=entry.provider_name if uses_default_routing else result.provider_name,
        provider_endpoint=entry.provider_endpoint if uses_default_routing else result.provider_endpoint,
        routing_policy=entry.routing_policy,
        metadata_snapshot_sha256=artifact_sha256(metadata),
        preflight_passed=True,
    )


def freeze_protocol_manifest(
    catalog: ModelCatalog,
    preflight_results: List[PreflightResult],
    scenario_manifest_sha256: str,
    output_path: Path,
) -> ProtocolManifest:
    """Freeze the seven-model panel, judge, controls, and active response matrix."""
    by_slug = {result.model_slug: result for result in preflight_results}
    required = [entry.model_slug for entry in catalog.evaluated_models] + [catalog.scoring_model.model_slug]
    if set(by_slug) != set(required):
        raise ValueError("preflight results must cover exactly the seven evaluated models and scoring judge")
    evaluated = [_preflighted_snapshot(entry, by_slug[entry.model_slug]) for entry in catalog.evaluated_models]
    scorer = _preflighted_snapshot(catalog.scoring_model, by_slug[catalog.scoring_model.model_slug])
    controls: Dict[str, GenerationControls] = {
        entry.model_slug: entry.generation_controls for entry in [*catalog.evaluated_models, catalog.scoring_model]
    }
    frozen_at = utc_now()
    base = {
        "schema_version": "4.0.0",
        "protocol_id": "final_protocol",
        "scenario_manifest_sha256": scenario_manifest_sha256,
        "experiments": list(ACTIVE_RESPONSE_COUNTS),
        "expected_response_counts": ACTIVE_RESPONSE_COUNTS,
        "evaluated_models": evaluated,
        "scorer_model": scorer,
        "generation_controls": controls,
        "frozen_at": frozen_at,
    }
    manifest = ProtocolManifest(
        scenario_manifest_sha256=scenario_manifest_sha256,
        experiments=list(ACTIVE_RESPONSE_COUNTS),
        expected_response_counts=ACTIVE_RESPONSE_COUNTS,
        evaluated_models=evaluated,
        scorer_model=scorer,
        generation_controls=controls,
        frozen_at=frozen_at,
        manifest_sha256=artifact_sha256(base),
    )
    write_json(output_path, manifest)
    return manifest
