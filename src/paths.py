"""Canonical paths for the dissertation experiments and analysis artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
SCENARIO_ROOT = DATA_ROOT / "inputs" / "scenarios" / "v4.0.1"
SCENARIO_SOURCE_ARCHIVE = DATA_ROOT / "inputs" / "scenarios" / "v4.0.0.zip"
EXPERIMENT_ROOT = DATA_ROOT / "outputs" / "experiments"
SCENARIO_GENERATION_ROOT = DATA_ROOT / "outputs" / "scenario_generation" / "v4.0.1" / "scenario_fact_generation_v1"
SCHEMA_ROOT = PROJECT_ROOT / "schemas"

EXPERIMENT_NAMES = (
    "user_state_adaptation_v2",
    "information_budget_v1",
    "word_budget_external_validity_v1",
    "single_fact_priority_v1",
    "ownership_role_control_v1",
    "option_first_v1",
    "commercial_interest_instruction_v1",
)


def experiment_paths(name: str) -> Dict[str, Path]:
    """Return the complete directory layout for one dissertation experiment."""
    if name not in EXPERIMENT_NAMES:
        raise ValueError(f"unknown dissertation experiment: {name}")
    root = EXPERIMENT_ROOT / name
    return {
        "root": root,
        "config": root / "config.json",
        "results": root / "results",
        "scoring": root / "scoring",
        "cache": root / "cache",
        "logs": root / "logs",
        "assets": root / "assets",
        "checkpoints": root / "checkpoints",
    }


def scoring_paths(name: str) -> Dict[str, Path]:
    """Return the self-contained scoring layout for one dissertation experiment."""
    root = experiment_paths(name)["scoring"]
    return {
        "root": root,
        "judge_prompts": root / "judge_prompts.json",
        "pilot_sample": root / "pilot_sample.json",
        "pilot_plan": root / "pilot_plan.jsonl",
        "pilot_cost_estimate": root / "pilot_cost_estimate.json",
        "pilot_approval": root / "pilot_approval.json",
        "pilot_raw_results": root / "pilot_raw_judge_results.jsonl",
        "pilot_manual_overrides": root / "pilot_manual_overrides.jsonl",
        "pilot_final_judgments": root / "pilot_final_judgments.jsonl",
        "frozen_contract": root / "frozen_judge_contract.json",
        "judge_plan": root / "judge_plan.jsonl",
        "cost_estimate": root / "cost_estimate.json",
        "approval": root / "approval.json",
        "raw_results": root / "raw_judge_results.jsonl",
        "manual_overrides": root / "manual_overrides.jsonl",
        "final_judgments": root / "final_judgments.jsonl",
        "selections": root / "selections.jsonl",
        "response_scores": root / "response_scores.jsonl",
        "outcome_observations": root / "outcome_observations.jsonl",
        "paired_contrasts": root / "paired_contrasts.json",
        "forced_choice_labels": root / "forced_choice_labels_v1.jsonl",
        "forced_choice_summary": root / "forced_choice_label_summary_v1.json",
        "manifest": root / "manifest.json",
        "summary": root / "summary.json",
        "cache": root / "cache",
        "logs": root / "logs",
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
