"""Execution-bundle materialization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from srcv2.common import artifact_sha256
from srcv2.experiments.matrix import build_matrix
from srcv2.experiments.planner import build_execution_bundles
from srcv2.models.catalog import load_model_catalog
from srcv2.models.enums import ReviewState
from srcv2.models.manifests import ProtocolManifest
from srcv2.models.queries import AuthoredQueryFamily, QueryVariant
from srcv2.models.scenarios import AcceptedScenario, ScenarioReview
from srcv2.models.seeds import ScenarioSeedSet
from srcv2.paths import SCENARIO_ROOT
from srcv2.protocol import PreflightResult, freeze_protocol_manifest
from srcv2.scenarios.queries import build_user_state_queries
from srcv2.storage import read_jsonl


def _queries() -> list[QueryVariant]:
    """Load the approved query family used by the scenario fixture."""
    family = AuthoredQueryFamily.model_validate(read_jsonl(SCENARIO_ROOT / "query_families.jsonl")[0])
    return build_user_state_queries(family)


def _accepted(scenario: AcceptedScenario) -> AcceptedScenario:
    """Mark a valid fixture as researcher accepted for bundle materialization."""
    return AcceptedScenario.model_validate(
        {
            **scenario.model_dump(mode="json", exclude={"review"}),
            "review": ScenarioReview(
                state=ReviewState.ACCEPTED,
                researcher_id="researcher-1",
                rationale="Accepted for bundle test.",
                reviewed_at="2026-08-15T12:00:00Z",
            ),
        }
    )


def _manifest(path: Path, scenarios: list[AcceptedScenario], queries: list[QueryVariant]) -> ProtocolManifest:
    """Freeze a complete test provider panel."""
    catalog = load_model_catalog()
    entries = [*catalog.evaluated_models, catalog.scoring_model]
    results = [
        PreflightResult(
            model_slug=entry.model_slug,
            returned_model_version=f"{entry.model_slug}@test",
            provider_name="pinned-test-provider",
            provider_endpoint="openrouter:test",
            accepted_controls=["max_output_tokens"],
            rejected_controls=[],
            semantic_response_received=True,
            completed_at=datetime(2026, 8, 15, tzinfo=UTC),
            provider_request_id=f"test-request-{index}",
        )
        for index, entry in enumerate(entries)
    ]
    corpus_hash = artifact_sha256({"scenarios": scenarios, "queries": queries})
    return freeze_protocol_manifest(catalog, results, corpus_hash, path)


def test_bundle_materialization_binds_accepted_scenario_query_and_model(
    tmp_path: Path,
    seed_set: ScenarioSeedSet,
    accepted_scenario: AcceptedScenario,
) -> None:
    """Resolve one assignment into an exact prompt and frozen provider bundle."""
    catalog = load_model_catalog()
    assignments = build_matrix(seed_set, [entry.model_slug for entry in catalog.evaluated_models])
    assignment = next(item for item in assignments if item.scenario_id == accepted_scenario.scenario_id)
    queries = _queries()
    scenarios = [_accepted(accepted_scenario)]
    bundles = build_execution_bundles(
        [assignment],
        scenarios,
        queries,
        _manifest(tmp_path / "manifest.json", scenarios, queries),
    )
    assert len(bundles) == 1
    assert bundles[0].assignment == assignment
    assert bundles[0].model.model_slug == assignment.model_slug
    assert bundles[0].prompt.query_variant_id == f"{assignment.scenario_id}_neutral_short"
    assert len(set(bundles[0].valid_fact_ids)) == 6


def test_bundle_materialization_rejects_pending_scenarios(
    tmp_path: Path,
    seed_set: ScenarioSeedSet,
    accepted_scenario: AcceptedScenario,
) -> None:
    """Fail closed before the required researcher acceptance exists."""
    catalog = load_model_catalog()
    assignment = build_matrix(seed_set, [entry.model_slug for entry in catalog.evaluated_models])[0]
    queries = _queries()
    scenarios = [accepted_scenario]
    with pytest.raises(PermissionError):
        build_execution_bundles([assignment], scenarios, queries, _manifest(tmp_path / "manifest.json", scenarios, queries))
