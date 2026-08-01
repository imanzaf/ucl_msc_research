"""Run resumable content-gated condition-blind scoring with per-call retries."""

from __future__ import annotations

import argparse
import importlib
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TypeVar, Union, cast

from pydantic import BaseModel

from src.data_models.common import artifact_sha256, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RetryPolicy, RunOutcomeStatus, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    EvaluatedModelSnapshot,
    FreezeStatus,
    ResponseGenerationConfig,
    ResponseScenarioScope,
    ScoringExecutionManifest,
)
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    BlindFactReference,
    ConditionBlindScoringInput,
    EvaluationCheckpoint,
    FactContentAssessmentResult,
    FactPresentationAssessmentResult,
    ManualScoringQueueRecord,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringAttemptStatus,
    ScoringCallArtifact,
    ScoringContract,
    ScoringExecutionAttempt,
)
from src.experiments.io import load_all_accepted_scenarios
from src.experiments.model_catalog import ExperimentModelSpec, load_model_catalog
from src.experiments.scoring_pipeline import (
    ConditionBlindScoringBackend,
    aggregate_content_fact_results,
    aggregate_presentation_fact_results,
    build_condition_blind_inputs,
)
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_accuracy_result, validate_content_fact_result, validate_presentation_fact_result
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl, write_model_json_atomic

ModelT = TypeVar("ModelT", bound=BaseModel)
ContractResult = Union[FactContentAssessmentResult, FactPresentationAssessmentResult, AccuracyAssessmentResult]
CallKey = Tuple[str, ScoredResponse, ScoringContract, Optional[str]]
DEFAULT_ACCEPTED_MANIFEST_PATH = ACTIVE_SCENARIO_INPUT_ROOT / "accepted_scenario_manifest.json"
DEFAULT_SCORING_BACKEND = "src.experiments.openrouter_scoring:create_openrouter_scoring_backend"


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
    fact_id: str | None,
    attempt_number: int,
) -> str:
    """Derive a stable identifier for one independently retryable call."""
    digest = sha256_bytes(f"{run_unit_id}:{scored_response.value}:{contract.value}:{fact_id or 'response'}:{attempt_number}".encode("utf-8")).upper()[
        :16
    ]
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
    fact_id: str | None,
) -> CallKey:
    """Return the cache and retry identity for one scoring call."""
    return run_unit_id, scored_response, contract, fact_id


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
    fact: BlindFactReference | None,
) -> ContractResult:
    """Execute one fact-level or response-level scoring call."""
    if contract == ScoringContract.CONTENT:
        if fact is None:
            raise ValueError("content scoring requires one fact")
        return backend.assess_content_fact(scoring_input, fact)
    if contract == ScoringContract.PRESENTATION:
        if fact is None:
            raise ValueError("presentation scoring requires one fact")
        return backend.assess_presentation_fact(scoring_input, fact)
    if fact is not None:
        raise ValueError("accuracy scoring is response-level and must not receive one fact")
    return backend.assess_accuracy(scoring_input)


def _validate_contract_result(
    contract: ScoringContract,
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    result: ContractResult,
    content_result: FactContentAssessmentResult | None,
) -> None:
    """Validate one call result using only its contract's required dependencies."""
    if contract == ScoringContract.CONTENT:
        if not isinstance(result, FactContentAssessmentResult):
            raise TypeError("content contract returned the wrong result type")
        validate_content_fact_result(scoring_input, transcript, result)
        return
    if contract == ScoringContract.PRESENTATION:
        if not isinstance(result, FactPresentationAssessmentResult):
            raise TypeError("presentation contract returned the wrong result type")
        if content_result is None:
            raise ValueError("presentation validation requires the cached content result for the same response")
        if not content_result.judgment.present:
            raise ValueError("presentation scoring is permitted only for a content-present fact")
        validate_presentation_fact_result(scoring_input, transcript, result)
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
    fact_id: str | None,
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
        "fact_id": fact_id,
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
    fact_id: str | None,
    scoring_manifest: ScoringExecutionManifest,
) -> str:
    """Hash one independently retryable provider request boundary."""
    return artifact_sha256(
        {
            "scoring_input": scoring_input,
            "contract": contract,
            "fact_id": fact_id,
            "scoring_contract_sha256": scoring_manifest.scoring_contract_sha256,
            "judge_model_ids": scoring_manifest.judge_model_ids,
        }
    )


