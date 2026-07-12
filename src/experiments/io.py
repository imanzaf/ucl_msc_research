"""Filesystem helpers for experiment inputs, outputs, and config snapshots."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel

from src.data_models.experiments import ExperimentConfig, ExperimentUsageSummary
from src.data_models.scenarios import ScenarioFamily

ExperimentRecordT = TypeVar("ExperimentRecordT", bound=BaseModel)

EXPERIMENT_NAME_PATTERN = re.compile(r"^[a-z0-9_]+_v[0-9]+$")
SCENARIO_JSON_EXCLUDE_SUFFIX = "_review"


def create_timestamped_run_id() -> str:
    """Create a timestamp identifier for experiment result files."""
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def validate_experiment_name(experiment_name: str) -> None:
    """Reject experiment names that do not follow <descriptive_name>_v<N>."""
    if not EXPERIMENT_NAME_PATTERN.fullmatch(experiment_name):
        raise ValueError("experiment name must follow lowercase_snake_case_v<N>")


def prepare_experiment_dir(experiment_root: Path, experiment_name: str) -> Path:
    """Create the standard experiment directory layout and return its path."""
    validate_experiment_name(experiment_name)
    experiment_dir = experiment_root / experiment_name
    for dirname in ["results", "cache/llm_calls", "logs", "assets", "checkpoints"]:
        (experiment_dir / dirname).mkdir(parents=True, exist_ok=True)
    return experiment_dir


def write_experiment_config(experiment_dir: Path, config: ExperimentConfig) -> None:
    """Write the experiment config snapshot before a run starts."""
    (experiment_dir / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")


def append_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    """Append Pydantic records to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")


def summarize_record_usage(records: Iterable[Any]) -> ExperimentUsageSummary:
    """Aggregate usage summaries stored on experiment records."""
    summary = ExperimentUsageSummary()
    for record in records:
        summary.merge(record.usage_summary)
    return summary


def add_record_usage(summary: ExperimentUsageSummary, records: Iterable[Any]) -> None:
    """Add usage summaries from experiment records into an existing summary."""
    for record in records:
        summary.merge(record.usage_summary)


def read_jsonl_models(path: Path, model: Type[ExperimentRecordT]) -> List[ExperimentRecordT]:
    """Read a JSONL file into typed Pydantic records."""
    records: List[ExperimentRecordT] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(model.model_validate_json(line))
    return records


def read_jsonl_dicts(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL file into plain dictionaries."""
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def scenario_json_paths(scenario_run_dir: Path) -> List[Path]:
    """Return scenario-family JSON files from a reviewed scenario run directory."""
    return sorted(
        path
        for path in scenario_run_dir.glob("*.json")
        if not path.stem.endswith(SCENARIO_JSON_EXCLUDE_SUFFIX)
    )


def load_scenario_families(scenario_run_dir: Path) -> List[ScenarioFamily]:
    """Load reviewed scenario-family artifacts from a directory."""
    paths = scenario_json_paths(scenario_run_dir)
    if not paths:
        raise ValueError(f"no scenario JSON files found in {scenario_run_dir}")
    return [ScenarioFamily.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]


def result_paths(experiment_dir: Path, pattern: str) -> List[Path]:
    """Return sorted result file paths matching a glob pattern."""
    return sorted((experiment_dir / "results").glob(pattern))


def latest_result_path(experiment_dir: Path, pattern: str) -> Optional[Path]:
    """Return the latest matching result path if one exists."""
    paths = result_paths(experiment_dir=experiment_dir, pattern=pattern)
    if not paths:
        return None
    return paths[-1]


def safe_filter_values(values: Optional[Sequence[str]]) -> Optional[List[str]]:
    """Normalize optional CLI filters to a non-empty list or None."""
    if not values:
        return None
    normalized = [value for value in values if value]
    return normalized or None
