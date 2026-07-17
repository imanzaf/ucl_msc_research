"""Filesystem helpers for experiment inputs, outputs, and config snapshots."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel

from src.data_models.experiments import ExperimentConfig, ExperimentUsageSummary
from src.data_models.scenario_review import (
    HumanFindingResolutionStatus,
    HumanReviewStatus,
    ScenarioGenerationManifest,
    ScenarioHumanReview,
    ScenarioSemanticReview,
    artifact_sha256,
    validate_generation_manifest_alignment,
    validate_semantic_review_coverage,
)
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


def validate_human_acceptance(scenario_run_dir: Path, family: ScenarioFamily) -> None:
    """Require an accepted human manifest covering every automated finding."""
    human_review_path = scenario_run_dir / "human_reviews" / f"{family.scenario_family_id}.json"
    semantic_review_path = (
        scenario_run_dir / "semantic_reviews" / f"{family.scenario_family_id}.json"
    )
    generation_manifest_path = scenario_run_dir / "manifests" / f"{family.scenario_family_id}.json"
    if (
        not human_review_path.exists()
        or not semantic_review_path.exists()
        or not generation_manifest_path.exists()
    ):
        raise ValueError(f"family {family.scenario_family_id} lacks required review manifests")

    human_review = ScenarioHumanReview.model_validate_json(
        human_review_path.read_text(encoding="utf-8")
    )
    semantic_review = ScenarioSemanticReview.model_validate_json(
        semantic_review_path.read_text(encoding="utf-8")
    )
    generation_manifest = ScenarioGenerationManifest.model_validate_json(
        generation_manifest_path.read_text(encoding="utf-8")
    )
    if human_review.scenario_family_id != family.scenario_family_id:
        raise ValueError("human-review family id does not match the scenario family")
    if semantic_review.scenario_family_id != family.scenario_family_id:
        raise ValueError("semantic-review family id does not match the scenario family")
    validate_semantic_review_coverage(review=semantic_review, family=family)
    validate_generation_manifest_alignment(
        manifest=generation_manifest,
        review=semantic_review,
        family=family,
    )
    expected_hashes = {
        "final_family_sha256": artifact_sha256(family),
        "semantic_review_sha256": artifact_sha256(semantic_review),
        "generation_manifest_sha256": artifact_sha256(generation_manifest),
    }
    for field_name, expected_hash in expected_hashes.items():
        if getattr(human_review, field_name) != expected_hash:
            raise ValueError(f"human review hash does not match {field_name}")
    if human_review.status != HumanReviewStatus.ACCEPTED:
        raise ValueError(
            f"family {family.scenario_family_id} is not human-accepted: {human_review.status.value}"
        )

    automated_finding_ids = {
        assessment.finding_id for assessment in semantic_review.assessments if assessment.finding_id
    }
    human_resolutions = {
        resolution.finding_id: resolution.status for resolution in human_review.finding_resolutions
    }
    if set(human_resolutions) != automated_finding_ids:
        raise ValueError("human review must cover exactly every automated semantic finding")
    if any(
        status != HumanFindingResolutionStatus.RESOLVED for status in human_resolutions.values()
    ):
        raise ValueError("accepted families require every automated finding to be resolved")


def scenario_family_matches_filters(
    family: ScenarioFamily,
    scenario_family_ids: Optional[Sequence[str]],
    scenario_ids: Optional[Sequence[str]],
) -> bool:
    """Return whether a family contains any scenario selected by the supplied filters."""
    if scenario_family_ids is not None and family.scenario_family_id not in scenario_family_ids:
        return False
    if scenario_ids is None:
        return True
    family_scenario_ids = {instance.scenario_id for instance in family.scenario_instances}
    return bool(family_scenario_ids.intersection(scenario_ids))


def load_scenario_families(
    scenario_run_dir: Path,
    scenario_family_ids: Optional[Sequence[str]] = None,
    scenario_ids: Optional[Sequence[str]] = None,
) -> List[ScenarioFamily]:
    """Load selected scenario families and enforce their human-acceptance gates."""
    paths = scenario_json_paths(scenario_run_dir)
    if not paths:
        raise ValueError(f"no scenario JSON files found in {scenario_run_dir}")
    families: List[ScenarioFamily] = []
    for path in paths:
        family = ScenarioFamily.model_validate_json(path.read_text(encoding="utf-8"))
        if scenario_family_matches_filters(
            family=family,
            scenario_family_ids=scenario_family_ids,
            scenario_ids=scenario_ids,
        ):
            validate_human_acceptance(scenario_run_dir=scenario_run_dir, family=family)
            families.append(family)
    if not families:
        raise ValueError("no scenario families matched the selected filters")
    return families


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
