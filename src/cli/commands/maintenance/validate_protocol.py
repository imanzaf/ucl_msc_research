"""Validate immutable V3.0.0 inputs, model catalog, schemas, and active protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.experiments.model_catalog import load_model_catalog
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT, REPO_ROOT
from src.scenarios.seed_validation import load_and_validate_seed

SEED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT


def validate_exported_schemas(schema_root: Path) -> int:
    """Validate every exported JSON Schema against Draft 2020-12."""
    schema_paths = sorted(schema_root.glob("*.schema.json"))
    if not schema_paths:
        raise ValueError(f"no exported schemas found in {schema_root}")
    for path in schema_paths:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    return len(schema_paths)


def validate_removed_active_interfaces() -> None:
    """Require superseded scenario and user-simulation interfaces to remain absent."""
    forbidden_paths = [
        REPO_ROOT / "src" / "data_models" / "user_personas.py",
        REPO_ROOT / "src" / "data_models" / "user_simulator.py",
        REPO_ROOT / "src" / "prompts" / "user_simulator",
        REPO_ROOT / "src" / "scenarios" / "numeric_engine.py",
        REPO_ROOT / "src" / "scenarios" / "rendering_templates.py",
        REPO_ROOT / "src" / "scenarios" / "source_rendering.py",
        REPO_ROOT / "src" / "prompts" / "scenario_generation 2.py",
        REPO_ROOT / "tests" / "test_generation_pipeline 2.py",
        REPO_ROOT / "src" / "analysis" / "composite.py",
        REPO_ROOT / "src" / "analysis" / "equivalence.py",
        REPO_ROOT / "schemas" / "claim_assessment.schema.json",
        REPO_ROOT / "schemas" / "fact_assessment.schema.json",
        REPO_ROOT / "schemas" / "response_communication.schema.json",
        REPO_ROOT / "schemas" / "domain_validation_gate_manifest.schema.json",
    ]
    existing = [str(path.relative_to(REPO_ROOT)) for path in forbidden_paths if path.is_file() or (path.is_dir() and any(path.rglob("*.py")))]
    if existing:
        raise ValueError("removed legacy interfaces reappeared: " + ", ".join(existing))


def main() -> None:
    """Run all offline protocol validation gates without API access."""
    argparse.ArgumentParser().parse_args()
    seed = load_and_validate_seed(
        seed_path=SEED_ROOT / "scenario_generation_seeds.json",
        schema_path=SEED_ROOT / "scenario_generation_seed_schema.json",
        query_path=SEED_ROOT / "scenario_customer_queries.json",
        query_schema_path=SEED_ROOT / "scenario_customer_queries_schema.json",
    )
    expected_use_cases = {f"CF{index:03d}" for index in range(1, 11)}
    active_use_case_ids = {item.use_case_id for item in seed.use_cases}
    if active_use_case_ids != expected_use_cases:
        raise ValueError("V3.0.0 must contain the exact CF001-CF010 use-case identifiers")
    catalog = load_model_catalog()
    schema_count = validate_exported_schemas(REPO_ROOT / "schemas")
    validate_removed_active_interfaces()
    print(
        f"Protocol valid: {len(seed.use_cases)} use cases, "
        f"{sum(len(use_case.replications) for use_case in seed.use_cases)} seeds, "
        f"{len(catalog.evaluated_models)} model candidates, {schema_count} exported schemas."
    )


if __name__ == "__main__":
    main()
