"""Build and execute the resumable single-model C1 2×2 diagnostic."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import ProviderRouting, RetryPolicy, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    C1EvaluationConfig,
    EvaluatedModelSnapshot,
    FreezeStatus,
    ModelWeightType,
    ScoringExecutionManifest,
)
from src.data_models.scoring import ScoredConversationBundle
from src.experiments.c1_assets import generate_c1_paper_assets
from src.experiments.io import load_accepted_calibration_scenarios, prepare_experiment_dir, read_transcript_results
from src.experiments.scenario_runner import build_c1_single_model_run_plan, execute_run_plan, validate_c1_single_model_plan_against_inputs
from src.llm.openrouter import OpenRouterClient
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_INPUT_ROOT, REPO_ROOT
from src.prompts.experiment import prompt_package_sha256
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic

DEFAULT_EXPERIMENT_NAME = "c1_llama_2x2_v1"
DEFAULT_AGENT_MODEL_ID = "meta-llama/llama-3.3-70b-instruct"
DEFAULT_SCORING_MODEL_ID = "google/gemini-3.1-flash-lite"
MODEL_CATALOG_PATH = REPO_ROOT / "src/settings/models.json"
ACCEPTED_MANIFEST_PATH = ACTIVE_SCENARIO_INPUT_ROOT / "calibration_accepted_scenario_manifest.json"


def _catalog_entry(model_id: str) -> Dict[str, object]:
    """Return one uniquely configured evaluated or scoring model entry."""
    catalog = json.loads(MODEL_CATALOG_PATH.read_text(encoding="utf-8"))
    entries = [*catalog["evaluated_models"], *catalog["scoring_models"]]
    matches = [entry for entry in entries if entry["model_id"] == model_id]
    if len(matches) != 1:
        raise ValueError(f"model catalog must contain exactly one entry for {model_id}")
    return matches[0]


def _snapshot(model_id: str, returned_model_version: str, frozen_at: datetime) -> EvaluatedModelSnapshot:
    """Freeze catalog metadata and the provider identity expected at execution."""
    entry = _catalog_entry(model_id)
    return EvaluatedModelSnapshot(
        name=str(entry["name"]),
        model_id=model_id,
        returned_model_version=returned_model_version,
        family=str(entry["family"]),
        provider=str(entry["provider"]),
        weight_type=ModelWeightType(str(entry["weight_type"])),
        metadata_sha256=artifact_sha256(entry),
        frozen_at=frozen_at,
    )


def _scoring_manifest(judge: EvaluatedModelSnapshot, frozen_by: str, frozen_at: datetime) -> ScoringExecutionManifest:
    """Freeze the one-judge scoring package used by the C1 diagnostic."""
    retry_policy = RetryPolicy(max_retries=2, backoff_seconds=[1.0, 2.0], reuse_identical_prompt_bytes=True)
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "judge_model_ids": [judge.model_id],
        "judge_snapshots": [judge],
        "scoring_contract_sha256": scoring_contract_sha256(),
        "fact_order_seed": 7,
        "retry_policy": retry_policy,
        "frozen_at": frozen_at,
        "frozen_by": frozen_by,
    }
    return ScoringExecutionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})


def _create_experiment(
    experiment_dir: Path,
    experiment_name: str,
    accepted_manifest: AcceptedScenarioManifest,
    agent_model_id: str,
    returned_model_version: str,
    judge_model_id: str,
    returned_judge_version: str,
    frozen_by: str,
    retry_policy: RetryPolicy,
    provider_routing: ProviderRouting | None,
) -> C1EvaluationConfig:
    """Create config, scoring manifest, and immutable run plan before paid calls."""
    created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime("%Y%m%dT%H%M%S")
    agent = _snapshot(agent_model_id, returned_model_version, created_at)
    judge = _snapshot(judge_model_id, returned_judge_version, created_at)
    scoring_manifest = _scoring_manifest(judge, frozen_by, created_at)
    scoring_path = experiment_dir / "checkpoints/scoring_execution_manifest.json"
    write_model_json_atomic(scoring_path, scoring_manifest)
    config = C1EvaluationConfig(
        schema_version="2.0.0",
        experiment_name=experiment_name,
        accepted_scenario_manifest_sha256=accepted_manifest.manifest_sha256,
        evaluated_model=agent,
        prompt_package_sha256=prompt_package_sha256(),
        scoring_execution_manifest_sha256=scoring_manifest.manifest_sha256,
        provider_routing=provider_routing,
        randomisation_seed=7,
        retry_policy=retry_policy,
        results_filename=f"{timestamp}_results.jsonl",
        log_filename=f"{timestamp}_run.log",
        created_at=created_at,
    )
    write_model_json_atomic(experiment_dir / "config.json", config)
    return config


def main() -> None:
    """Build or resume the 40-conversation Llama C1 diagnostic."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-name", default=DEFAULT_EXPERIMENT_NAME)
    parser.add_argument("--accepted-root", type=Path, default=ACTIVE_SCENARIO_ACCEPTED_ROOT)
    parser.add_argument("--accepted-scenario-manifest", type=Path, default=ACCEPTED_MANIFEST_PATH)
    parser.add_argument("--agent-model-id", default=DEFAULT_AGENT_MODEL_ID)
    parser.add_argument("--returned-model-version", default=DEFAULT_AGENT_MODEL_ID)
    parser.add_argument("--scoring-model-id", default=DEFAULT_SCORING_MODEL_ID)
    parser.add_argument("--returned-scoring-model-version", default=DEFAULT_SCORING_MODEL_ID)
    parser.add_argument("--frozen-by", required=True)
    parser.add_argument("--retry-backoff-seconds", nargs=2, type=float, default=[1.0, 2.0])
    parser.add_argument("--agent-provider-only", nargs="+")
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("C1 model execution may call paid APIs and requires --execute-paid")
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted_manifest)
    provider_routing = ProviderRouting(only=args.agent_provider_only, allow_fallbacks=False) if args.agent_provider_only else None
    experiment_dir = prepare_experiment_dir(REPO_ROOT / "data/outputs/experiments", args.experiment_name)
    config_path = experiment_dir / "config.json"
    if config_path.exists():
        config = read_model_json(config_path, C1EvaluationConfig)
        if config.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
            raise ValueError("existing C1 config binds a different accepted-scenario manifest")
        if config.prompt_package_sha256 != prompt_package_sha256():
            raise ValueError("existing C1 config binds a different prompt package")
        if config.evaluated_model.model_id != args.agent_model_id:
            raise ValueError("existing C1 config binds a different evaluated model")
        if config.provider_routing != provider_routing:
            raise ValueError("existing C1 config binds different evaluated-model provider routing")
    else:
        config = _create_experiment(
            experiment_dir=experiment_dir,
            experiment_name=args.experiment_name,
            accepted_manifest=accepted_manifest,
            agent_model_id=args.agent_model_id,
            returned_model_version=args.returned_model_version,
            judge_model_id=args.scoring_model_id,
            returned_judge_version=args.returned_scoring_model_version,
            frozen_by=args.frozen_by,
            retry_policy=RetryPolicy(
                max_retries=2,
                backoff_seconds=args.retry_backoff_seconds,
                reuse_identical_prompt_bytes=True,
            ),
            provider_routing=provider_routing,
        )
    plan_path = experiment_dir / "checkpoints/run_plan.jsonl"
    if plan_path.exists():
        run_units = read_model_jsonl(plan_path, RunUnit)
        validate_c1_single_model_plan_against_inputs(run_units, scenarios, config)
    else:
        run_units = build_c1_single_model_run_plan(
            scenarios=scenarios,
            model=config.evaluated_model,
            randomisation_seed=config.randomisation_seed,
            created_at=config.created_at,
            provider_routing=config.provider_routing,
        )
        write_models_jsonl_atomic(plan_path, run_units)
    result_path = experiment_dir / "results" / config.results_filename
    log_path = experiment_dir / "logs" / config.log_filename
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(filename=log_path, level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    existing = read_transcript_results(result_path)
    provider = OpenRouterClient.from_settings(
        get_api_settings(),
        get_model_settings(),
        OpenRouterCredentialRole.AGENT,
        cache_dir=experiment_dir / "cache/agent",
        provider_routing=config.provider_routing,
    )
    new_transcripts = execute_run_plan(run_units, provider, config, result_path, existing, paid_execution_approved=True)
    transcripts = read_transcript_results(result_path)
    bundles = read_model_jsonl(experiment_dir / "results/scored_conversations.jsonl", ScoredConversationBundle)
    generate_c1_paper_assets(transcripts, bundles, experiment_dir / "assets", config.experiment_name)
    logging.info("Persisted %s new C1 terminal conversations; total=%s", len(new_transcripts), len(transcripts))
    print(f"Persisted {len(new_transcripts)} new C1 conversations; {len(transcripts)}/40 terminal at {result_path}")


if __name__ == "__main__":
    main()
