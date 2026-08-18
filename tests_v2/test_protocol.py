"""Model-catalog, preflight, manifest, and approval tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from srcv2.common import artifact_sha256, utc_now
from srcv2.models.catalog import load_model_catalog
from srcv2.models.enums import ModelAccess
from srcv2.models.manifests import CostApproval, PreflightApproval, ProtocolManifest
from srcv2.protocol import PreflightResult, freeze_protocol_manifest
from srcv2.storage import read_json


def _preflight_results() -> list[PreflightResult]:
    """Build complete successful test probes for the declared model catalog."""
    catalog = load_model_catalog()
    assert "pending" not in catalog.model_dump_json()
    entries = [*catalog.evaluated_models, catalog.scoring_model]
    return [
        PreflightResult(
            model_slug=entry.model_slug,
            returned_model_version=f"{entry.model_slug}@test",
            provider_name="pinned-test-provider",
            provider_endpoint="openrouter:test",
            accepted_controls=["max_output_tokens"],
            rejected_controls=[],
            semantic_response_received=True,
            completed_at=utc_now(),
            provider_request_id=f"test-request-{index}",
        )
        for index, entry in enumerate(entries)
    ]


def test_catalog_freezes_exact_models_and_parameter_metadata() -> None:
    """Declare the completed generator, exact panel, judge, access split, and parameters."""
    catalog = load_model_catalog()
    assert catalog.scenario_generation_model.model_slug == "openai/gpt-5.4"
    assert catalog.scenario_generation_model.returned_model_version == "openai/gpt-5.4"
    assert catalog.scenario_generation_model.preflight_passed is True
    assert catalog.scenario_generation_model.run_config_path == "data/outputs/scenario_generation/v4.0.1/scenario_fact_generation_v1/config.json"
    assert [entry.model_slug for entry in catalog.evaluated_models] == [
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
        "meta-llama/llama-4-maverick",
        "qwen/qwen3.5-122b-a10b",
        "deepseek/deepseek-v4-pro",
        "openai/gpt-5.4",
        "anthropic/claude-sonnet-5",
    ]
    assert [entry.model_access for entry in catalog.evaluated_models].count(ModelAccess.OPEN_WEIGHT) == 5
    assert [entry.model_access for entry in catalog.evaluated_models].count(ModelAccess.CLOSED) == 2
    assert catalog.scoring_model.model_slug == "google/gemini-3.1-flash-lite"
    assert catalog.scoring_model.generation_controls.reasoning_effort == "medium"
    deepseek = catalog.evaluated_models[4]
    assert (deepseek.total_parameters, deepseek.active_parameters) == ("1.6T", "49B")


def test_manifest_and_approval_hashes_survive_json_round_trip(tmp_path: Path) -> None:
    """Bind nested enums, models, decimals, and UTC timestamps to stable artifact hashes."""
    catalog = load_model_catalog()
    manifest_path = tmp_path / "protocol_manifest.json"
    manifest = freeze_protocol_manifest(catalog, _preflight_results(), "a" * 64, manifest_path)
    assert sum(manifest.expected_response_counts.values()) == 10710
    assert ProtocolManifest.model_validate(read_json(manifest_path)) == manifest

    preflight_base = {
        "schema_version": "4.0.0",
        "model_catalog_sha256": artifact_sha256(catalog),
        "estimated_max_cost": Decimal("1.00"),
        "approved_max_cost": Decimal("1.00"),
        "currency": "USD",
        "approved_by": "test reviewer",
        "approved_at": utc_now(),
        "approval_note": "serialization test",
    }
    PreflightApproval.model_validate({**preflight_base, "approval_sha256": artifact_sha256(preflight_base)})
    cost_base = {
        "schema_version": "4.0.0",
        "protocol_manifest_sha256": manifest.manifest_sha256,
        "estimated_max_cost": Decimal("10.00"),
        "currency": "USD",
        "approved_max_cost": Decimal("10.00"),
        "approved_by": "test reviewer",
        "approved_at": utc_now(),
        "approval_note": "serialization test",
    }
    CostApproval.model_validate({**cost_base, "approval_sha256": artifact_sha256(cost_base)})