def _run_or_resume_call(
    run_unit_id: str,
    scoring_input: ConditionBlindScoringInput,
    contract: ScoringContract,
    fact: BlindFactReference | None,
    transcript: ConversationTranscript,
    content_result: FactContentAssessmentResult | None,
    scoring_manifest: ScoringExecutionManifest,
    backend: ConditionBlindScoringBackend,
    cached_artifact: ScoringCallArtifact | None,
    existing_failures: List[ScoringExecutionAttempt],
    call_path: Path,
    failure_path: Path,
) -> ScoringCallArtifact | None:
    """Reuse one successful call or retry only that failed response-contract-fact key."""
    fact_id = fact.fact_id if fact is not None else None
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

    request_sha256 = _request_digest(scoring_input, contract, fact_id, scoring_manifest)
    failures = sorted(existing_failures, key=lambda item: item.attempt_number)
    if any(attempt.request_sha256 != request_sha256 for attempt in failures):
        raise ValueError("failed scoring attempts do not bind the active request")
    maximum_attempts = scoring_manifest.retry_policy.max_retries + 1
    attempts = list(failures)
    while len(attempts) < maximum_attempts:
        attempt_number = len(attempts) + 1
        started_at = utc_now()
        try:
            result = _execute_contract(backend, contract, scoring_input, fact)
            _validate_contract_result(contract, scoring_input, transcript, result, content_result)
            _validate_provider(result, scoring_manifest)
        except Exception as error:
            failed_attempt = ScoringExecutionAttempt(
                schema_version="3.0.0",
                attempt_id=_attempt_id(run_unit_id, scoring_input.scored_response, contract, fact_id, attempt_number),
                run_unit_id=run_unit_id,
                blind_conversation_id=scoring_input.blind_conversation_id,
                scored_response=scoring_input.scored_response,
                contract=contract,
                fact_id=fact_id,
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
            attempt_id=_attempt_id(run_unit_id, scoring_input.scored_response, contract, fact_id, attempt_number),
            run_unit_id=run_unit_id,
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            contract=contract,
            fact_id=fact_id,
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
            fact_id,
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
    """Resume content-gated scoring and persist a bundle or manual queue record per conversation."""
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
        key = _call_key(artifact.run_unit_id, artifact.scored_response, artifact.contract, artifact.fact_id)
        if key in cached_by_key:
            raise ValueError("successful scoring-call cache contains a duplicate response-contract-fact key")
        cached_by_key[key] = artifact
    failures_by_key: Dict[CallKey, List[ScoringExecutionAttempt]] = {}
    for attempt in existing_failures:
        failures_by_key.setdefault(
            _call_key(attempt.run_unit_id, attempt.scored_response, attempt.contract, attempt.fact_id),
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
        completed: Dict[Tuple[ScoredResponse, ScoringContract, Optional[str]], ScoringCallArtifact] = {}
        exhausted = False
        for contract in ScoringContract:
            for response in ScoredResponse:
                scoring_input = scoring_inputs[response]
                facts: List[BlindFactReference | None] = (
                    list(scoring_input.facts) if contract in {ScoringContract.CONTENT, ScoringContract.PRESENTATION} else [None]
                )
                if contract == ScoringContract.PRESENTATION:
                    facts = [
                        fact
                        for fact in scoring_input.facts
                        if cast(
                            FactContentAssessmentResult,
                            _result_from_artifact(completed[(response, ScoringContract.CONTENT, fact.fact_id)]),
                        ).judgment.present
                    ]
                for fact in facts:
                    fact_id = fact.fact_id if fact is not None else None
                    key = _call_key(run_unit_id, response, contract, fact_id)
                    content_result = None
                    if contract == ScoringContract.PRESENTATION:
                        content_artifact = completed[(response, ScoringContract.CONTENT, fact_id)]
                        content_value = _result_from_artifact(content_artifact)
                        if not isinstance(content_value, FactContentAssessmentResult):
                            raise TypeError("cached fact-content call contains the wrong result type")
                        content_result = content_value
                    artifact = _run_or_resume_call(
                        run_unit_id=run_unit_id,
                        scoring_input=scoring_input,
                        contract=contract,
                        fact=fact,
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
                    completed[(response, contract, fact_id)] = artifact
                    cached_by_key[key] = artifact
                if exhausted:
                    break
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
                item.fact_id or "",
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
                "reason": "One response-contract-fact call exhausted its frozen retry policy; blinded manual resolution is required.",
            }
            record = ManualScoringQueueRecord.model_validate({**queue_payload, "record_sha256": artifact_sha256(queue_payload)})
            _append_unique(queue_path, record, "run_unit_id")
            continue

        content_results = {
            response: aggregate_content_fact_results(
                scoring_inputs[response],
                [
                    cast(
                        FactContentAssessmentResult,
                        _result_from_artifact(completed[(response, ScoringContract.CONTENT, fact.fact_id)]),
                    )
                    for fact in scoring_inputs[response].facts
                ],
            )
            for response in ScoredResponse
        }
        presentation_results = {
            response: aggregate_presentation_fact_results(
                scoring_inputs[response],
                [
                    cast(
                        FactPresentationAssessmentResult,
                        _result_from_artifact(completed[(response, ScoringContract.PRESENTATION, fact.fact_id)]),
                    )
                    for fact in scoring_inputs[response].facts
                    if (response, ScoringContract.PRESENTATION, fact.fact_id) in completed
                ],
                content_results[response],
            )
            for response in ScoredResponse
        }
        accuracy_results = {
            response: cast(AccuracyAssessmentResult, _result_from_artifact(completed[(response, ScoringContract.ACCURACY, None)]))
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


def _judge_snapshot(model: ExperimentModelSpec, frozen_at: datetime) -> EvaluatedModelSnapshot:
    """Freeze the configured independent judge identity for one scoring run."""
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


def _load_or_create_scoring_manifest(
    path: Path,
    response_config: ResponseGenerationConfig,
    judge_model_id: str | None,
    fact_order_seed: int,
    max_retries: int,
    backoff_seconds: List[float],
    frozen_by: str | None,
) -> ScoringExecutionManifest:
    """Load an authenticated scoring manifest or freeze one from the configured judge."""
    if path.exists():
        manifest = read_model_json(path, ScoringExecutionManifest)
        validate_model_self_hash(manifest, "manifest_sha256")
        if manifest.freeze_status != FreezeStatus.FROZEN:
            raise ValueError("scoring execution manifest must be frozen")
        if manifest.scoring_contract_sha256 != scoring_contract_sha256():
            raise ValueError("scoring execution manifest does not bind the active scoring contracts")
        if judge_model_id is not None and manifest.judge_model_ids != [judge_model_id]:
            raise ValueError("requested scoring judge differs from the existing scoring manifest")
        return manifest

    if not frozen_by or not frozen_by.strip():
        raise ValueError("--frozen-by is required when creating a scoring execution manifest")
    catalog = load_model_catalog()
    selected_id = judge_model_id or catalog.scoring_models[0].model_id
    configured = {model.model_id: model for model in catalog.scoring_models}
    if selected_id not in configured:
        raise ValueError(f"unconfigured scoring judge: {selected_id}")
    if selected_id in {model.model_id for model in response_config.evaluated_models}:
        raise ValueError("the scoring judge must be independent of every evaluated model")
    retry_policy = RetryPolicy(
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        reuse_identical_prompt_bytes=True,
    )
    frozen_at = utc_now()
    snapshot = _judge_snapshot(configured[selected_id], frozen_at)
    payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "judge_model_ids": [selected_id],
        "judge_snapshots": [snapshot],
        "scoring_contract_sha256": scoring_contract_sha256(),
        "fact_order_seed": fact_order_seed,
        "retry_policy": retry_policy,
        "frozen_at": frozen_at,
        "frozen_by": frozen_by.strip(),
    }
    manifest = ScoringExecutionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(path, manifest)
    return manifest


def _expected_scenario_ids(scope: ResponseScenarioScope) -> set[str]:
    """Return the published scenario identifiers selected by one response scope."""
    calibration_ids = {f"CF{index:03d}_C1" for index in range(1, 11)}
    evaluation_ids = {f"CF{index:03d}_R{replication}" for index in range(1, 11) for replication in range(1, 3)}
    if scope == ResponseScenarioScope.C:
        return calibration_ids
    if scope == ResponseScenarioScope.R:
        return evaluation_ids
    return calibration_ids | evaluation_ids


def _validate_response_scoring_inputs(
    transcripts: List[ConversationTranscript],
    run_units: List[RunUnit],
    scenarios: List[AcceptedScenario],
    accepted_manifest: AcceptedScenarioManifest,
    response_config: ResponseGenerationConfig,
) -> Dict[str, AcceptedScenario]:
    """Authenticate a completed generic response matrix before any scoring call."""
    if response_config.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("response config does not bind the accepted-scenario manifest")
    expected_ids = _expected_scenario_ids(response_config.scenario_scope)
    selected_scenarios = {scenario.scenario_id: scenario for scenario in scenarios if scenario.scenario_id in expected_ids}
    if set(selected_scenarios) != expected_ids:
        raise ValueError("accepted scenarios do not contain the response config's exact scope")
    if len(run_units) != response_config.expected_conversation_count or len(transcripts) != response_config.expected_conversation_count:
        raise ValueError("scoring requires the response config's complete conversation matrix")
    plan_by_id = {unit.run_unit_id: unit for unit in run_units}
    if len(plan_by_id) != len(run_units):
        raise ValueError("response run plan contains duplicate run-unit ids")
    transcript_ids = [transcript.run_unit.run_unit_id for transcript in transcripts]
    if len(transcript_ids) != len(set(transcript_ids)) or set(transcript_ids) != set(plan_by_id):
        raise ValueError("active transcripts do not exactly cover the response run plan")
    if any(transcript.outcome_status != RunOutcomeStatus.COMPLETED for transcript in transcripts):
        raise ValueError("scoring requires every active response conversation to be completed")
    if any(plan_by_id[transcript.run_unit.run_unit_id] != transcript.run_unit for transcript in transcripts):
        raise ValueError("an active transcript differs from its authenticated run-plan unit")
    if {unit.scenario_id for unit in run_units} != expected_ids:
        raise ValueError("response run plan scenario ids differ from its configured scope")
    expected_model_ids = {model.model_id for model in response_config.evaluated_models}
    if {unit.model_id for unit in run_units} != expected_model_ids:
        raise ValueError("response run plan model ids differ from its configured snapshots")
    return selected_scenarios


def main() -> None:
    """Score completed transcripts without exposing treatment or model labels to the backend."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=DEFAULT_SCORING_BACKEND)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--response-config", type=Path)
    parser.add_argument("--run-plan", type=Path)
    parser.add_argument("--accepted-root", type=Path, default=ACTIVE_SCENARIO_ACCEPTED_ROOT)
    parser.add_argument("--accepted-scenario-manifest", type=Path, default=DEFAULT_ACCEPTED_MANIFEST_PATH)
    parser.add_argument("--scoring-execution-manifest", type=Path)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--judge-model-id")
    parser.add_argument("--fact-order-seed", type=int, default=7)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--backoff-seconds", nargs="+", type=float, default=[1.0, 2.0])
    parser.add_argument("--frozen-by")
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("automated scoring may call paid APIs and requires --execute-paid")

    experiment_dir = args.transcripts.parent.parent
    response_config_path = args.response_config or experiment_dir / "config.json"
    run_plan_path = args.run_plan or experiment_dir / "checkpoints/run_plan.jsonl"
    scoring_manifest_path = args.scoring_execution_manifest or experiment_dir / "checkpoints/scoring_execution_manifest.json"
    results_dir = args.results_dir or experiment_dir / "results/scoring"
    response_config = read_model_json(response_config_path, ResponseGenerationConfig)
    if experiment_dir.name != response_config.experiment_name:
        raise ValueError("transcript experiment directory differs from its response config name")
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    scenarios = load_all_accepted_scenarios(args.accepted_root, accepted_manifest)
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    run_units = read_model_jsonl(run_plan_path, RunUnit)
    selected_scenarios = _validate_response_scoring_inputs(
        transcripts,
        run_units,
        scenarios,
        accepted_manifest,
        response_config,
    )
    scoring_manifest = _load_or_create_scoring_manifest(
        path=scoring_manifest_path,
        response_config=response_config,
        judge_model_id=args.judge_model_id,
        fact_order_seed=args.fact_order_seed,
        max_retries=args.max_retries,
        backoff_seconds=args.backoff_seconds,
        frozen_by=args.frozen_by,
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    backend = _load_backend(args.backend, scoring_manifest.judge_snapshots[0])
    execute_scoring_transcripts(
        transcripts=transcripts,
        scenarios=selected_scenarios,
        scoring_manifest=scoring_manifest,
        results_dir=results_dir,
        backend=backend,
    )
    print(f"Content-gated scoring bundles and any manual queue records are under {results_dir}")


if __name__ == "__main__":
    main()
