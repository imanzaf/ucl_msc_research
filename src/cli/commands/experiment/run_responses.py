"""Build or resume a selectable scenario-by-model 2×2 response-generation run."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import EVALUATED_RESPONSE_MAX_RETRIES, ProviderRouting, RunUnit, evaluated_response_retry_policy
from src.data_models.manifests import AcceptedScenarioManifest, EvaluatedModelSnapshot, ResponseGenerationConfig, ResponseScenarioScope
from src.data_models.scenarios import AcceptedScenario, ScenarioStage
from src.experiments.io import load_all_accepted_scenarios, prepare_experiment_dir, read_transcript_results
from src.experiments.model_catalog import ExperimentModelCatalog, ExperimentModelSpec, load_model_catalog
from src.experiments.response_assets import generate_response_paper_assets
from src.experiments.scenario_runner import (
    TextCompletionProvider,
    build_response_generation_run_plan,
    execute_run_plan,
    validate_response_generation_plan_against_inputs,
)
from src.llm.openrouter import OpenRouterClient, ProviderTextResponse
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_INPUT_ROOT, REPO_ROOT
from src.prompts.experiment import prompt_package_sha256
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic

DEFAULT_ACCEPTED_MANIFEST_PATH = ACTIVE_SCENARIO_INPUT_ROOT / "accepted_scenario_manifest.json"


class ModelRoutedProvider(TextCompletionProvider):
    """Dispatch each evaluated model to a client with its own frozen provider routing."""

    def __init__(self, clients_by_model: Dict[str, OpenRouterClient]) -> None:
        """Store exactly one OpenRouter client for each selected model id."""
        self.clients_by_model = clients_by_model

    def complete_text(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        seed: int,
    ) -> ProviderTextResponse:
        """Complete a request through the client configured for its model."""
        if model_id not in self.clients_by_model:
            raise ValueError(f"no evaluated-model client is configured for {model_id}")
        return self.clients_by_model[model_id].complete_text(model_id, messages, temperature, max_tokens, seed)


def _parse_args() -> argparse.Namespace:
    """Parse scenario scope, optional model ids, routing, and the explicit paid flag."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--scenario-scope", choices=[scope.value for scope in ResponseScenarioScope], type=str.lower, default="all")
    parser.add_argument(
        "--model-ids",
        nargs="+",
        help="Evaluated model ids to run. Omit this option to run all three catalogued evaluated models.",
    )
    parser.add_argument(
        "--provider-only",
        action="append",
        default=[],
        metavar="MODEL_ID=PROVIDER_ID[,PROVIDER_ID]",
        help="Optionally freeze an ordered OpenRouter provider allowlist for one selected model.",
    )
    parser.add_argument("--accepted-root", type=Path, default=ACTIVE_SCENARIO_ACCEPTED_ROOT)
    parser.add_argument("--accepted-scenario-manifest", type=Path, default=DEFAULT_ACCEPTED_MANIFEST_PATH)
    parser.add_argument("--randomisation-seed", type=int, default=7)
    parser.add_argument("--max-retries", type=int, default=EVALUATED_RESPONSE_MAX_RETRIES)
    parser.add_argument("--retry-backoff-seconds", nargs="+", type=float)
    parser.add_argument("--execute-paid", action="store_true")
    return parser.parse_args()


def _selected_model_specs(catalog: ExperimentModelCatalog, requested_model_ids: List[str] | None) -> List[ExperimentModelSpec]:
    """Resolve an ordered subset of configured evaluated models, defaulting to all three."""
    configured_by_id = {model.model_id: model for model in catalog.evaluated_models}
    model_ids = list(configured_by_id) if requested_model_ids is None else requested_model_ids
    if not model_ids or len(model_ids) != len(set(model_ids)):
        raise ValueError("model ids must contain one to three unique values")
    unknown = sorted(set(model_ids) - set(configured_by_id))
    if unknown:
        raise ValueError("unconfigured evaluated model ids: " + ", ".join(unknown))
    return [configured_by_id[model_id] for model_id in model_ids]


