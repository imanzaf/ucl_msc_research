"""Score completed scenario-run records with the post-run scoring pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configs.api_settings import get_api_settings  # noqa: E402
from configs.model_settings import get_model_settings  # noqa: E402
from src.data_models.experiments import ExperimentConfig, GenerationConfig  # noqa: E402
from src.experiments.assets import generate_paper_assets  # noqa: E402
from src.experiments.io import create_timestamped_run_id, prepare_experiment_dir  # noqa: E402
from src.experiments.model_catalog import (  # noqa: E402
    default_agent_model_ids,
    validate_model_ids_against_openrouter,
)
from src.experiments.scoring_pipeline import score_scenario_runs  # noqa: E402
from src.llm.openrouter import OpenRouterStructuredClient  # noqa: E402

DEFAULT_EXPERIMENT_ROOT = Path("experiments")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for scoring scenario runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment-name", required=True, help="Experiment name, e.g. deception_probe_v1."
    )
    parser.add_argument(
        "--scenario-run-dir",
        required=True,
        help="Directory containing reviewed scenario JSON files.",
    )
    parser.add_argument(
        "--experiment-root",
        default=str(DEFAULT_EXPERIMENT_ROOT),
        help="Root output directory for experiments.",
    )
    parser.add_argument(
        "--agent-model",
        action="append",
        default=None,
        help="OpenRouter agent model slug used in config snapshot.",
    )
    parser.add_argument(
        "--run-unit-id",
        action="append",
        default=None,
        help="Optional run-unit id filter; repeatable.",
    )
    parser.add_argument(
        "--scoring-run-id", default=None, help="Optional timestamp id for scoring output files."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional maximum number of run units to score."
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Disable local LLM-call cache reads and writes."
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Refresh cached scoring calls by making API requests again.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip run units already present in prior scoring outputs.",
    )
    parser.add_argument(
        "--skip-assets",
        action="store_true",
        help="Do not regenerate the stable LaTeX summary table.",
    )
    parser.add_argument(
        "--skip-model-validation", action="store_true", help="Skip OpenRouter /models validation."
    )
    return parser.parse_args(argv)


def build_experiment_config(args: argparse.Namespace) -> ExperimentConfig:
    """Build a typed experiment config from CLI arguments and settings."""
    model_settings = get_model_settings()
    agent_models = args.agent_model or default_agent_model_ids()
    return ExperimentConfig(
        experiment_name=args.experiment_name,
        scenario_run_dir=str(Path(args.scenario_run_dir).resolve()),
        agent_model_ids=agent_models,
        user_simulator_model=model_settings.user_simulator_model,
        scoring_model=model_settings.scoring_model,
        generation_config=GenerationConfig(
            temperature=model_settings.openrouter_temperature,
            seed=model_settings.openrouter_seed,
        ),
        max_followup_turns=model_settings.max_followup_turns,
        cache_enabled=not args.no_cache,
        refresh_cache=args.refresh_cache,
        resume=args.resume,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the scoring CLI."""
    args = parse_args(argv)
    scoring_run_id = args.scoring_run_id or create_timestamped_run_id()
    experiment_config = build_experiment_config(args)
    experiment_dir = prepare_experiment_dir(
        experiment_root=Path(args.experiment_root),
        experiment_name=experiment_config.experiment_name,
    )
    logger.add(experiment_dir / "logs" / f"{scoring_run_id}_scoring_run.log")
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    if not args.skip_model_validation:
        validate_model_ids_against_openrouter(
            model_ids=[experiment_config.scoring_model],
            api_settings=api_settings,
            timeout_seconds=model_settings.openrouter_request_timeout_seconds,
        )
    client = OpenRouterStructuredClient.from_settings(
        api_settings=api_settings,
        model_settings=model_settings,
        cache_dir=experiment_dir / "cache" / "llm_calls",
        cache_enabled=experiment_config.cache_enabled,
        refresh_cache=experiment_config.refresh_cache,
    )
    score_scenario_runs(
        client=client,
        experiment_root=Path(args.experiment_root),
        experiment_config=experiment_config,
        run_unit_ids=args.run_unit_id,
        scoring_run_id=scoring_run_id,
        limit=args.limit,
    )
    if not args.skip_assets:
        table_path = generate_paper_assets(experiment_dir)
        logger.success("Wrote paper asset {}", table_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
