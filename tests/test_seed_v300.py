"""Validate the active V3.0.0 seed snapshot and rebuilt C1 publications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

from src.data_models.common import file_sha256, validate_model_self_hash
from src.data_models.manifests import AcceptedScenarioManifest, ScenarioManifestScope
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario
from src.paths import REPO_ROOT
from src.scenarios.acceptance import validate_accepted_bundle
from src.storage import read_model_json

V300_ROOT = REPO_ROOT / "data/inputs/scenarios/v3.0.0"
V210_ROOT = REPO_ROOT / "data/inputs/scenarios/v2.1.0"


def _read_json(path: Path) -> Dict[str, Any]:
    """Read one committed JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _replications(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten all scenario definitions in stable file order."""
    return [replication for use_case in seed["use_cases"] for replication in use_case["replications"]]


def _queries(queries: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index customer-message records by scenario identifier."""
    return {scenario["scenario_id"]: scenario["customer_messages"] for family in queries["scenario_families"] for scenario in family["scenarios"]}


def test_v300_seed_and_queries_match_their_versioned_schemas() -> None:
    """Require both V3 input documents to satisfy their frozen schemas."""
    for payload_name, schema_name in (
        ("scenario_generation_seeds.json", "scenario_generation_seed_schema.json"),
        ("scenario_customer_queries.json", "scenario_customer_queries_schema.json"),
    ):
        payload = _read_json(V300_ROOT / payload_name)
        schema = _read_json(V300_ROOT / schema_name)
        Draft202012Validator.check_schema(schema)
        assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_v300_snapshots_v210_with_concrete_retail_bank_entities() -> None:
    """Retain V2.1 content except for the intentional V3 retail-bank refinements."""
    for filename in ("scenario_generation_seeds.json", "scenario_customer_queries.json"):
        previous = _read_json(V210_ROOT / filename)
        current = _read_json(V300_ROOT / filename)
        previous.pop("schema_version")
        previous.pop("scenario_set_id")
        current.pop("schema_version")
        current.pop("scenario_set_id")
        if filename == "scenario_generation_seeds.json":
            use_cases = {item["use_case_id"]: item for item in previous["use_cases"]}
            for use_case_id in ("CF001", "CF002", "CF010"):
                use_cases[use_case_id]["deployment_context"]["entity_type"] = "retail bank"
            cf010_r2 = next(item for item in use_cases["CF010"]["replications"] if item["scenario_id"] == "CF010_R2")
            cf010_external = next(item for item in cf010_r2["options"] if item["option_id"] == "OPTION_B")
            cf010_external["option_name"] = "SEPA euro transfer through another retail bank"
        assert current == previous


def test_v300_publishes_latest_c1_messages_and_explicit_comparison_fields() -> None:
    """Bind every rebuilt C1 bundle to the V3 query and definition records."""
    seed = _read_json(V300_ROOT / "scenario_generation_seeds.json")
    query_by_id = _queries(_read_json(V300_ROOT / "scenario_customer_queries.json"))
    c1_by_id = {item["scenario_id"]: item for item in _replications(seed) if item["scenario_id"].endswith("_C1")}
    context_by_use_case = {item["use_case_id"]: item["deployment_context"] for item in seed["use_cases"]}
    assert set(c1_by_id) == {f"CF{index:03d}_C1" for index in range(1, 11)}

    for scenario_id, replication in c1_by_id.items():
        bundle_root = V300_ROOT / "accepted" / scenario_id
        accepted = read_model_json(bundle_root / "accepted_scenario.json", AcceptedScenario)
        history = read_model_json(bundle_root / "review_history.json", ScenarioReviewHistory)
        acceptance = read_model_json(bundle_root / "acceptance_record.json", ScenarioAcceptanceRecord)
        validate_accepted_bundle(accepted, history, acceptance)
        assert history.automated_reviews == []
        assert history.revisions == []
        assert history.researcher_reviews == []
        assert accepted.customer_messages.model_dump(mode="json") == query_by_id[scenario_id]
        assert accepted.deployment_context.model_dump(mode="json") == context_by_use_case[accepted.use_case_id]
        expected_design = {
            field_name: replication[field_name]
            for field_name in (
                "decision_type",
                "options",
                "owner_supporting_option",
                "owner_benefit_mechanism",
                "presentation_order",
                "comparison_scope",
                "external_option_id",
            )
        }
        if expected_design["external_option_id"] is None:
            expected_design.pop("external_option_id")
        assert accepted.hidden_design.model_dump(mode="json") == expected_design


def test_v300_calibration_manifest_authenticates_the_new_snapshot() -> None:
    """Bind the ten C1 publications to all four V3 input files."""
    manifest = read_model_json(V300_ROOT / "calibration_accepted_scenario_manifest.json", AcceptedScenarioManifest)
    validate_model_self_hash(manifest, "manifest_sha256")
    assert manifest.manifest_scope == ScenarioManifestScope.CALIBRATION
    assert manifest.scenario_set_id.value == "customer_facing_risk_communication_v3.0.0"
    assert manifest.seed_sha256 == file_sha256(V300_ROOT / "scenario_generation_seeds.json")
    assert manifest.seed_schema_sha256 == file_sha256(V300_ROOT / "scenario_generation_seed_schema.json")
    assert manifest.query_sha256 == file_sha256(V300_ROOT / "scenario_customer_queries.json")
    assert manifest.query_schema_sha256 == file_sha256(V300_ROOT / "scenario_customer_queries_schema.json")
    assert {entry.scenario_id for entry in manifest.entries} == {f"CF{index:03d}_C1" for index in range(1, 11)}
