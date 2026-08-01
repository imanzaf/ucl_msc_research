"""Build or resume a selectable scenario-by-model 2×2 response-generation run."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from src.data_models.common import artifact_sha256, file_sha256, utc_now, validate_model_self_hash
from src.data_models.experiments import (
    EVALUATED_RESPONSE_MAX_RETRIES,
    ConversationTranscript,
    ProviderRouting,
    RunOutcomeStatus,
    RunUnit,
    evaluated_response_retry_policy,
)
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    EvaluatedModelSnapshot,
    ResponseGenerationConfig,
    ResponseGenerationFailedRerunManifest,
    ResponseGenerationRoutingAmendment,
    ResponseScenarioScope,
)
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
from src.storage import atomic_write_bytes, read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic

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
    parser.add_argument(
        "--route-unfinished-only",
        action="append",
        default=[],
        metavar="MODEL_ID=PROVIDER_ID[,PROVIDER_ID]",
        help="Amend an existing stopped run by routing only unfinished units for one model.",
    )
    parser.add_argument(
        "--routing-amendment-reason",
        help="Required provenance note when --route-unfinished-only creates a routing amendment.",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="Archive active failed transcripts and rerun only those records during this resume.",
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


def _create_routing_amendment(
    amendment_path: Path,
    source_plan_path: Path,
    source_plan_backup_path: Path,
    config_path: Path,
    results_path: Path,
    config: ResponseGenerationConfig,
    run_units: List[RunUnit],
    existing_run_unit_ids: set[str],
    requested_routing_by_model: Dict[str, ProviderRouting],
    reason: str | None,
) -> None:
    """Record and apply one provider route to only unfinished units of one model."""
    if amendment_path.exists():
        raise ValueError("this response run already has a routing amendment; resume without --route-unfinished-only")
    if len(requested_routing_by_model) != 1:
        raise ValueError("--route-unfinished-only currently requires exactly one model routing amendment")
    if not reason or not reason.strip():
        raise ValueError("--routing-amendment-reason is required with --route-unfinished-only")
    if not results_path.exists():
        raise ValueError("routing unfinished units requires an existing results file")

    model_id, provider_routing = next(iter(requested_routing_by_model.items()))
    affected_ids = [unit.run_unit_id for unit in run_units if unit.model_id == model_id and unit.run_unit_id not in existing_run_unit_ids]
    if not affected_ids:
        raise ValueError(f"no unfinished run units remain for {model_id}")
    affected_id_set = set(affected_ids)
    amended_units = [
        unit.model_copy(update={"provider_routing": provider_routing}) if unit.run_unit_id in affected_id_set else unit for unit in run_units
    ]

    source_plan_bytes = source_plan_path.read_bytes()
    source_plan_sha256 = file_sha256(source_plan_path)
    atomic_write_bytes(source_plan_backup_path, source_plan_bytes)
    write_models_jsonl_atomic(source_plan_path, amended_units)
    amendment_payload = {
        "schema_version": "1.0.0",
        "experiment_name": config.experiment_name,
        "source_config_sha256": file_sha256(config_path),
        "source_run_plan_sha256": source_plan_sha256,
        "amended_run_plan_sha256": file_sha256(source_plan_path),
        "source_results_sha256": file_sha256(results_path),
        "model_id": model_id,
        "provider_routing": provider_routing,
        "affected_run_unit_ids": affected_ids,
        "reason": reason.strip(),
        "amended_at": utc_now(),
    }
    amendment = ResponseGenerationRoutingAmendment(
        **amendment_payload,
        amendment_sha256=artifact_sha256(amendment_payload),
    )
    write_model_json_atomic(amendment_path, amendment)


def _load_routing_amendment(
    amendment_path: Path,
    source_plan_backup_path: Path,
    config_path: Path,
    authenticated_plan_path: Path,
    config: ResponseGenerationConfig,
) -> Dict[str, ProviderRouting]:
    """Authenticate an optional routing amendment and return its per-run-unit overrides."""
    if not amendment_path.exists():
        return {}
    amendment = read_model_json(amendment_path, ResponseGenerationRoutingAmendment)
    validate_model_self_hash(amendment, "amendment_sha256")
    if amendment.experiment_name != config.experiment_name:
        raise ValueError("routing amendment binds a different experiment")
    if amendment.source_config_sha256 != file_sha256(config_path):
        raise ValueError("routing amendment binds a different response config")
    if not source_plan_backup_path.exists() or amendment.source_run_plan_sha256 != file_sha256(source_plan_backup_path):
        raise ValueError("routing amendment source-plan backup is absent or unauthentic")
    if amendment.amended_run_plan_sha256 != file_sha256(authenticated_plan_path):
        raise ValueError("routing amendment does not authenticate its amended run plan")
    configured_model_ids = {model.model_id for model in config.evaluated_models}
    if amendment.model_id not in configured_model_ids:
        raise ValueError("routing amendment names a model absent from the response config")
    return {run_unit_id: amendment.provider_routing for run_unit_id in amendment.affected_run_unit_ids}


def _failed_rerun_paths(experiment_dir: Path, rerun_id: str) -> Dict[str, Path]:
    """Return conventional audit-artifact paths for one failed-record rerun."""
    checkpoint_dir = experiment_dir / "checkpoints/failed_reruns"
    result_dir = experiment_dir / "results/failed_reruns"
    return {
        "manifest": checkpoint_dir / f"{rerun_id}_manifest.json",
        "source_plan": checkpoint_dir / f"{rerun_id}_run_plan_before.jsonl",
        "source_results": result_dir / f"{rerun_id}_results_before.jsonl",
        "archived_failures": result_dir / f"{rerun_id}_failed_results.jsonl",
    }


def _read_failed_rerun_manifests(experiment_dir: Path) -> List[ResponseGenerationFailedRerunManifest]:
    """Read self-hashed failed-rerun manifests in chronological order."""
    manifest_dir = experiment_dir / "checkpoints/failed_reruns"
    manifests = [read_model_json(path, ResponseGenerationFailedRerunManifest) for path in sorted(manifest_dir.glob("*_manifest.json"))]
    for manifest in manifests:
        validate_model_self_hash(manifest, "manifest_sha256")
    if len({manifest.rerun_id for manifest in manifests}) != len(manifests):
        raise ValueError("failed-rerun manifests contain duplicate rerun ids")
    return manifests


def _load_effective_routing(
    experiment_dir: Path,
    config_path: Path,
    plan_path: Path,
    amendment_path: Path,
    source_plan_backup_path: Path,
    config: ResponseGenerationConfig,
) -> Dict[str, ProviderRouting]:
    """Authenticate the routing-amendment chain and return current per-unit routes."""
    failed_reruns = _read_failed_rerun_manifests(experiment_dir)
    first_plan_path = _failed_rerun_paths(experiment_dir, failed_reruns[0].rerun_id)["source_plan"] if failed_reruns else plan_path
    routing = _load_routing_amendment(
        amendment_path=amendment_path,
        source_plan_backup_path=source_plan_backup_path,
        config_path=config_path,
        authenticated_plan_path=first_plan_path,
        config=config,
    )
    expected_plan_sha256 = file_sha256(first_plan_path)
    for manifest in failed_reruns:
        paths = _failed_rerun_paths(experiment_dir, manifest.rerun_id)
        if manifest.experiment_name != config.experiment_name or manifest.source_config_sha256 != file_sha256(config_path):
            raise ValueError("failed-rerun manifest binds a different experiment config")
        if manifest.source_run_plan_sha256 != expected_plan_sha256:
            raise ValueError("failed-rerun plan history is not a continuous hash chain")
        if not paths["source_plan"].exists() or file_sha256(paths["source_plan"]) != manifest.source_run_plan_sha256:
            raise ValueError("failed-rerun source-plan snapshot is absent or unauthentic")
        if not paths["source_results"].exists() or file_sha256(paths["source_results"]) != manifest.source_results_sha256:
            raise ValueError("failed-rerun source-results snapshot is absent or unauthentic")
        if not paths["archived_failures"].exists() or file_sha256(paths["archived_failures"]) != manifest.archived_failures_sha256:
            raise ValueError("failed-rerun failure archive is absent or unauthentic")
        archived = read_transcript_results(paths["archived_failures"])
        if [transcript.run_unit.run_unit_id for transcript in archived] != manifest.failed_run_unit_ids:
            raise ValueError("failed-rerun archive identities differ from its manifest")
        if any(transcript.outcome_status != RunOutcomeStatus.FAILED for transcript in archived):
            raise ValueError("failed-rerun archive contains a non-failed transcript")
        routing.update(manifest.provider_routing_by_run_unit)
        expected_plan_sha256 = manifest.rerun_plan_sha256
    if expected_plan_sha256 != file_sha256(plan_path):
        raise ValueError("failed-rerun history does not authenticate the current run plan")
    return routing


def _inherited_routing_by_model(
    run_units: List[RunUnit],
    provider_routing_by_run_unit: Dict[str, ProviderRouting],
) -> Dict[str, ProviderRouting]:
    """Resolve a unique amended route that failed units may inherit per model."""
    routing_by_model: Dict[str, ProviderRouting] = {}
    for unit in run_units:
        route = provider_routing_by_run_unit.get(unit.run_unit_id)
        if route is None:
            continue
        existing = routing_by_model.get(unit.model_id)
        if existing is not None and existing != route:
            raise ValueError(f"run-unit routing amendments disagree within model {unit.model_id}")
        routing_by_model[unit.model_id] = route
    return routing_by_model


def _prepare_failed_rerun(
    experiment_dir: Path,
    config_path: Path,
    plan_path: Path,
    results_path: Path,
    config: ResponseGenerationConfig,
    run_units: List[RunUnit],
    existing: List[ConversationTranscript],
    provider_routing_by_run_unit: Dict[str, ProviderRouting],
) -> None:
    """Archive active failures, amend inherited routing, and make only those IDs pending."""
    failures = [transcript for transcript in existing if transcript.outcome_status == RunOutcomeStatus.FAILED]
    if not failures:
        raise ValueError("--rerun-failed found no active failed response records")
    planned_by_id = {unit.run_unit_id: unit for unit in run_units}
    for transcript in existing:
        if planned_by_id.get(transcript.run_unit.run_unit_id) != transcript.run_unit:
            raise ValueError("active response transcript differs from the authenticated run plan")

    failed_ids = [transcript.run_unit.run_unit_id for transcript in failures]
    failed_id_set = set(failed_ids)
    inherited_by_model = _inherited_routing_by_model(run_units, provider_routing_by_run_unit)
    rerun_routing: Dict[str, ProviderRouting] = {}
    amended_units: List[RunUnit] = []
    for unit in run_units:
        inherited = inherited_by_model.get(unit.model_id) if unit.run_unit_id in failed_id_set else None
        if inherited is not None and unit.provider_routing != inherited:
            rerun_routing[unit.run_unit_id] = inherited
            amended_units.append(unit.model_copy(update={"provider_routing": inherited}))
        else:
            amended_units.append(unit)

    rerun_at = utc_now()
    rerun_id = rerun_at.strftime("%Y%m%dT%H%M%S%fZ")
    paths = _failed_rerun_paths(experiment_dir, rerun_id)
    source_plan_sha256 = file_sha256(plan_path)
    source_results_sha256 = file_sha256(results_path)
    atomic_write_bytes(paths["source_plan"], plan_path.read_bytes())
    atomic_write_bytes(paths["source_results"], results_path.read_bytes())
    write_models_jsonl_atomic(paths["archived_failures"], failures)
    write_models_jsonl_atomic(plan_path, amended_units)
    write_models_jsonl_atomic(
        results_path,
        [transcript for transcript in existing if transcript.run_unit.run_unit_id not in failed_id_set],
    )
    manifest_payload = {
        "schema_version": "1.0.0",
        "rerun_id": rerun_id,
        "experiment_name": config.experiment_name,
        "source_config_sha256": file_sha256(config_path),
        "source_run_plan_sha256": source_plan_sha256,
        "rerun_plan_sha256": file_sha256(plan_path),
        "source_results_sha256": source_results_sha256,
        "archived_failures_sha256": file_sha256(paths["archived_failures"]),
        "failed_run_unit_ids": failed_ids,
        "provider_routing_by_run_unit": rerun_routing,
        "rerun_at": rerun_at,
    }
    manifest = ResponseGenerationFailedRerunManifest(
        **manifest_payload,
        manifest_sha256=artifact_sha256(manifest_payload),
    )
    write_model_json_atomic(paths["manifest"], manifest)


def _build_provider(
    config: ResponseGenerationConfig,
    experiment_dir: Path,
    run_units: List[RunUnit],
    existing_run_unit_ids: set[str],
) -> ModelRoutedProvider:
    """Construct one no-hidden-retry client for each model's effective unfinished-unit route."""
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    clients: Dict[str, OpenRouterClient] = {}
    for model in config.evaluated_models:
        pending_routing = [
            unit.provider_routing for unit in run_units if unit.model_id == model.model_id and unit.run_unit_id not in existing_run_unit_ids
        ]
        distinct_routing = {routing.model_dump_json() if routing is not None else None for routing in pending_routing}
        if len(distinct_routing) > 1:
            raise ValueError(f"unfinished units for {model.model_id} require more than one provider route")
        provider_routing = pending_routing[0] if pending_routing else config.provider_routing_by_model.get(model.model_id)
        clients[model.model_id] = OpenRouterClient.from_settings(
            api_settings=api_settings,
            model_settings=model_settings,
            credential_role=OpenRouterCredentialRole.AGENT,
            cache_dir=experiment_dir / "cache/agent",
            provider_routing=provider_routing,
        )
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
    requested_unfinished_routing = _parse_provider_routing(args.route_unfinished_only, selected_model_ids)
    if args.routing_amendment_reason and not requested_unfinished_routing:
        raise ValueError("--routing-amendment-reason requires --route-unfinished-only")
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
    else:
        if requested_unfinished_routing:
            raise ValueError("--route-unfinished-only requires an existing stopped run plan")
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
    existing = read_transcript_results(result_path)
    existing_run_unit_ids = {transcript.run_unit.run_unit_id for transcript in existing}
    amendment_path = experiment_dir / "checkpoints/response_routing_amendment.json"
    source_plan_backup_path = experiment_dir / "checkpoints/run_plan_before_routing_amendment.jsonl"
    if requested_unfinished_routing:
        _create_routing_amendment(
            amendment_path=amendment_path,
            source_plan_path=plan_path,
            source_plan_backup_path=source_plan_backup_path,
            config_path=config_path,
            results_path=result_path,
            config=config,
            run_units=run_units,
            existing_run_unit_ids=existing_run_unit_ids,
            requested_routing_by_model=requested_unfinished_routing,
            reason=args.routing_amendment_reason,
        )
        run_units = read_model_jsonl(plan_path, RunUnit)
    routing_by_run_unit = _load_effective_routing(
        experiment_dir=experiment_dir,
        config_path=config_path,
        plan_path=plan_path,
        amendment_path=amendment_path,
        source_plan_backup_path=source_plan_backup_path,
        config=config,
    )
    validate_response_generation_plan_against_inputs(run_units, scenarios, config, routing_by_run_unit)
    if args.rerun_failed:
        _prepare_failed_rerun(
            experiment_dir=experiment_dir,
            config_path=config_path,
            plan_path=plan_path,
            results_path=result_path,
            config=config,
            run_units=run_units,
            existing=existing,
            provider_routing_by_run_unit=routing_by_run_unit,
        )
        run_units = read_model_jsonl(plan_path, RunUnit)
        existing = read_transcript_results(result_path)
        existing_run_unit_ids = {transcript.run_unit.run_unit_id for transcript in existing}
        routing_by_run_unit = _load_effective_routing(
            experiment_dir=experiment_dir,
            config_path=config_path,
            plan_path=plan_path,
            amendment_path=amendment_path,
            source_plan_backup_path=source_plan_backup_path,
            config=config,
        )
        validate_response_generation_plan_against_inputs(run_units, scenarios, config, routing_by_run_unit)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    new_transcripts = execute_run_plan(
        run_units=run_units,
        provider=_build_provider(config, experiment_dir, run_units, existing_run_unit_ids),
        config=config,
        results_path=result_path,
        existing_transcripts=existing,
        paid_execution_approved=True,
        provider_routing_by_run_unit=routing_by_run_unit,
    )
    transcripts = read_transcript_results(result_path)
    generate_response_paper_assets(transcripts, experiment_dir / "assets", config.experiment_name)
    logging.info("Persisted %s new terminal conversations; total=%s", len(new_transcripts), len(transcripts))
    print(
        f"Persisted {len(new_transcripts)} new conversations; " f"{len(transcripts)}/{config.expected_conversation_count} terminal at {result_path}"
    )


if __name__ == "__main__":
    main()
