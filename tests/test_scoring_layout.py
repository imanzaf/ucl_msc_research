"""Per-experiment scoring layout tests."""

from __future__ import annotations

from src.models.enums import ExperimentKind
from src.paths import experiment_paths, scoring_paths


def test_scoring_artifacts_are_owned_by_one_experiment() -> None:
    """Keep every scoring artifact beneath its evaluated experiment directory."""
    for experiment in ExperimentKind:
        experiment_root = experiment_paths(experiment.value)["root"]
        paths = scoring_paths(experiment.value)
        assert paths["root"] == experiment_root / "scoring"
        assert all(path == paths["root"] or paths["root"] in path.parents for path in paths.values())


def test_scoring_layout_separates_raw_and_final_judgments() -> None:
    """Expose immutable raw calls, manual corrections, final labels, and final scores explicitly."""
    paths = scoring_paths(ExperimentKind.USER_STATE.value)
    assert paths["raw_results"].name == "raw_judge_results.jsonl"
    assert paths["manual_overrides"].name == "manual_overrides.jsonl"
    assert paths["final_judgments"].name == "final_judgments.jsonl"
    assert paths["response_scores"].name == "response_scores.jsonl"
    assert len({paths["raw_results"], paths["final_judgments"], paths["response_scores"]}) == 3
