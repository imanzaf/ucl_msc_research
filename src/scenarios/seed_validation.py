"""Validate immutable archived seeds and the active V0.9.0 seed boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

from src.data_models.common import file_sha256
from src.data_models.scenarios import ScenarioSeedSet, V09UseCaseSeed
from src.paths import ACTIVE_SCENARIO_SEED_SCHEMA_SHA256, ACTIVE_SCENARIO_SEED_SHA256, ACTIVE_SCENARIO_SEED_VERSION

EXPECTED_HASHES = {
    "v0.5.1": (
        "ecf3e81761cd5dc6543bb5dd21a153ff8dff9813a937da90f2aa144c672b1b72",
        "7f2eba17550ad915177d15351bebb767898c138e023e149c75f69a7bd249dcfe",
    ),
    "v0.5.2": (
        "ce21fd98368a0f0719a5fdad0a4e5793510be58f4f7367d8339bec6fdbb3d389",
        "480e40d7d05f38500ccc2bdfcd792c7ed1a8eb0583beba1c3ab15f4a5b28f130",
    ),
    "v0.6.0": (
        "b282337daa6c501cdcc4b5d7d5b719ae5cd1f9bafa51676c7d8c7f4f611e0cf2",
        "9a3b04d3f22c3eb5f907853b29f307c519e8b1f4766775770fac6d447aeec574",
    ),
    "v0.7.0": (
        "e8eb485607baa3e18bf1073d0273efb827f2167fdd5b76efc5e9f85d66a79e90",
        "8e1683ada8351db03c1e909c8f13919c984425ec6bf3cf5f252ce1d575bc3eac",
    ),
    "v0.8.0": (
        "d5880fa2935810cf2a90ca522175c94bfe96cb5634dca12fb507f9715068000c",
        "458dc64d85712dde77492be0ee4ddc3d30eaaaaafc05964f522cfbf4af93536e",
    ),
    ACTIVE_SCENARIO_SEED_VERSION: (ACTIVE_SCENARIO_SEED_SHA256, ACTIVE_SCENARIO_SEED_SCHEMA_SHA256),
}
EXPECTED_SEED_SHA256, EXPECTED_SCHEMA_SHA256 = EXPECTED_HASHES["v0.5.1"]
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


def validate_seed_hashes(seed_path: Path, schema_path: Path) -> Dict[str, str]:
    """Require the imported seed and schema to match the supplied source bytes."""
    hashes = {"seed_sha256": file_sha256(seed_path), "schema_sha256": file_sha256(schema_path)}
    version = seed_path.parent.name
    if version not in EXPECTED_HASHES:
        raise ValueError(f"unsupported immutable seed version: {version}")
    expected_seed, expected_schema = EXPECTED_HASHES[version]
    if hashes["seed_sha256"] != expected_seed:
        raise ValueError(f"{version} seed bytes differ from the approved artifact")
    if hashes["schema_sha256"] != expected_schema:
        raise ValueError(f"{version} seed schema bytes differ from the approved artifact")
    return hashes


def load_and_validate_seed(seed_path: Path, schema_path: Path) -> ScenarioSeedSet:
    """Validate byte hashes, JSON Schema, ownership boundaries, and Pydantic types."""
    validate_seed_hashes(seed_path=seed_path, schema_path=schema_path)
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(f"{'.'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in errors)
        raise ValueError(f"seed JSON Schema validation failed: {details}")
    forbidden_paths = _collect_forbidden_keys(payload)
    if forbidden_paths:
        raise ValueError("seed contains code-owned study keys: " + ", ".join(forbidden_paths))
    seed = ScenarioSeedSet.model_validate(payload)
    if seed_path.parent.name == ACTIVE_SCENARIO_SEED_VERSION:
        if any(not isinstance(use_case, V09UseCaseSeed) for use_case in seed.use_cases):
            raise ValueError("active seed must use the V0.9.0 documented-option structure")
    return seed
