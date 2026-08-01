"""Validate the draft V2.1.0 scenario seed and its comparison-scope design."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

from src.data_models.common import file_sha256, validate_model_self_hash
from src.data_models.manifests import AcceptedScenarioManifest, ScenarioManifestScope
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.paths import REPO_ROOT
from src.scenarios.acceptance import validate_accepted_bundle
from src.scenarios.candidate_compatibility import read_accepted_scenario
from src.storage import read_model_json

V210_ROOT = REPO_ROOT / "data/inputs/scenarios/v2.1.0"
V200_ROOT = REPO_ROOT / "data/inputs/scenarios/v2.0.0"


def _read_json(path: Path) -> Dict[str, Any]:
    """Read one JSON object from the fixed test artifact path."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _replications(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten all scenario replication definitions in stable file order."""
    return [replication for use_case in seed["use_cases"] for replication in use_case["replications"]]


def test_v210_seed_and_queries_match_their_schemas() -> None:
    """Require both V2.1.0 input documents to pass their committed JSON Schemas."""
    artifacts = [
        ("scenario_generation_seeds.json", "scenario_generation_seed_schema.json"),
        ("scenario_customer_queries.json", "scenario_customer_queries_schema.json"),
    ]
    for payload_name, schema_name in artifacts:
        payload = _read_json(V210_ROOT / payload_name)
        schema = _read_json(V210_ROOT / schema_name)
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(payload))
        assert errors == []


def test_v210_preserves_c1_design_and_allows_query_wording_to_change_in_place() -> None:
    """Keep C1 decision designs fixed while allowing non-leading query edits in the active file."""
    current_seed = _read_json(V200_ROOT / "scenario_generation_seeds.json")
    revised_seed = _read_json(V210_ROOT / "scenario_generation_seeds.json")
    current_c1 = {item["scenario_id"]: item for item in _replications(current_seed) if item["scenario_id"].endswith("_C1")}
    revised_c1 = [item for item in _replications(revised_seed) if item["scenario_id"].endswith("_C1")]

    for replication in revised_c1:
        content = deepcopy(replication)
        content.pop("comparison_scope")
        content.pop("external_option_id")
        assert content == current_c1[replication["scenario_id"]]
    assert sum(item["comparison_scope"] == "intra_provider" for item in revised_c1) == 6
    assert sum(item["comparison_scope"] == "provider_vs_external" for item in revised_c1) == 4

    current_queries = _read_json(V200_ROOT / "scenario_customer_queries.json")
    revised_queries = _read_json(V210_ROOT / "scenario_customer_queries.json")
    current_c1_queries = {
        item["scenario_id"]: item
        for family in current_queries["scenario_families"]
        for item in family["scenarios"]
        if item["scenario_id"].endswith("_C1")
    }
    revised_c1_queries = {
        item["scenario_id"]: item
        for family in revised_queries["scenario_families"]
        for item in family["scenarios"]
        if item["scenario_id"].endswith("_C1")
    }
    assert revised_c1_queries != current_c1_queries
    assert all(
        item["customer_messages"][condition].endswith("What should I consider?")
        for item in revised_c1_queries.values()
        for condition in ("neutral_user_query", "concerned_user_query")
    )


def test_v210_r1_and_r2_enforce_the_new_option_relationships() -> None:
    """Require every R1 to be internal and every R2 to identify one non-owner external option."""
    seed = _read_json(V210_ROOT / "scenario_generation_seeds.json")
    replications = _replications(seed)
    for replication in replications:
        stage = replication["scenario_id"].rsplit("_", maxsplit=1)[1]
        if replication["comparison_scope"] == "intra_provider":
            assert replication["external_option_id"] is None
        else:
            assert replication["external_option_id"] in {"OPTION_A", "OPTION_B"}
            assert replication["external_option_id"] != replication["owner_supporting_option"]
        if stage == "R1":
            assert replication["comparison_scope"] == "intra_provider"
        if stage == "R2":
            assert replication["comparison_scope"] == "provider_vs_external"