def _parse_provider_routing(values: List[str], selected_model_ids: set[str]) -> Dict[str, ProviderRouting]:
    """Parse repeatable MODEL=PROVIDER lists and reject routing for unselected models."""
    routing: Dict[str, ProviderRouting] = {}
    for value in values:
        model_id, separator, provider_text = value.partition("=")
        provider_ids = [provider_id.strip() for provider_id in provider_text.split(",") if provider_id.strip()]
        if not separator or not model_id.strip() or not provider_ids:
            raise ValueError("--provider-only must use MODEL_ID=PROVIDER_ID[,PROVIDER_ID]")
        if model_id not in selected_model_ids:
            raise ValueError(f"provider routing names unselected model {model_id}")
        if model_id in routing:
            raise ValueError(f"provider routing is repeated for model {model_id}")
        routing[model_id] = ProviderRouting(only=provider_ids, allow_fallbacks=False)
    return routing


def _snapshot(model: ExperimentModelSpec, frozen_at: datetime) -> EvaluatedModelSnapshot:
    """Freeze catalog metadata and the exact requested OpenRouter model identity."""
    return EvaluatedModelSnapshot(
        name=model.name,
        model_id=model.model_id,
        returned_model_version=model.model_id,
        family=model.family,
        provider=model.provider,
        weight_type=model.weight_type,
        metadata_sha256=artifact_sha256(model),
        frozen_at=frozen_at,
    )


def _select_scenarios(scenarios: List[AcceptedScenario], scope: ResponseScenarioScope) -> List[AcceptedScenario]:
    """Filter the authenticated complete manifest according to the requested C/R/all scope."""
    if scope == ResponseScenarioScope.C:
        return [scenario for scenario in scenarios if scenario.study_stage == ScenarioStage.CALIBRATION]
    if scope == ResponseScenarioScope.R:
        return [scenario for scenario in scenarios if scenario.study_stage == ScenarioStage.EVALUATION]
    return scenarios


def _create_config(
    experiment_dir: Path,
    experiment_name: str,
    scenario_scope: ResponseScenarioScope,
    accepted_manifest: AcceptedScenarioManifest,
    models: List[EvaluatedModelSnapshot],
    provider_routing_by_model: Dict[str, ProviderRouting],
    randomisation_seed: int,
    max_retries: int,
    retry_backoff_seconds: List[float] | None,
    created_at: datetime,
) -> ResponseGenerationConfig:
    """Persist the immutable configuration for one new response-generation run."""
    timestamp = created_at.strftime("%Y%m%dT%H%M%S")
    scenario_count = {ResponseScenarioScope.C: 10, ResponseScenarioScope.R: 20, ResponseScenarioScope.ALL: 30}[scenario_scope]
    conversation_count = scenario_count * len(models) * 4
    config = ResponseGenerationConfig(
        schema_version="1.0.0",
        experiment_name=experiment_name,
        scenario_scope=scenario_scope,
        accepted_scenario_manifest_sha256=accepted_manifest.manifest_sha256,
        evaluated_models=models,
        prompt_package_sha256=prompt_package_sha256(),
        provider_routing_by_model=provider_routing_by_model,
        scenario_count=scenario_count,
        evaluated_model_count=len(models),
        expected_conversation_count=conversation_count,
        expected_agent_response_count=conversation_count * 2,
        randomisation_seed=randomisation_seed,
        retry_policy=evaluated_response_retry_policy(max_retries=max_retries, backoff_seconds=retry_backoff_seconds),
        results_filename=f"{timestamp}_results.jsonl",
        log_filename=f"{timestamp}_run.log",
        created_at=created_at,
    )
    write_model_json_atomic(experiment_dir / "config.json", config)
    return config


def _validate_existing_config(
    config: ResponseGenerationConfig,
    accepted_manifest: AcceptedScenarioManifest,
    scenario_scope: ResponseScenarioScope,
    models: List[EvaluatedModelSnapshot],
    provider_routing_by_model: Dict[str, ProviderRouting],
) -> None:
    """Reject resume arguments that differ from the persisted response-generation contract."""
    if config.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("existing response config binds a different accepted-scenario manifest")
    if config.prompt_package_sha256 != prompt_package_sha256():
        raise ValueError("existing response config binds a different prompt package")
    if config.scenario_scope != scenario_scope:
        raise ValueError("existing response config binds a different scenario scope")
    if [model.model_id for model in config.evaluated_models] != [model.model_id for model in models]:
        raise ValueError("existing response config binds different evaluated models")
    if config.provider_routing_by_model != provider_routing_by_model:
        raise ValueError("existing response config binds different evaluated-model provider routing")


