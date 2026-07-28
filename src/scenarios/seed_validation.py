"""Validate and join the immutable active V2.0.0 scenario inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

from src.data_models.common import file_sha256
from src.data_models.scenarios import LoadedScenarioSeedSet, ScenarioQuerySet, ScenarioReplicationSeed, ScenarioSeedSet, ScenarioUseCaseSeed
from src.paths import (
    ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
    ACTIVE_SCENARIO_QUERY_SHA256,
    ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
    ACTIVE_SCENARIO_SEED_SHA256,
    ACTIVE_SCENARIO_SEED_VERSION,
)

EXPECTED_SEED_SHA256 = ACTIVE_SCENARIO_SEED_SHA256
EXPECTED_SCHEMA_SHA256 = ACTIVE_SCENARIO_SEED_SCHEMA_SHA256
EXPECTED_QUERY_SHA256 = ACTIVE_SCENARIO_QUERY_SHA256
EXPECTED_QUERY_SCHEMA_SHA256 = ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256
FORBIDDEN_STUDY_KEYS = {
    "word_budget",
    "word_limit",
    "emotional_cue",
    "expressed_concern",
    "worried_cue",
    "neutral_cue",
    "integrity_instruction",
    "integrity_condition",
    "follow_up",
    "initial_message",
    "follow_up_message",
    "customer_supporting_option",
    "temperature",
    "model_id",
    "scoring_model",
    "source_order",
    "fact_count",
    "review_threshold",
}


def _collect_forbidden_keys(value: Any, path: str = "$") -> List[str]:
    """Return forbidden code-owned keys found recursively in seed JSON."""
    findings: List[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_STUDY_KEYS:
                findings.append(child_path)
            findings.extend(_collect_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_collect_forbidden_keys(child, f"{path}[{index}]"))
    return findings


def validate_seed_hashes(
    seed_path: Path,
    schema_path: Path,
    query_path: Path,
    query_schema_path: Path,
) -> Dict[str, str]:
    """Require all active definition and query artifacts to match approved bytes."""
    hashes = {
        "seed_sha256": file_sha256(seed_path),
        "schema_sha256": file_sha256(schema_path),
        "query_sha256": file_sha256(query_path),
        "query_schema_sha256": file_sha256(query_schema_path),
    }
    version = seed_path.parent.name
    if version != ACTIVE_SCENARIO_SEED_VERSION or {query_path.parent, schema_path.parent, query_schema_path.parent} != {seed_path.parent}:
        raise ValueError(f"only the active seed version is supported: {ACTIVE_SCENARIO_SEED_VERSION}")
    if hashes["seed_sha256"] != EXPECTED_SEED_SHA256:
        raise ValueError(f"{version} seed bytes differ from the approved artifact")
    if hashes["schema_sha256"] != EXPECTED_SCHEMA_SHA256:
        raise ValueError(f"{version} seed schema bytes differ from the approved artifact")
    if hashes["query_sha256"] != EXPECTED_QUERY_SHA256:
        raise ValueError(f"{version} query bytes differ from the approved artifact")
    if hashes["query_schema_sha256"] != EXPECTED_QUERY_SCHEMA_SHA256:
        raise ValueError(f"{version} query schema bytes differ from the approved artifact")
    return hashes


def _validate_json_artifact(payload_path: Path, schema_path: Path, artifact_name: str) -> Dict[str, Any]:
    """Validate one JSON object against its Draft 2020-12 schema."""
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{artifact_name} must be a JSON object")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(f"{'.'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in errors)
        raise ValueError(f"{artifact_name} JSON Schema validation failed: {details}")
    return payload


def _join_scenario_inputs(seed: ScenarioSeedSet, queries: ScenarioQuerySet) -> LoadedScenarioSeedSet:
    """Join query records to scenario definitions after exact identifier validation."""
    query_by_scenario_id = {scenario.scenario_id: scenario.customer_messages for family in queries.scenario_families for scenario in family.scenarios}
    definition_ids = {replication.scenario_id for use_case in seed.use_cases for replication in use_case.replications}
    if set(query_by_scenario_id) != definition_ids:
        raise ValueError("scenario definitions and customer queries must contain the same exact scenario ids")
    return LoadedScenarioSeedSet(
        use_cases=[
            ScenarioUseCaseSeed(
                use_case_id=use_case.use_case_id,
                deployment_context=use_case.deployment_context,
                replications=[
                    ScenarioReplicationSeed(
                        **replication.model_dump(mode="python"),
                        customer_messages=query_by_scenario_id[replication.scenario_id],
                    )
                    for replication in use_case.replications
                ],
            )
            for use_case in seed.use_cases
        ]
    )


def load_and_validate_seed(
    seed_path: Path,
    schema_path: Path,
    query_path: Path,
    query_schema_path: Path,
) -> LoadedScenarioSeedSet:
    """Authenticate, validate, and exactly join scenario definitions and queries."""
    validate_seed_hashes(
        seed_path=seed_path,
        schema_path=schema_path,
        query_path=query_path,
        query_schema_path=query_schema_path,
    )
    payload = _validate_json_artifact(seed_path, schema_path, "seed")
    query_payload = _validate_json_artifact(query_path, query_schema_path, "query")
    forbidden_paths = _collect_forbidden_keys(payload)
    if forbidden_paths:
        raise ValueError("seed contains code-owned study keys: " + ", ".join(forbidden_paths))
    seed = ScenarioSeedSet.model_validate(payload)
    queries = ScenarioQuerySet.model_validate(query_payload)
    if seed.scenario_set_id != queries.scenario_set_id:
        raise ValueError("scenario definitions and customer queries must share one scenario_set_id")
    return _join_scenario_inputs(seed, queries)
