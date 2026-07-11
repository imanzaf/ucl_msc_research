"""Smoke tests for end-to-end pipeline CLI argument parsing."""

from __future__ import annotations

from scripts.run_experiment_pipeline import parse_args as parse_pipeline_args
from scripts.run_scenarios import parse_args as parse_run_args
from scripts.score_runs import parse_args as parse_score_args


def test_run_scenarios_cli_parses_filters_and_cache_flags() -> None:
    """Verify the scenario-run CLI accepts the core public interface."""
    args = parse_run_args(
        [
            "--experiment-name",
            "deception_probe_v1",
            "--scenario-run-dir",
            "data/inputs/scenarios/v0.1.0/runs/20260705T204014",
            "--agent-model",
            "openai/gpt-5.5",
            "--prompt-condition",
            "neutral",
            "--persona-id",
            "neutral_baseline",
            "--no-cache",
        ]
    )

    assert args.experiment_name == "deception_probe_v1"
    assert args.agent_model == ["openai/gpt-5.5"]
    assert args.prompt_condition == ["neutral"]
    assert args.no_cache is True


def test_score_runs_cli_parses_resume_and_assets_flags() -> None:
    """Verify the scoring CLI accepts resume and asset controls."""
    args = parse_score_args(
        [
            "--experiment-name",
            "deception_probe_v1",
            "--scenario-run-dir",
            "data/inputs/scenarios/v0.1.0/runs/20260705T204014",
            "--resume",
            "--skip-assets",
        ]
    )

    assert args.resume is True
    assert args.skip_assets is True


def test_joint_pipeline_cli_parses_shared_options() -> None:
    """Verify the joint pipeline CLI exposes run and scoring controls together."""
    args = parse_pipeline_args(
        [
            "--experiment-name",
            "deception_probe_v1",
            "--scenario-run-dir",
            "data/inputs/scenarios/v0.1.0/runs/20260705T204014",
            "--limit",
            "1",
            "--refresh-cache",
        ]
    )

    assert args.limit == 1
    assert args.refresh_cache is True
