"""Validate immutable V0.5.1 sources, model catalog, schemas, and active-code exclusions."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.experiments.model_catalog import load_model_catalog
from src.scenarios.seed_validation import load_and_validate_seed

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = REPO_ROOT / "data" / "inputs" / "scenarios" / "v0.5.1"


def validate_exported_schemas(schema_root: Path) -> int:
    """Validate every exported V9 JSON Schema against Draft 2020-12."""
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
    seed = load_and_validate_seed(
        seed_path=SEED_ROOT / "scenario_generation_seeds.json",
        schema_path=SEED_ROOT / "scenario_generation_seed_schema.json",
    )
    catalog = load_model_catalog()
    schema_count = validate_exported_schemas(REPO_ROOT / "schemas" / "v9")
    validate_removed_active_interfaces()
    print(
        f"V9 protocol valid: {len(seed.use_cases)} use cases, "
        f"{sum(len(use_case.replications) for use_case in seed.use_cases)} seeds, "
        f"{len(catalog.evaluated_models)} model candidates, {schema_count} exported schemas."
    )


if __name__ == "__main__":
    main()
