"""Final-protocol paths that do not depend on historical active-version constants."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
SCENARIO_ROOT = DATA_ROOT / "inputs" / "scenarios" / "v4.0.1"
SCENARIO_SOURCE_ARCHIVE = DATA_ROOT / "inputs" / "scenarios" / "v4.0.0.zip"
EXPERIMENT_ROOT = DATA_ROOT / "outputs" / "experiments"
SCENARIO_GENERATION_ROOT = EXPERIMENT_ROOT / "scenario_fact_generation_v1"
SCHEMA_ROOT = PROJECT_ROOT / "schemas_v2"
MANUSCRIPT_ROOT = PROJECT_ROOT / "tex_src" / "v0.2.0"
DECISION_REGISTER = PROJECT_ROOT / "docs" / "research-plan" / "V4_REDESIGN_DECISIONS.md"

EXPERIMENT_NAMES = (
    "user_state_adaptation_v2",
    "information_budget_v1",
    "word_budget_external_validity_v1",
    "single_fact_priority_v1",
    "ownership_role_control_v1",
    "option_first_v1",
    "balanced_prominence_mitigation_v1",
)


def experiment_paths(name: str) -> Dict[str, Path]:
    """Return the complete directory layout for one final-protocol experiment."""
    if name not in EXPERIMENT_NAMES:
        raise ValueError(f"unknown final-protocol experiment: {name}")
    root = EXPERIMENT_ROOT / name
    return {
        "root": root,
        "config": root / "config.json",
        "results": root / "results",
        "cache": root / "cache",
        "logs": root / "logs",
        "assets": root / "assets",
        "checkpoints": root / "checkpoints",
    }


def scenario_generation_paths() -> Dict[str, Path]:
    """Return the auditable output layout for one-shot scenario generation."""
    root = SCENARIO_GENERATION_ROOT
    return {
        "root": root,
        "config": root / "config.json",
        "approval": root / "approval.json",
        "results": root / "results",
        "cache": root / "cache",
        "logs": root / "logs",
        "assets": root / "assets",
        "checkpoints": root / "checkpoints",
    }