def test_v210_retains_stage_specific_counterbalancing_and_query_coverage() -> None:
    """Balance option mappings within every stage and retain one query record per scenario."""
    seed = _read_json(V210_ROOT / "scenario_generation_seeds.json")
    queries = _read_json(V210_ROOT / "scenario_customer_queries.json")
    replications = _replications(seed)
    for stage in ("C1", "R1", "R2"):
        stage_replications = [item for item in replications if item["scenario_id"].endswith(f"_{stage}")]
        assert sum(item["owner_supporting_option"] == "OPTION_A" for item in stage_replications) == 5
        assert sum(item["presentation_order"][0] == "OPTION_A" for item in stage_replications) == 5
    query_records = [scenario for family in queries["scenario_families"] for scenario in family["scenarios"]]
    assert {item["scenario_id"] for item in query_records} == {item["scenario_id"] for item in replications}
    assert len({item["customer_messages"]["follow_up_query"] for item in query_records}) == 1


def test_v210_retains_the_accepted_c1_bundles_byte_for_byte() -> None:
    """Carry every immutable accepted C1 artifact and its review provenance into V2.1.0 unchanged."""
    current_root = V200_ROOT / "accepted"
    revised_root = V210_ROOT / "accepted"
    current_files = sorted(path.relative_to(current_root) for path in current_root.rglob("*.json"))
    revised_files = sorted(path.relative_to(revised_root) for path in revised_root.rglob("*.json"))
    assert revised_files == current_files
    assert len(revised_files) == 30
    for relative_path in current_files:
        assert (revised_root / relative_path).read_bytes() == (current_root / relative_path).read_bytes()


def test_v210_historical_c1_bundles_remain_valid_after_query_edits() -> None:
    """Keep earlier publications readable without treating current query text as an ownership gate."""
    seed = _read_json(V210_ROOT / "scenario_generation_seeds.json")
    queries = _read_json(V210_ROOT / "scenario_customer_queries.json")
    c1_by_id = {item["scenario_id"]: item for item in _replications(seed) if item["scenario_id"].endswith("_C1")}
    deployment_by_use_case = {item["use_case_id"]: item["deployment_context"] for item in seed["use_cases"]}
    del queries

    for scenario_id, replication in c1_by_id.items():
        bundle_root = V210_ROOT / "accepted" / scenario_id
        accepted = read_accepted_scenario(bundle_root / "accepted_scenario.json")
        history = read_model_json(bundle_root / "review_history.json", ScenarioReviewHistory)
        acceptance = read_model_json(bundle_root / "acceptance_record.json", ScenarioAcceptanceRecord)
        validate_accepted_bundle(accepted, history, acceptance)
        assert accepted.use_case_id == scenario_id.removesuffix("_C1")
        assert accepted.deployment_context.model_dump(mode="json") == deployment_by_use_case[accepted.use_case_id]
        expected_hidden_design = {
            field: replication[field]
            for field in (
                "decision_type",
                "options",
                "owner_supporting_option",
                "owner_benefit_mechanism",
                "presentation_order",
            )
        }
        assert accepted.hidden_design.model_dump(mode="json") == expected_hidden_design


def test_v210_calibration_manifest_rebinds_retained_c1s_to_v210_inputs() -> None:
    """Publish retained C1 bundles under the V2.1.0 input hashes without changing their artifact identities."""
    manifest_path = V210_ROOT / "calibration_accepted_scenario_manifest.json"
    manifest = read_model_json(manifest_path, AcceptedScenarioManifest)
    validate_model_self_hash(manifest, "manifest_sha256")
    assert manifest.manifest_scope == ScenarioManifestScope.CALIBRATION
    assert manifest.scenario_set_id.value == "customer_facing_risk_communication_v2.1.0"
    assert manifest.seed_sha256 == file_sha256(V210_ROOT / "scenario_generation_seeds.json")
    assert manifest.seed_schema_sha256 == file_sha256(V210_ROOT / "scenario_generation_seed_schema.json")
    assert manifest.query_sha256 == file_sha256(V210_ROOT / "scenario_customer_queries.json")
    assert manifest.query_schema_sha256 == file_sha256(V210_ROOT / "scenario_customer_queries_schema.json")
    assert {entry.scenario_id for entry in manifest.entries} == {f"CF{index:03d}_C1" for index in range(1, 11)}