def _build_provider(config: ResponseGenerationConfig, experiment_dir: Path) -> ModelRoutedProvider:
    """Construct one no-hidden-retry client per selected model and routing policy."""
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    clients = {
        model.model_id: OpenRouterClient.from_settings(
            api_settings=api_settings,
            model_settings=model_settings,
            credential_role=OpenRouterCredentialRole.AGENT,
            cache_dir=experiment_dir / "cache/agent",
            provider_routing=config.provider_routing_by_model.get(model.model_id),
        )
        for model in config.evaluated_models
    }
    return ModelRoutedProvider(clients)


def main() -> None:
    """Build or resume the selected paid response matrix without running scoring."""
    args = _parse_args()
    if not args.execute_paid:
        raise PermissionError("response generation may call paid APIs and requires --execute-paid")

    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    all_scenarios = load_all_accepted_scenarios(args.accepted_root, accepted_manifest)
    scenario_scope = ResponseScenarioScope(args.scenario_scope)
    scenarios = _select_scenarios(all_scenarios, scenario_scope)
    catalog = load_model_catalog()
    selected_specs = _selected_model_specs(catalog, args.model_ids)
    selected_model_ids = {model.model_id for model in selected_specs}
    provider_routing = _parse_provider_routing(args.provider_only, selected_model_ids)
    experiment_dir = prepare_experiment_dir(REPO_ROOT / "data/outputs/experiments", args.experiment_name)
    config_path = experiment_dir / "config.json"
    if config_path.exists():
        config = read_model_json(config_path, ResponseGenerationConfig)
        selected_snapshots = [_snapshot(model, config.created_at) for model in selected_specs]
        _validate_existing_config(config, accepted_manifest, scenario_scope, selected_snapshots, provider_routing)
    else:
        created_at = datetime.now(timezone.utc)
        selected_snapshots = [_snapshot(model, created_at) for model in selected_specs]
        config = _create_config(
            experiment_dir=experiment_dir,
            experiment_name=args.experiment_name,
            scenario_scope=scenario_scope,
            accepted_manifest=accepted_manifest,
            models=selected_snapshots,
            provider_routing_by_model=provider_routing,
            randomisation_seed=args.randomisation_seed,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            created_at=created_at,
        )

    plan_path = experiment_dir / "checkpoints/run_plan.jsonl"
    if plan_path.exists():
        run_units = read_model_jsonl(plan_path, RunUnit)
        validate_response_generation_plan_against_inputs(run_units, scenarios, config)
    else:
        run_units = build_response_generation_run_plan(
            scenarios=scenarios,
            models=config.evaluated_models,
            scenario_scope=config.scenario_scope,
            randomisation_seed=config.randomisation_seed,
            created_at=config.created_at,
            provider_routing_by_model=config.provider_routing_by_model,
        )
        write_models_jsonl_atomic(plan_path, run_units)

    result_path = experiment_dir / "results" / config.results_filename
    log_path = experiment_dir / "logs" / config.log_filename
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    existing = read_transcript_results(result_path)
    new_transcripts = execute_run_plan(
        run_units=run_units,
        provider=_build_provider(config, experiment_dir),
        config=config,
        results_path=result_path,
        existing_transcripts=existing,
        paid_execution_approved=True,
    )
    transcripts = read_transcript_results(result_path)
    generate_response_paper_assets(transcripts, experiment_dir / "assets", config.experiment_name)
    logging.info("Persisted %s new terminal conversations; total=%s", len(new_transcripts), len(transcripts))
    print(
        f"Persisted {len(new_transcripts)} new conversations; " f"{len(transcripts)}/{config.expected_conversation_count} terminal at {result_path}"
    )


if __name__ == "__main__":
    main()
