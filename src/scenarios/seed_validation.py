"""Validate immutable V0.5.1/V0.5.2 seed ownership, schema, and bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft202012Validator

from src.data_models.common import file_sha256
from src.data_models.scenarios import ScenarioSeedSet

EXPECTED_HASHES = {
    "v0.5.1": (
        "ecf3e81761cd5dc6543bb5dd21a153ff8dff9813a937da90f2aa144c672b1b72",
        "7f2eba17550ad915177d15351bebb767898c138e023e149c75f69a7bd249dcfe",
    ),
    "v0.5.2": (
        "ce21fd98368a0f0719a5fdad0a4e5793510be58f4f7367d8339bec6fdbb3d389",
        "480e40d7d05f38500ccc2bdfcd792c7ed1a8eb0583beba1c3ab15f4a5b28f130",
    ),
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
    return ScenarioSeedSet.model_validate(payload)
