"""Validate immutable V0.8.0 sources, model catalog, schemas, and active protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.data_models.scenarios import EvidencePairType, UseCaseSeed
from src.experiments.model_catalog import load_model_catalog
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT, REPO_ROOT
from src.scenarios.rendering_templates import SOURCE_FORMAT_BY_USE_CASE, SOURCE_LAYOUT_BY_FORMAT, SourceFormat
from src.scenarios.seed_validation import load_and_validate_seed

SEED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT
LEGACY_SEED_ROOTS = [
    REPO_ROOT / "data" / "inputs" / "scenarios" / "v0.5.1",
    REPO_ROOT / "data" / "inputs" / "scenarios" / "v0.5.2",
    REPO_ROOT / "data" / "inputs" / "scenarios" / "v0.6.0",
    REPO_ROOT / "data" / "inputs" / "scenarios" / "v0.7.0",
]


def validate_exported_schemas(schema_root: Path) -> int:
    """Validate every exported JSON Schema against Draft 2020-12."""
    schema_paths = sorted(schema_root.glob("*.schema.json"))
    if not schema_paths:
        raise ValueError(f"no exported schemas found in {schema_root}")
    for path in schema_paths:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    return len(schema_paths)


def validate_removed_active_interfaces() -> None:
    """Require persona, simulator, and user-harm implementations to remain absent."""
    forbidden_paths = [
        REPO_ROOT / "src" / "data_models" / "user_personas.py",
        REPO_ROOT / "src" / "data_models" / "user_simulator.py",
        REPO_ROOT / "src" / "prompts" / "user_simulator",
    ]
    existing = [str(path.relative_to(REPO_ROOT)) for path in forbidden_paths if path.is_file() or (path.is_dir() and any(path.rglob("*.py")))]
    if existing:
        raise ValueError("removed V6 interfaces reappeared: " + ", ".join(existing))


def main() -> None:
    """Run all offline protocol validation gates without API access."""
    argparse.ArgumentParser().parse_args()
    seed = load_and_validate_seed(
        seed_path=SEED_ROOT / "scenario_generation_seeds.json",
        schema_path=SEED_ROOT / "scenario_generation_seed_schema.json",
    )
    legacy_seeds = [
        load_and_validate_seed(
            seed_path=legacy_root / "scenario_generation_seeds.json",
            schema_path=legacy_root / "scenario_generation_seed_schema.json",
        )
        for legacy_root in LEGACY_SEED_ROOTS
    ]
    expected_use_cases = {f"CF{index:03d}" for index in range(1, 11)}
    if (
        set(SOURCE_FORMAT_BY_USE_CASE) != expected_use_cases
        or set(SOURCE_FORMAT_BY_USE_CASE.values()) != set(SourceFormat)
        or set(SOURCE_LAYOUT_BY_FORMAT) != set(SourceFormat)
    ):
        raise ValueError("V0.8.0 requires one distinct deterministic source format for each use case")
    if any({item.use_case_id for item in seed.use_cases} != {item.use_case_id for item in legacy_seed.use_cases} for legacy_seed in legacy_seeds):
        raise ValueError("V0.8.0 must preserve the CF001-CF010 identifiers used by all archived seed families")
    active_use_cases = [use_case for use_case in seed.use_cases if isinstance(use_case, UseCaseSeed)]
    if len(active_use_cases) != 10:
        raise ValueError("V0.8.0 requires the balanced-evidence structure for every use case")
    if any({pair.pair_type for pair in use_case.hidden_design.evidence.pairs} != set(EvidencePairType) for use_case in active_use_cases):
        raise ValueError("V0.8.0 requires one benefit and one downside comparison per use case")
    catalog = load_model_catalog()
    schema_count = validate_exported_schemas(REPO_ROOT / "schemas")
    validate_removed_active_interfaces()
    print(
        f"Protocol valid: {len(seed.use_cases)} use cases, "
        f"{sum(len(use_case.hidden_design.generation.replications) for use_case in active_use_cases)} seeds, "
        f"{len(catalog.evaluated_models)} model candidates, {schema_count} exported schemas."
    )


if __name__ == "__main__":
    main()
