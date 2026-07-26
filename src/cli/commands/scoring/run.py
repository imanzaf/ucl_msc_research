"""Run resumable condition-blind scoring with frozen retries and atomic bundles."""

from __future__ import annotations

import argparse
import importlib
import time
from pathlib import Path
from typing import Dict, List, TypeVar, cast

from pydantic import BaseModel

from src.data_models.common import artifact_sha256, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, EvaluatedModelSnapshot, ExperimentManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import ManualScoringQueueRecord, ScoredConversationBundle, ScoringAttemptStatus, ScoringExecutionAttempt
from src.data_models.study import EXPERIMENT_DIMENSIONS, ExperimentName
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import validate_complete_run_plan, validate_exploratory_run_plan
from src.experiments.scoring_pipeline import ConditionBlindScoringBackend, build_condition_blind_input, score_condition_blind_input
from src.paths import REPO_ROOT
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_backend(specification: str, judge_snapshot: EvaluatedModelSnapshot) -> ConditionBlindScoringBackend:
    """Load a scoring backend factory from module:attribute syntax."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator:
        raise ValueError("backend must use module:attribute syntax")
    return cast(ConditionBlindScoringBackend, getattr(importlib.import_module(module_name), attribute_name)(judge_snapshot))


def _fact_order_seed(global_seed: int, run_unit_id: str) -> int:
    """Derive stable blinded fact order without depending on transcript file position."""
    return int(sha256_bytes(f"{global_seed}:{run_unit_id}".encode("utf-8"))[:16], 16)


def _attempt_id(run_unit_id: str, attempt_number: int) -> str:
    """Derive a stable scoring-attempt identifier."""
    digest = sha256_bytes(f"{run_unit_id}:{attempt_number}".encode("utf-8")).upper()[:16]
    return f"SCOREATTEMPT_{digest}"


def _append_unique(path: Path, model: ModelT, id_field: str) -> None:
    """Append one model while rejecting a duplicate semantic identifier under the storage lock."""

    def validate(existing: List[ModelT], new: ModelT) -> None:
        """Reject a duplicate record identifier."""
        if any(getattr(item, id_field) == getattr(new, id_field) for item in existing):
            raise ValueError(f"duplicate {id_field}: {getattr(new, id_field)}")

    append_model_jsonl_validated(path, model, validate)


def execute_scoring_transcripts(
    transcripts: List[ConversationTranscript],
    scenarios: Dict[str, AcceptedScenario],
    scoring_manifest: ScoringExecutionManifest,
    results_dir: Path,
    backend: ConditionBlindScoringBackend,
    prompt_factor_isolation_valid: bool,
) -> None:
    """Resume condition-blind scoring and atomically persist every terminal result."""
    transcript_ids = [transcript.run_unit.run_unit_id for transcript in transcripts]
    if len(transcript_ids) != len(set(transcript_ids)):
        raise ValueError("transcript results contain duplicate run-unit ids")
    if any(transcript.run_unit.scenario_id not in scenarios for transcript in transcripts):
        raise ValueError("a transcript refers to a scenario outside the authenticated scoring set")
    bundle_path = results_dir / "scored_conversations.jsonl"
    attempt_path = results_dir / "failed_attempts.jsonl"
    queue_path = results_dir / "manual_scoring_queue.jsonl"
    existing_bundles = read_model_jsonl(bundle_path, ScoredConversationBundle)
    existing_attempts = read_model_jsonl(attempt_path, ScoringExecutionAttempt)
    existing_queue = read_model_jsonl(queue_path, ManualScoringQueueRecord)
    transcript_by_id = {transcript.run_unit.run_unit_id: transcript for transcript in transcripts}
    for bundle in existing_bundles:
        transcript = transcript_by_id.get(bundle.run_unit_id)
        if transcript is None or bundle.transcript_sha256 != transcript.transcript_sha256:
            raise ValueError("existing scored bundle does not bind an active transcript")
        if bundle.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
            raise ValueError("existing scored bundle was created under a different scoring manifest")
        if bundle.scoring_contract_sha256 != scoring_manifest.scoring_contract_sha256:
            raise ValueError("existing scored bundle was created under different scoring contracts")
    for record in existing_queue:
        if record.run_unit_id not in transcript_by_id:
            raise ValueError("existing manual-scoring queue record has no active transcript")
        if record.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
            raise ValueError("existing manual-scoring queue record was created under a different scoring manifest")
    terminal_ids = {bundle.run_unit_id for bundle in existing_bundles} | {record.run_unit_id for record in existing_queue}
    if len(terminal_ids) != len(existing_bundles) + len(existing_queue):
        raise ValueError("a run unit cannot be both successfully scored and queued for manual scoring")
    failed_attempts_by_run: Dict[str, List[ScoringExecutionAttempt]] = {}
    for attempt in existing_attempts:
        failed_attempts_by_run.setdefault(attempt.run_unit_id, []).append(attempt)

    if len(scoring_manifest.judge_snapshots) != 1:
        raise ValueError("the current scoring backend requires exactly one independently frozen judge snapshot")
    maximum_attempts = scoring_manifest.retry_policy.max_retries + 1
    for transcript in transcripts:
        run_unit_id = transcript.run_unit.run_unit_id
        if transcript.outcome_status != RunOutcomeStatus.COMPLETED or run_unit_id in terminal_ids:
            continue
        fact_order_seed = _fact_order_seed(scoring_manifest.fact_order_seed, run_unit_id)
        scoring_input = build_condition_blind_input(transcript, scenarios[transcript.run_unit.scenario_id], fact_order_seed)
        request_digest = artifact_sha256(
            {
                "scoring_input": scoring_input,
                "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
                "judge_model_ids": scoring_manifest.judge_model_ids,
            }
        )
        attempts = sorted(failed_attempts_by_run.get(run_unit_id, []), key=lambda item: item.attempt_number)
        succeeded = False
        while len(attempts) < maximum_attempts:
            attempt_number = len(attempts) + 1
            started_at = utc_now()
            try:
                fact_result, response_result, claim_result, metrics = score_condition_blind_input(
                    scoring_input=scoring_input,
                    transcript=transcript,
                    scenario=scenarios[transcript.run_unit.scenario_id],
                    backend=backend,
                    prompt_factor_isolation_valid=prompt_factor_isolation_valid,
                )
                judge_ids = {fact_result.judge_model_id, response_result.judge_model_id, claim_result.judge_model_id}
                if not judge_ids.issubset(scoring_manifest.judge_model_ids):
                    raise ValueError("scoring result used a judge outside the frozen scoring manifest")
                provider_calls = [fact_result.provider_call, response_result.provider_call, claim_result.provider_call]
                snapshot = scoring_manifest.judge_snapshots[0]
                if any(call is None or call.returned_model_version != snapshot.returned_model_version for call in provider_calls):
                    raise ValueError("scoring result does not bind the frozen returned judge snapshot")
            except Exception as error:
                failed_attempt = ScoringExecutionAttempt(
                    schema_version="2.0.0",
                    attempt_id=_attempt_id(run_unit_id, attempt_number),
                    run_unit_id=run_unit_id,
                    blind_conversation_id=scoring_input.blind_conversation_id,
                    attempt_number=attempt_number,
                    request_sha256=request_digest,
                    status=ScoringAttemptStatus.FAILED,
                    error_type=type(error).__name__,
                    error_message=str(error) or type(error).__name__,
                    started_at=started_at,
                    completed_at=utc_now(),
                )
                _append_unique(attempt_path, failed_attempt, "attempt_id")
                attempts.append(failed_attempt)
                if len(attempts) < maximum_attempts:
                    delay = scoring_manifest.retry_policy.backoff_seconds[len(attempts) - 1]
                    if delay:
                        time.sleep(delay)
                continue
            scoring_output_sha256 = artifact_sha256(
                {"fact_result": fact_result, "response_result": response_result, "claim_result": claim_result, "metrics": metrics}
            )
            success_attempt = ScoringExecutionAttempt(
                schema_version="2.0.0",
                attempt_id=_attempt_id(run_unit_id, attempt_number),
                run_unit_id=run_unit_id,
                blind_conversation_id=scoring_input.blind_conversation_id,
                attempt_number=attempt_number,
                request_sha256=request_digest,
                status=ScoringAttemptStatus.SUCCEEDED,
                scoring_output_sha256=scoring_output_sha256,
                started_at=started_at,
                completed_at=utc_now(),
            )
            bundle_payload = {
                "schema_version": "2.0.0",
                "run_unit_id": run_unit_id,
                "transcript_sha256": transcript.transcript_sha256,
                "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
                "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
                "scoring_input": scoring_input,
                "fact_result": fact_result,
                "response_result": response_result,
                "claim_result": claim_result,
                "metrics": metrics,
                "attempts": [*attempts, success_attempt],
                "completed_at": utc_now(),
            }
            bundle = ScoredConversationBundle.model_validate({**bundle_payload, "bundle_sha256": artifact_sha256(bundle_payload)})
            _append_unique(bundle_path, bundle, "run_unit_id")
            succeeded = True
            break
        if succeeded:
            continue
        queue_payload = {
            "schema_version": "2.0.0",
            "run_unit_id": run_unit_id,
            "transcript_sha256": transcript.transcript_sha256,
            "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
            "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
            "scoring_input": scoring_input,
            "attempts": attempts,
            "queued_at": utc_now(),
            "reason": "Frozen scoring retry policy exhausted; blinded manual scoring is required.",
        }
        queue_record = ManualScoringQueueRecord.model_validate({**queue_payload, "record_sha256": artifact_sha256(queue_payload)})
        _append_unique(queue_path, queue_record, "run_unit_id")


def main() -> None:
    """Score completed transcripts without exposing treatment/model labels to the backend."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("automated scoring may call paid APIs and requires --execute-paid")
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    experiment_manifest = read_model_json(args.experiment_manifest, ExperimentManifest)
    experiment_name = experiment_manifest.experiment_name.value
    validate_experiment_path(args.transcripts, REPO_ROOT, "result", experiment_name)
    validate_experiment_path(args.results_dir, REPO_ROOT, "results_tree", experiment_name)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(experiment_manifest, "manifest_sha256")
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN or experiment_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("automated scoring requires frozen experiment and scoring-execution manifests")
    if experiment_manifest.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the accepted-scenario manifest")
    if experiment_manifest.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the scoring-execution manifest")
    if experiment_manifest.scoring_contract_sha256 != scoring_manifest.scoring_contract_sha256:
        raise ValueError("experiment and scoring-execution manifests bind different scoring contracts")
    if experiment_manifest.scoring_judge_model_ids != scoring_manifest.judge_model_ids:
        raise ValueError("experiment and scoring-execution manifests bind different judges")
    if scoring_manifest.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("scoring manifest does not bind the active condition-blind contracts")
    scenarios: Dict[str, AcceptedScenario] = {
        scenario.scenario_id: scenario for scenario in load_accepted_evaluation_scenarios(args.accepted_root, accepted_manifest)
    }
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    transcript_ids = [transcript.run_unit.run_unit_id for transcript in transcripts]
    if len(transcript_ids) != len(set(transcript_ids)):
        raise ValueError("transcript results contain duplicate run-unit ids")
    run_units = [transcript.run_unit for transcript in transcripts]
    if experiment_manifest.experiment_name == ExperimentName.RISK_COMM_V1:
        validate_complete_run_plan(run_units)
    else:
        dimensions = EXPERIMENT_DIMENSIONS[experiment_manifest.experiment_name]
        validate_exploratory_run_plan(run_units, dimensions.conversation_count, dimensions.cell_count)

    if len(scoring_manifest.judge_snapshots) != 1:
        raise ValueError("the current scoring backend requires exactly one independently frozen judge snapshot")
    backend = _load_backend(args.backend, scoring_manifest.judge_snapshots[0])
    execute_scoring_transcripts(
        transcripts=transcripts,
        scenarios=scenarios,
        scoring_manifest=scoring_manifest,
        results_dir=args.results_dir,
        backend=backend,
        prompt_factor_isolation_valid=True,
    )
    print(f"Scoring bundles and any manual queue records are under {args.results_dir}")


if __name__ == "__main__":
    main()
