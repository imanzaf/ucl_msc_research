"""Run scenario execution and post-run scoring as one end-to-end pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configs.api_settings import OpenRouterCredentialRole, get_api_settings  # noqa: E402
from configs.model_settings import get_model_settings  # noqa: E402
from src.data_models.experiments import ExperimentConfig, GenerationConfig  # noqa: E402
from src.experiments.assets import generate_paper_assets  # noqa: E402
from src.experiments.io import create_timestamped_run_id, prepare_experiment_dir  # noqa: E402
from src.experiments.model_catalog import (  # noqa: E402
    load_model_catalog,
    resolve_agent_model_ids,
    validate_model_ids_against_openrouter,
)
from src.experiments.scenario_runner import run_scenarios  # noqa: E402
from src.experiments.scoring_pipeline import score_scenario_runs  # noqa: E402
from src.llm.openrouter import OpenRouterStructuredClient  # noqa: E402

DEFAULT_EXPERIMENT_ROOT = Path("data/outputs/experiments")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for the joint pipeline."""
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
        help="OpenRouter agent model slug; repeat to run more than one.",
    )
    parser.add_argument(
        "--scenario-family-id",
        action="append",
        default=None,
        help="Optional family id filter; repeatable.",
    )
    parser.add_argument(
        "--scenario-id",
        action="append",
        default=None,
        help="Optional scenario id filter; repeatable.",
    )
    parser.add_argument(
        "--prompt-condition",
        action="append",
        default=None,
        help="Optional prompt condition filter; repeatable.",
    )
    parser.add_argument(
        "--persona-id",
        action="append",
        default=None,
        help="Optional persona id filter; repeatable.",
    )
    parser.add_argument("--run-id", default=None, help="Optional timestamp id for output files.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Optional maximum number of run units."
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Disable local LLM-call cache reads and writes."
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Refresh cached calls by making API requests again.",
    )
    parser.add_argument(
        "--resume", action="store_true", help="Skip run units already present in prior outputs."
    )
    parser.add_argument(
        "--family-scenario-concurrency",
        type=int,
        default=1,
        help=(
            "Maximum scenario instances to run concurrently within each family; "
            "families still run sequentially."
        ),
    )
    parser.add_argument(
        "--scoring-concurrency",
        type=int,
        default=1,
        help="Maximum completed scenario-run records to score concurrently.",
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
    model_catalog = load_model_catalog()
    agent_models = resolve_agent_model_ids(model_catalog, args.agent_model)
    return ExperimentConfig(
        experiment_name=args.experiment_name,
        scenario_run_dir=str(Path(args.scenario_run_dir).resolve()),
        agent_model_ids=agent_models,
        user_simulator_model=model_catalog.user_model.model_id,
        scoring_model=model_catalog.scoring_model.model_id,
        generation_config=GenerationConfig(
            temperature=model_settings.openrouter_temperature,
            seed=model_settings.openrouter_seed,
        ),
        cache_enabled=not args.no_cache,
        refresh_cache=args.refresh_cache,
        resume=args.resume,
        family_scenario_concurrency=args.family_scenario_concurrency,
        scoring_concurrency=args.scoring_concurrency,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run scenario execution, scoring, and asset generation."""
    args = parse_args(argv)
    run_id = args.run_id or create_timestamped_run_id()
    experiment_config = build_experiment_config(args)
    experiment_dir = prepare_experiment_dir(
        experiment_root=Path(args.experiment_root),
        experiment_name=experiment_config.experiment_name,
    )
    logger.add(experiment_dir / "logs" / f"{run_id}_run.log")
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    if not args.skip_model_validation:
        validate_model_ids_against_openrouter(
            model_ids=experiment_config.agent_model_ids,
            api_settings=api_settings,
            credential_role=OpenRouterCredentialRole.AGENT,
            timeout_seconds=model_settings.openrouter_request_timeout_seconds,
        )
        validate_model_ids_against_openrouter(
            model_ids=[experiment_config.user_simulator_model],
            api_settings=api_settings,
            credential_role=OpenRouterCredentialRole.USER_SIMULATOR,
            timeout_seconds=model_settings.openrouter_request_timeout_seconds,
        )
        validate_model_ids_against_openrouter(
            model_ids=[experiment_config.scoring_model],
            api_settings=api_settings,
            credential_role=OpenRouterCredentialRole.SCORING,
            timeout_seconds=model_settings.openrouter_request_timeout_seconds,
        )
    agent_client = OpenRouterStructuredClient.from_settings(
        api_settings=api_settings,
        model_settings=model_settings,
        credential_role=OpenRouterCredentialRole.AGENT,
        cache_dir=experiment_dir / "cache" / "llm_calls",
        cache_enabled=experiment_config.cache_enabled,
        refresh_cache=experiment_config.refresh_cache,
    )
    user_simulator_client = OpenRouterStructuredClient.from_settings(
        api_settings=api_settings,
        model_settings=model_settings,
        credential_role=OpenRouterCredentialRole.USER_SIMULATOR,
        cache_dir=experiment_dir / "cache" / "llm_calls",
        cache_enabled=experiment_config.cache_enabled,
        refresh_cache=experiment_config.refresh_cache,
    )
    scoring_client = OpenRouterStructuredClient.from_settings(
        api_settings=api_settings,
        model_settings=model_settings,
        credential_role=OpenRouterCredentialRole.SCORING,
        cache_dir=experiment_dir / "cache" / "llm_calls",
        cache_enabled=experiment_config.cache_enabled,
        refresh_cache=experiment_config.refresh_cache,
    )
    run_scenarios(
        agent_client=agent_client,
        user_simulator_client=user_simulator_client,
        experiment_root=Path(args.experiment_root),
        experiment_config=experiment_config,
        scenario_family_ids=args.scenario_family_id,
        scenario_ids=args.scenario_id,
        prompt_conditions=args.prompt_condition,
        persona_ids=args.persona_id,
        run_id=run_id,
        limit=args.limit,
    )
    score_scenario_runs(
        client=scoring_client,
        experiment_root=Path(args.experiment_root),
        experiment_config=experiment_config,
        scoring_run_id=run_id,
        limit=args.limit,
    )
    if not args.skip_assets:
        table_path = generate_paper_assets(experiment_dir)
        logger.success("Wrote paper asset {}", table_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
