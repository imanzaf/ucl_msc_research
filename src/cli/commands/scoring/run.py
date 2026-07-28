"""Run resumable six-call condition-blind scoring with per-call retries."""

from __future__ import annotations

import argparse
import importlib
import time
from pathlib import Path
from typing import Dict, List, Tuple, TypeVar, Union, cast

from pydantic import BaseModel

from src.data_models.common import artifact_sha256, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, EvaluatedModelSnapshot, ExperimentManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    EvaluationCheckpoint,
    ManualScoringQueueRecord,
    PresentationAssessmentResult,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringAttemptStatus,
    ScoringCallArtifact,
    ScoringContract,
    ScoringExecutionAttempt,
)
from src.data_models.study import EXPERIMENT_DIMENSIONS, ExperimentName
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import validate_complete_run_plan, validate_exploratory_run_plan
from src.experiments.scoring_pipeline import ConditionBlindScoringBackend, build_condition_blind_inputs
from src.paths import REPO_ROOT
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_accuracy_result, validate_content_result, validate_presentation_result
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl

ModelT = TypeVar("ModelT", bound=BaseModel)
ContractResult = Union[ContentAssessmentResult, PresentationAssessmentResult, AccuracyAssessmentResult]
CallKey = Tuple[str, ScoredResponse, ScoringContract]


def _load_backend(specification: str, judge_snapshot: EvaluatedModelSnapshot) -> ConditionBlindScoringBackend:
    """Load a scoring backend factory from module:attribute syntax."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator:
        raise ValueError("backend must use module:attribute syntax")
    return cast(ConditionBlindScoringBackend, getattr(importlib.import_module(module_name), attribute_name)(judge_snapshot))


def _fact_order_seed(global_seed: int, run_unit_id: str) -> int:
    """Derive stable blinded fact order without depending on transcript file position."""
    return int(sha256_bytes(f"{global_seed}:{run_unit_id}".encode("utf-8"))[:16], 16)


def _attempt_id(
    run_unit_id: str,
    scored_response: ScoredResponse,
    contract: ScoringContract,
    attempt_number: int,
) -> str:
    """Derive a stable identifier for one independently retryable call."""
    digest = sha256_bytes(f"{run_unit_id}:{scored_response.value}:{contract.value}:{attempt_number}".encode("utf-8")).upper()[:16]
    return f"SCOREATTEMPT_{digest}"


def _append_unique(path: Path, model: ModelT, id_field: str) -> None:
    """Append one model while rejecting a duplicate identifier under the storage lock."""

    def validate(existing: List[ModelT], new: ModelT) -> None:
        """Reject a duplicate record identifier."""
        if any(getattr(item, id_field) == getattr(new, id_field) for item in existing):
            raise ValueError(f"duplicate {id_field}: {getattr(new, id_field)}")

    append_model_jsonl_validated(path, model, validate)


def _call_key(
    run_unit_id: str,
    scored_response: ScoredResponse,
    contract: ScoringContract,
) -> CallKey:
    """Return the cache and retry identity for one scoring call."""
    return run_unit_id, scored_response, contract


def _result_from_artifact(artifact: ScoringCallArtifact) -> ContractResult:
    """Return the sole typed result stored in a successful call artifact."""
    result_by_contract: Dict[ScoringContract, ContractResult | None] = {
        ScoringContract.CONTENT: artifact.content_result,
        ScoringContract.PRESENTATION: artifact.presentation_result,
        ScoringContract.ACCURACY: artifact.accuracy_result,
    }
    result = result_by_contract[artifact.contract]
    if result is None:
        raise ValueError("successful call artifact has no matching result")
    return result


def _execute_contract(
    backend: ConditionBlindScoringBackend,
    contract: ScoringContract,
    scoring_input: ConditionBlindScoringInput,
) -> ContractResult:
    """Execute exactly one scoring contract for one isolated response."""
    if contract == ScoringContract.CONTENT:
        return backend.assess_content(scoring_input)
    if contract == ScoringContract.PRESENTATION:
        return backend.assess_presentation(scoring_input)
    return backend.assess_accuracy(scoring_input)


def _validate_contract_result(
    contract: ScoringContract,
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    result: ContractResult,
    content_result: ContentAssessmentResult | None,
) -> None:
    """Validate one call result using only its contract's required dependencies."""
    if contract == ScoringContract.CONTENT:
        if not isinstance(result, ContentAssessmentResult):
            raise TypeError("content contract returned the wrong result type")
        validate_content_result(scoring_input, transcript, result)
        return
    if contract == ScoringContract.PRESENTATION:
        if not isinstance(result, PresentationAssessmentResult):
            raise TypeError("presentation contract returned the wrong result type")
        if content_result is None:
            raise ValueError("presentation validation requires the cached content result for the same response")
        validate_presentation_result(scoring_input, transcript, result, content_result)
        return
    if not isinstance(result, AccuracyAssessmentResult):
        raise TypeError("accuracy contract returned the wrong result type")
    validate_accuracy_result(scoring_input, transcript, result)


