"""Execution-bundle materialization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.common import artifact_sha256
from src.experiments.accounting import execute_bundle_batch
from src.experiments.matrix import build_matrix
from src.experiments.planner import build_execution_bundles
from src.experiments.runner import write_run_cache
from src.llm.openrouter import OpenRouterClient
from src.models.catalog import load_model_catalog
from src.models.enums import Affect, CommercialInterestInstruction, CommercialInterestTask, ReviewState
from src.models.experiments import AttemptMetadata, CommercialInterestCell, ResponseMetadata, RunUnit
from src.models.manifests import CostApproval, ProtocolManifest
from src.models.queries import AuthoredQueryFamily, QueryVariant
from src.models.scenarios import AcceptedScenario, ScenarioReview
from src.models.seeds import ScenarioSeedSet
from src.paths import SCENARIO_ROOT
from src.protocol import PreflightResult, freeze_protocol_manifest
from src.scenarios.queries import build_user_state_queries
from src.storage import read_jsonl


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


def test_commercial_bundle_uses_its_short_affect_query(
    tmp_path: Path,
    seed_set: ScenarioSeedSet,
    accepted_scenario: AcceptedScenario,
) -> None:
    """Resolve commercial-interest cells to short queries at their assigned affect."""
    catalog = load_model_catalog()
    assignments = build_matrix(seed_set, [entry.model_slug for entry in catalog.evaluated_models])
    assignment = next(
        item
        for item in assignments
        if item.scenario_id == accepted_scenario.scenario_id
        and isinstance(item.cell, CommercialInterestCell)
        and item.cell.affect == Affect.FRUSTRATED
        and item.cell.instruction == CommercialInterestInstruction.PROTECT_COMMERCIAL_INTERESTS
        and item.cell.task == CommercialInterestTask.STANDARD
    )
    queries = _queries()
    scenarios = [_accepted(accepted_scenario)]
    bundle = build_execution_bundles(
        [assignment],
        scenarios,
        queries,
        _manifest(tmp_path / "manifest.json", scenarios, queries),
    )[0]
    assert bundle.prompt.query_variant_id == f"{assignment.scenario_id}_frustrated_short"
    assert "protect the commercial interests" in bundle.prompt.messages[0]["content"]


def test_commercial_batch_reuses_a_cached_run_without_calling_provider(
    tmp_path: Path,
    seed_set: ScenarioSeedSet,
    accepted_scenario: AcceptedScenario,
) -> None:
    """Resume the same experiment ID by skipping an already cached semantic response."""
    catalog = load_model_catalog()
    assignment = next(
        item
        for item in build_matrix(seed_set, [entry.model_slug for entry in catalog.evaluated_models])
        if item.scenario_id == accepted_scenario.scenario_id and isinstance(item.cell, CommercialInterestCell)
    )
    queries = _queries()
    scenarios = [_accepted(accepted_scenario)]
    manifest = _manifest(tmp_path / "manifest.json", scenarios, queries)
    bundle = build_execution_bundles([assignment], scenarios, queries, manifest)[0]
    timestamp = datetime(2026, 8, 17, tzinfo=UTC)
    cached = RunUnit(
        run_unit_id=assignment.assignment_id,
        experiment=assignment.cell.kind,
        cell=assignment.cell,
        scenario_id=assignment.scenario_id,
        query_variant_id=bundle.prompt.query_variant_id,
        prompt_sha256=bundle.prompt.prompt_sha256,
        response_contract_sha256=bundle.prompt.response_contract_sha256,
        model=bundle.model,
        generation_controls=bundle.generation_controls,
        response=ResponseMetadata(
            raw_response="Cached semantic response.",
            structurally_valid=True,
            adherent=True,
            billed_cost=Decimal("0.01"),
            received_at=timestamp,
        ),
        attempts=[
            AttemptMetadata(
                attempt_number=1,
                started_at=timestamp,
                completed_at=timestamp,
                semantic_response_received=True,
            )
        ],
    )
    cache_directory = tmp_path / "cache"
    write_run_cache(cache_directory / f"{assignment.assignment_id}.json", cached)
    approval_base = {
        "schema_version": "4.0.0",
        "protocol_manifest_sha256": manifest.manifest_sha256,
        "estimated_max_cost": Decimal("1.00"),
        "currency": "USD",
        "approved_max_cost": Decimal("1.00"),
        "approved_by": "test researcher",
        "approved_at": timestamp,
        "approval_note": "cache resume test",
    }
    approval = CostApproval.model_validate({**approval_base, "approval_sha256": artifact_sha256(approval_base)})

    def fail_if_called() -> OpenRouterClient:
        """Prove that a completed assignment never constructs a provider client."""
        raise AssertionError("provider client should not be constructed for a cached run")

    resumed = execute_bundle_batch(
        [bundle],
        cache_directory,
        fail_if_called,
        approval,
        prior_billed_cost=Decimal("0"),
        reserved_cost_per_call=Decimal("0.10"),
        max_workers=1,
    )
    assert resumed == [cached]