def _validate_provider(
    result: ContractResult,
    scoring_manifest: ScoringExecutionManifest,
) -> None:
    """Require one successful result to bind the independently frozen judge."""
    if result.judge_model_id not in scoring_manifest.judge_model_ids:
        raise ValueError("scoring result used a judge outside the frozen scoring manifest")
    snapshot = scoring_manifest.judge_snapshots[0]
    if result.provider_call is None or result.provider_call.returned_model_version != snapshot.returned_model_version:
        raise ValueError("automated scoring result does not bind the frozen returned judge snapshot")


def _build_call_artifact(
    run_unit_id: str,
    scoring_input: ConditionBlindScoringInput,
    contract: ScoringContract,
    scoring_manifest: ScoringExecutionManifest,
    result: ContractResult,
    attempts: List[ScoringExecutionAttempt],
) -> ScoringCallArtifact:
    """Build a self-authenticating successful-call cache record."""
    result_fields: Dict[str, ContractResult | None] = {
        "content_result": result if contract == ScoringContract.CONTENT else None,
        "presentation_result": result if contract == ScoringContract.PRESENTATION else None,
        "accuracy_result": result if contract == ScoringContract.ACCURACY else None,
    }
    payload = {
        "schema_version": "3.0.0",
        "run_unit_id": run_unit_id,
        "blind_conversation_id": scoring_input.blind_conversation_id,
        "scored_response": scoring_input.scored_response,
        "contract": contract,
        "scoring_input_sha256": artifact_sha256(scoring_input),
        "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
        **result_fields,
        "attempts": attempts,
        "completed_at": utc_now(),
    }
    return ScoringCallArtifact.model_validate({**payload, "artifact_sha256": artifact_sha256(payload)})


def _request_digest(
    scoring_input: ConditionBlindScoringInput,
    contract: ScoringContract,
    scoring_manifest: ScoringExecutionManifest,
) -> str:
    """Hash one independently retryable provider request boundary."""
    return artifact_sha256(
        {
            "scoring_input": scoring_input,
            "contract": contract,
            "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
            "judge_model_ids": scoring_manifest.judge_model_ids,
        }
    )


def _run_or_resume_call(
    run_unit_id: str,
    scoring_input: ConditionBlindScoringInput,
    contract: ScoringContract,
    transcript: ConversationTranscript,
    content_result: ContentAssessmentResult | None,
    scoring_manifest: ScoringExecutionManifest,
    backend: ConditionBlindScoringBackend,
    cached_artifact: ScoringCallArtifact | None,
    existing_failures: List[ScoringExecutionAttempt],
    call_path: Path,
    failure_path: Path,
) -> ScoringCallArtifact | None:
    """Reuse one successful call or retry only that failed response-contract pair."""
    input_sha256 = artifact_sha256(scoring_input)
    if cached_artifact is not None:
        if (
            cached_artifact.scoring_input_sha256 != input_sha256
            or cached_artifact.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256
        ):
            raise ValueError("cached scoring call was created from different inputs or manifest")
        _validate_contract_result(
            contract,
            scoring_input,
            transcript,
            _result_from_artifact(cached_artifact),
            content_result,
        )
        return cached_artifact

    request_sha256 = _request_digest(scoring_input, contract, scoring_manifest)
    failures = sorted(existing_failures, key=lambda item: item.attempt_number)
    if any(attempt.request_sha256 != request_sha256 for attempt in failures):
        raise ValueError("failed scoring attempts do not bind the active request")
    maximum_attempts = scoring_manifest.retry_policy.max_retries + 1
    attempts = list(failures)
    while len(attempts) < maximum_attempts:
        attempt_number = len(attempts) + 1
        started_at = utc_now()
        try:
            result = _execute_contract(backend, contract, scoring_input)
            _validate_contract_result(contract, scoring_input, transcript, result, content_result)
            _validate_provider(result, scoring_manifest)
        except Exception as error:
            failed_attempt = ScoringExecutionAttempt(
                schema_version="3.0.0",
                attempt_id=_attempt_id(run_unit_id, scoring_input.scored_response, contract, attempt_number),
                run_unit_id=run_unit_id,
                blind_conversation_id=scoring_input.blind_conversation_id,
                scored_response=scoring_input.scored_response,
                contract=contract,
                attempt_number=attempt_number,
                request_sha256=request_sha256,
                status=ScoringAttemptStatus.FAILED,
                error_type=type(error).__name__,
                error_message=str(error) or type(error).__name__,
                started_at=started_at,
                completed_at=utc_now(),
            )
            _append_unique(failure_path, failed_attempt, "attempt_id")
            attempts.append(failed_attempt)
            if len(attempts) < maximum_attempts:
                delay = scoring_manifest.retry_policy.backoff_seconds[len(attempts) - 1]
                if delay:
                    time.sleep(delay)
            continue

        success_attempt = ScoringExecutionAttempt(
            schema_version="3.0.0",
            attempt_id=_attempt_id(run_unit_id, scoring_input.scored_response, contract, attempt_number),
            run_unit_id=run_unit_id,
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            contract=contract,
            attempt_number=attempt_number,
            request_sha256=request_sha256,
            status=ScoringAttemptStatus.SUCCEEDED,
            scoring_output_sha256=artifact_sha256(result),
            started_at=started_at,
            completed_at=utc_now(),
        )
        artifact = _build_call_artifact(
            run_unit_id,
            scoring_input,
            contract,
            scoring_manifest,
            result,
            [*attempts, success_attempt],
        )
        _append_unique(call_path, artifact, "artifact_sha256")
        return artifact
    return None


def execute_scoring_transcripts(
    transcripts: List[ConversationTranscript],
    scenarios: Dict[str, AcceptedScenario],
    scoring_manifest: ScoringExecutionManifest,
    results_dir: Path,
    backend: ConditionBlindScoringBackend,
) -> None:
    """Resume six-call scoring and persist a bundle or manual queue record per conversation."""
    transcript_ids = [transcript.run_unit.run_unit_id for transcript in transcripts]
    if len(transcript_ids) != len(set(transcript_ids)):
        raise ValueError("transcript results contain duplicate run-unit ids")
    if any(transcript.run_unit.scenario_id not in scenarios for transcript in transcripts):
        raise ValueError("a transcript refers to a scenario outside the authenticated scoring set")
    if len(scoring_manifest.judge_snapshots) != 1:
        raise ValueError("the current scoring backend requires exactly one independently frozen judge snapshot")

    bundle_path = results_dir / "scored_conversations.jsonl"
    call_path = results_dir / "scoring_calls.jsonl"
    failure_path = results_dir / "failed_scoring_calls.jsonl"
    queue_path = results_dir / "manual_scoring_queue.jsonl"
    existing_bundles = read_model_jsonl(bundle_path, ScoredConversationBundle)
    existing_calls = read_model_jsonl(call_path, ScoringCallArtifact)
    existing_failures = read_model_jsonl(failure_path, ScoringExecutionAttempt)
    existing_queue = read_model_jsonl(queue_path, ManualScoringQueueRecord)
    transcript_by_id = {transcript.run_unit.run_unit_id: transcript for transcript in transcripts}

    for bundle in existing_bundles:
        transcript = transcript_by_id.get(bundle.run_unit_id)
        if transcript is None or bundle.transcript_sha256 != transcript.transcript_sha256:
            raise ValueError("existing scored bundle does not bind an active transcript")
        if bundle.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
            raise ValueError("existing scored bundle was created under a different scoring manifest")
    for record in existing_queue:
        if record.run_unit_id not in transcript_by_id:
            raise ValueError("existing manual-scoring queue record has no active transcript")
        if record.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
            raise ValueError("existing manual-scoring queue record was created under a different scoring manifest")

    cached_by_key: Dict[CallKey, ScoringCallArtifact] = {}
    for artifact in existing_calls:
        key = _call_key(artifact.run_unit_id, artifact.scored_response, artifact.contract)
        if key in cached_by_key:
            raise ValueError("successful scoring-call cache contains a duplicate response-contract pair")
        cached_by_key[key] = artifact
    failures_by_key: Dict[CallKey, List[ScoringExecutionAttempt]] = {}
    for attempt in existing_failures:
        failures_by_key.setdefault(
            _call_key(attempt.run_unit_id, attempt.scored_response, attempt.contract),
            [],
        ).append(attempt)

    terminal_ids = {bundle.run_unit_id for bundle in existing_bundles} | {record.run_unit_id for record in existing_queue}
    if len(terminal_ids) != len(existing_bundles) + len(existing_queue):
        raise ValueError("a run unit cannot be both successfully scored and queued for manual scoring")

    for transcript in transcripts:
        run_unit_id = transcript.run_unit.run_unit_id
        if transcript.outcome_status != RunOutcomeStatus.COMPLETED or run_unit_id in terminal_ids:
            continue
        scenario = scenarios[transcript.run_unit.scenario_id]
        scoring_inputs = build_condition_blind_inputs(
            transcript,
            scenario,
            _fact_order_seed(scoring_manifest.fact_order_seed, run_unit_id),
        )
        completed: Dict[Tuple[ScoredResponse, ScoringContract], ScoringCallArtifact] = {}
        exhausted = False
        for contract in ScoringContract:
            for response in ScoredResponse:
                key = _call_key(run_unit_id, response, contract)
                content_result = None
                if contract == ScoringContract.PRESENTATION:
                    content_artifact = completed[(response, ScoringContract.CONTENT)]
                    content_value = _result_from_artifact(content_artifact)
                    if not isinstance(content_value, ContentAssessmentResult):
                        raise TypeError("cached content call contains the wrong result type")
                    content_result = content_value
                artifact = _run_or_resume_call(
                    run_unit_id=run_unit_id,
                    scoring_input=scoring_inputs[response],
                    contract=contract,
                    transcript=transcript,
                    content_result=content_result,
                    scoring_manifest=scoring_manifest,
                    backend=backend,
                    cached_artifact=cached_by_key.get(key),
                    existing_failures=failures_by_key.get(key, []),
                    call_path=call_path,
                    failure_path=failure_path,
                )
                if artifact is None:
                    exhausted = True
                    break
                completed[(response, contract)] = artifact
                cached_by_key[key] = artifact
            if exhausted:
                break

        attempts_by_id = {attempt.attempt_id: attempt for artifact in completed.values() for attempt in artifact.attempts}
        if exhausted:
            for attempt in read_model_jsonl(
                failure_path,
                ScoringExecutionAttempt,
            ):
                if attempt.run_unit_id == run_unit_id:
                    attempts_by_id[attempt.attempt_id] = attempt
        attempts = sorted(
            attempts_by_id.values(),
            key=lambda item: (
                item.scored_response.value,
                item.contract.value,
                item.attempt_number,
            ),
        )
        if exhausted:
            queue_payload = {
                "schema_version": "3.0.0",
                "run_unit_id": run_unit_id,
                "transcript_sha256": transcript.transcript_sha256,
                "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
                "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
                "scoring_inputs": scoring_inputs,
                "completed_calls": list(completed.values()),
                "attempts": attempts,
                "queued_at": utc_now(),
                "reason": "One response-contract call exhausted its frozen retry policy; blinded manual resolution is required.",
            }
            record = ManualScoringQueueRecord.model_validate({**queue_payload, "record_sha256": artifact_sha256(queue_payload)})
            _append_unique(queue_path, record, "run_unit_id")
            continue

        content_results = {
            response: cast(ContentAssessmentResult, _result_from_artifact(completed[(response, ScoringContract.CONTENT)]))
            for response in ScoredResponse
        }
        presentation_results = {
            response: cast(PresentationAssessmentResult, _result_from_artifact(completed[(response, ScoringContract.PRESENTATION)]))
            for response in ScoredResponse
        }
        accuracy_results = {
            response: cast(AccuracyAssessmentResult, _result_from_artifact(completed[(response, ScoringContract.ACCURACY)]))
            for response in ScoredResponse
        }
        metrics = [
            compute_conversation_metrics(
                transcript,
                scenario,
                content_results,
                presentation_results,
                accuracy_results,
                checkpoint,
            )
            for checkpoint in EvaluationCheckpoint
        ]
        bundle_payload = {
            "schema_version": "3.0.0",
            "run_unit_id": run_unit_id,
            "transcript_sha256": transcript.transcript_sha256,
            "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
            "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
            "scoring_inputs": scoring_inputs,
            "content_results": content_results,
            "presentation_results": presentation_results,
            "accuracy_results": accuracy_results,
            "metrics": metrics,
            "attempts": attempts,
            "completed_at": utc_now(),
        }
        bundle = ScoredConversationBundle.model_validate({**bundle_payload, "bundle_sha256": artifact_sha256(bundle_payload)})
        _append_unique(bundle_path, bundle, "run_unit_id")


def main() -> None:
    """Score completed transcripts without exposing treatment or model labels to the backend."""
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
        raise ValueError("scoring manifest does not bind the active six-call contracts")
    scenarios = {scenario.scenario_id: scenario for scenario in load_accepted_evaluation_scenarios(args.accepted_root, accepted_manifest)}
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    run_units = [transcript.run_unit for transcript in transcripts]
    if experiment_manifest.experiment_name == ExperimentName.RISK_COMM_V1:
        validate_complete_run_plan(run_units)
    else:
        dimensions = EXPERIMENT_DIMENSIONS[experiment_manifest.experiment_name]
        validate_exploratory_run_plan(run_units, dimensions.conversation_count, dimensions.cell_count)
    backend = _load_backend(args.backend, scoring_manifest.judge_snapshots[0])
    execute_scoring_transcripts(
        transcripts=transcripts,
        scenarios=scenarios,
        scoring_manifest=scoring_manifest,
        results_dir=args.results_dir,
        backend=backend,
    )
    print(f"Six-call scoring bundles and any manual queue records are under {args.results_dir}")


if __name__ == "__main__":
    main()
