"""Run the resumable 60-output calibration-only 320-word adequacy pilot."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from pydantic import BaseModel

from src.data_models.common import artifact_sha256, canonical_json_bytes, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.experiments import CompletionFinishReason, RetryPolicy, provider_request_sha256
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AmplePilotApproval,
    AmplePilotAttempt,
    AmplePilotCostReport,
    AmplePilotRecord,
    CalibrationPromptReviewManifest,
    CueReviewDecision,
    EvaluatedModelManifest,
    FreezeStatus,
    PilotAttemptStatus,
)
from src.data_models.scenarios import AcceptedScenario
from src.data_models.study import PILOT_WORD_LIMIT, ExperimentCell, ExpressedConcernCondition, IntegrityCondition, WordBudgetCondition
from src.experiments.io import load_accepted_calibration_scenarios
from src.llm.openrouter import OpenRouterClient, ProviderTextResponse
from src.paths import (
    ACTIVE_SCENARIO_ACCEPTED_ROOT,
    ACTIVE_SCENARIO_CHECKPOINT_ROOT,
    ACTIVE_SCENARIO_GENERATION_ROOT,
    ACTIVE_SCENARIO_INPUT_ROOT,
    AMPLE_PILOT_APPROVAL_PATH,
    AMPLE_PILOT_ATTEMPTS_PATH,
    AMPLE_PILOT_COST_REPORT_PATH,
    AMPLE_PILOT_RECORDS_PATH,
    EVALUATED_MODEL_MANIFEST_PATH,
)
from src.prompts.experiment import compile_experiment_prompt, prompt_package_sha256
from src.scenarios.word_count import count_words
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl


def _identifier(prefix: str, *parts: str) -> str:
    """Derive a stable sixteen-hex pilot or attempt identifier."""
    return f"{prefix}_{sha256_bytes(canonical_json_bytes(list(parts))).upper()[:16]}"


def _append_unique(path: Path, model: BaseModel, field_name: str) -> None:
    """Append one strict model while rejecting a duplicate semantic identifier."""

    def validate(existing: List[BaseModel], new: BaseModel) -> None:
        """Reject an existing identifier under the storage lock."""
        if any(getattr(item, field_name) == getattr(new, field_name) for item in existing):
            raise ValueError(f"duplicate {field_name}: {getattr(new, field_name)}")

    append_model_jsonl_validated(path, model, validate)


def compile_ample_pilot_messages(
    scenario: AcceptedScenario,
    cue: ExpressedConcernCondition,
    integrity: IntegrityCondition,
) -> Tuple[List[Dict[str, str]], str]:
    """Compile the exact 320-word pilot request without a follow-up turn."""
    cell = ExperimentCell.create(WordBudgetCondition.AMPLE, cue, integrity)
    messages, _follow_up, prompt_sha256, _follow_up_sha256 = compile_experiment_prompt(scenario, cell, PILOT_WORD_LIMIT)
    return [{"role": message.role.value, "content": message.content} for message in messages], prompt_sha256


def compile_ample_pilot_request(
    scenario: AcceptedScenario,
    model_id: str,
    cue: ExpressedConcernCondition,
    integrity: IntegrityCondition,
    study_seed: int,
) -> Tuple[List[Dict[str, str]], str, str, int, str]:
    """Compile one exact provider request and all deterministic request identifiers."""
    messages, prompt_sha256 = compile_ample_pilot_messages(scenario, cue, integrity)
    record_id = _identifier("PILOT", scenario.scenario_id, model_id, cue.value, integrity.value)
    random_seed = int(sha256_bytes(f"{study_seed}:{record_id}".encode("utf-8"))[:16], 16)
    request_sha256 = provider_request_sha256(messages, model_id, 0.0, PILOT_WORD_LIMIT * 4, random_seed)
    return messages, prompt_sha256, record_id, random_seed, request_sha256


def _build_pilot_record(
    scenario: AcceptedScenario,
    model_id: str,
    model_snapshot_sha256: str,
    expected_model_version: str,
    prompt_review_manifest_sha256: str,
    cue: ExpressedConcernCondition,
    integrity: IntegrityCondition,
    prompt_sha256: str,
    request_sha256: str,
    random_seed: int,
    response: ProviderTextResponse,
    completed_at: datetime,
) -> AmplePilotRecord:
    """Build the response record shared by normal completion and cache recovery."""
    response_sha256 = sha256_bytes(response.text.encode("utf-8"))
    payload = {
        "schema_version": "2.0.0",
        "pilot_record_id": _identifier("PILOT", scenario.scenario_id, model_id, cue.value, integrity.value),
        "scenario_id": scenario.scenario_id,
        "use_case_id": scenario.use_case_id,
        "model_id": model_id,
        "model_snapshot_sha256": model_snapshot_sha256,
        "prompt_review_manifest_sha256": prompt_review_manifest_sha256,
        "expected_model_version": expected_model_version,
        "returned_model_version": response.returned_model_version,
        "expressed_concern": cue,
        "integrity": integrity,
        "pilot_word_limit": PILOT_WORD_LIMIT,
        "output_text": response.text,
        "output_word_count": count_words(response.text),
        "finished_naturally": response.finish_reason == CompletionFinishReason.STOP,
        "finish_reason": response.finish_reason,
        "prompt_sha256": prompt_sha256,
        "request_sha256": request_sha256,
        "random_seed": random_seed,
        "provider_request_id": response.provider_request_id,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "scenario_artifact_sha256": scenario.artifact_sha256,
        "generated_at": completed_at,
        "output_sha256": response_sha256,
    }
    return AmplePilotRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)})


def _recover_cached_success(
    client: OpenRouterClient,
    attempt: AmplePilotAttempt,
    request_sha256: str,
) -> ProviderTextResponse:
    """Recover a logged successful response from the exact-request cache without a paid retry."""
    response = client.read_cached_text_response(request_sha256)
    if response is None:
        raise RuntimeError("successful ample-pilot attempt has no response record or exact-request cache entry")
    response_sha256 = sha256_bytes(response.text.encode("utf-8"))
    expected = {
        "returned_model_version": response.returned_model_version,
        "provider_request_id": response.provider_request_id,
        "finish_reason": response.finish_reason,
        "response_sha256": response_sha256,
    }
    if any(getattr(attempt, name) != value for name, value in expected.items()):
        raise ValueError("cached ample-pilot response differs from the logged successful attempt")
    return response


def main() -> None:
    """Validate frozen inputs, resume exact requests, and persist every provider outcome."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--retry-policy", type=Path, required=True)
    parser.add_argument("--cost-report", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("the ample pilot may call paid APIs and requires --execute-paid")
    expected_paths = [
        (args.accepted_root, ACTIVE_SCENARIO_ACCEPTED_ROOT),
        (args.accepted_scenario_manifest, ACTIVE_SCENARIO_INPUT_ROOT / "calibration_accepted_scenario_manifest.json"),
        (args.evaluated_model_manifest, EVALUATED_MODEL_MANIFEST_PATH),
        (args.prompt_review_manifest, ACTIVE_SCENARIO_CHECKPOINT_ROOT / "calibration_prompt_review.json"),
        (args.cost_report, AMPLE_PILOT_COST_REPORT_PATH),
        (args.approval, AMPLE_PILOT_APPROVAL_PATH),
        (args.records, AMPLE_PILOT_RECORDS_PATH),
        (args.attempts, AMPLE_PILOT_ATTEMPTS_PATH),
        (args.cache_dir, ACTIVE_SCENARIO_GENERATION_ROOT / "cache"),
    ]
    if any(supplied.resolve() != expected.resolve() for supplied, expected in expected_paths):
        raise ValueError("ample-pilot execution must use the fixed V0.10.0 lifecycle paths")
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    model_manifest = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, CalibrationPromptReviewManifest)
    retry_policy = read_model_json(args.retry_policy, RetryPolicy)
    cost_report = read_model_json(args.cost_report, AmplePilotCostReport)
    approval = read_model_json(args.approval, AmplePilotApproval)
    for manifest in [accepted_manifest, model_manifest, prompt_review]:
        validate_model_self_hash(manifest, "manifest_sha256")
    validate_model_self_hash(cost_report, "report_sha256")
    validate_model_self_hash(approval, "approval_sha256")
    if model_manifest.freeze_status != FreezeStatus.FROZEN or prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("ample pilot requires frozen model snapshots and an approved C1 prompt review")
    if prompt_review.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("prompt review does not bind the accepted calibration scenarios")
    expected_cost_bindings = {
        "accepted_scenario_manifest_sha256": accepted_manifest.manifest_sha256,
        "evaluated_model_manifest_sha256": model_manifest.manifest_sha256,
        "prompt_review_manifest_sha256": prompt_review.manifest_sha256,
        "prompt_package_sha256": prompt_package_sha256(),
        "retry_policy_sha256": artifact_sha256(retry_policy),
    }
    if any(getattr(cost_report, name) != value for name, value in expected_cost_bindings.items()):
        raise ValueError("ample-pilot cost report does not bind the supplied frozen inputs")
    if cost_report.maximum_attempts_including_retries != 60 * (retry_policy.max_retries + 1):
        raise ValueError("ample-pilot cost report does not match the supplied retry policy")
    if cost_report.randomisation_seed != args.seed:
        raise ValueError("ample-pilot cost report does not bind the requested randomisation seed")
    if approval.cost_report_sha256 != cost_report.report_sha256:
        raise ValueError("ample-pilot approval does not bind the supplied cost report")
    if approval.approved_maximum_cost_usd < cost_report.worst_case_cost_usd:
        raise ValueError("ample-pilot approval maximum is below the worst-case cost")
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted_manifest)
    if len(scenarios) != 10:
        raise ValueError("ample pilot requires exactly ten accepted C1 scenarios")
    expected_request_sha256s = sorted(
        compile_ample_pilot_request(scenario, model.model_id, cue, IntegrityCondition.ABSENT, args.seed)[4]
        for scenario in scenarios
        for model in model_manifest.evaluated_models
        for cue in ExpressedConcernCondition
    )
    if cost_report.provider_request_sha256s != expected_request_sha256s:
        raise ValueError("ample-pilot cost report does not bind the exact provider request bytes")
    existing_records = read_model_jsonl(args.records, AmplePilotRecord)
    existing_attempts = read_model_jsonl(args.attempts, AmplePilotAttempt)
    record_by_id = {record.pilot_record_id: record for record in existing_records}
    if len(record_by_id) != len(existing_records):
        raise ValueError("ample-pilot records contain duplicate identifiers")
    attempts_by_record: Dict[str, List[AmplePilotAttempt]] = {}
    for attempt in existing_attempts:
        attempts_by_record.setdefault(attempt.pilot_record_id, []).append(attempt)
    client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), OpenRouterCredentialRole.AGENT, cache_dir=args.cache_dir)
    maximum_attempts = retry_policy.max_retries + 1
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(model_manifest.evaluated_models, key=lambda item: item.model_id):
            for cue in ExpressedConcernCondition:
                integrity = IntegrityCondition.ABSENT
                messages, prompt_sha256, record_id, random_seed, request_digest = compile_ample_pilot_request(
                    scenario,
                    model.model_id,
                    cue,
                    integrity,
                    args.seed,
                )
                existing_record = record_by_id.get(record_id)
                if existing_record is not None:
                    expected_bindings = {
                        "scenario_id": scenario.scenario_id,
                        "use_case_id": scenario.use_case_id,
                        "model_id": model.model_id,
                        "model_snapshot_sha256": artifact_sha256(model),
                        "prompt_review_manifest_sha256": prompt_review.manifest_sha256,
                        "expected_model_version": model.returned_model_version,
                        "expressed_concern": cue,
                        "integrity": integrity,
                        "prompt_sha256": prompt_sha256,
                        "request_sha256": request_digest,
                        "random_seed": random_seed,
                        "scenario_artifact_sha256": scenario.artifact_sha256,
                    }
                    if any(getattr(existing_record, name) != value for name, value in expected_bindings.items()):
                        raise ValueError(f"resumed ample-pilot record differs from the active frozen request: {record_id}")
                    successful_attempts = [
                        attempt
                        for attempt in attempts_by_record.get(record_id, [])
                        if attempt.status == PilotAttemptStatus.SUCCEEDED
                        and attempt.request_sha256 == request_digest
                        and attempt.response_sha256 == existing_record.output_sha256
                    ]
                    if len(successful_attempts) != 1:
                        raise ValueError("completed ample-pilot record must bind exactly one successful attempt")
                    continue
                prior_attempts = sorted(attempts_by_record.get(record_id, []), key=lambda item: item.attempt_number)
                if any(attempt.request_sha256 != request_digest for attempt in prior_attempts):
                    raise ValueError("resumed ample-pilot attempt used different request bytes")
                successful_attempts = [attempt for attempt in prior_attempts if attempt.status == PilotAttemptStatus.SUCCEEDED]
                if successful_attempts:
                    if len(successful_attempts) != 1:
                        raise ValueError("ample-pilot request has multiple successful attempts without a response record")
                    successful_attempt = successful_attempts[0]
                    response = _recover_cached_success(client, successful_attempt, request_digest)
                    record = _build_pilot_record(
                        scenario=scenario,
                        model_id=model.model_id,
                        model_snapshot_sha256=artifact_sha256(model),
                        expected_model_version=model.returned_model_version,
                        prompt_review_manifest_sha256=prompt_review.manifest_sha256,
                        cue=cue,
                        integrity=integrity,
                        prompt_sha256=prompt_sha256,
                        request_sha256=request_digest,
                        random_seed=random_seed,
                        response=response,
                        completed_at=successful_attempt.completed_at,
                    )
                    _append_unique(args.records, record, "pilot_record_id")
                    record_by_id[record_id] = record
                    continue
                while len(prior_attempts) < maximum_attempts:
                    attempt_number = len(prior_attempts) + 1
                    started_at = utc_now()
                    try:
                        response = client.complete_text(model.model_id, messages, 0.0, PILOT_WORD_LIMIT * 4, random_seed)
                        if response.returned_model_version != model.returned_model_version:
                            raise ValueError(
                                f"expected frozen model version {model.returned_model_version}, received {response.returned_model_version}"
                            )
                    except Exception as error:
                        attempt_payload = {
                            "schema_version": "2.0.0",
                            "attempt_id": _identifier("PILOTATTEMPT", record_id, str(attempt_number)),
                            "pilot_record_id": record_id,
                            "attempt_number": attempt_number,
                            "request_sha256": request_digest,
                            "status": PilotAttemptStatus.FAILED,
                            "returned_model_version": None,
                            "provider_request_id": None,
                            "finish_reason": None,
                            "response_sha256": None,
                            "error_type": type(error).__name__,
                            "error_message": str(error) or type(error).__name__,
                            "started_at": started_at,
                            "completed_at": utc_now(),
                        }
                        attempt = AmplePilotAttempt.model_validate({**attempt_payload, "attempt_sha256": artifact_sha256(attempt_payload)})
                        _append_unique(args.attempts, attempt, "attempt_id")
                        prior_attempts.append(attempt)
                        if len(prior_attempts) < maximum_attempts:
                            delay = retry_policy.backoff_seconds[len(prior_attempts) - 1]
                            if delay:
                                time.sleep(delay)
                        continue
                    completed_at = utc_now()
                    response_sha256 = sha256_bytes(response.text.encode("utf-8"))
                    attempt_payload = {
                        "schema_version": "2.0.0",
                        "attempt_id": _identifier("PILOTATTEMPT", record_id, str(attempt_number)),
                        "pilot_record_id": record_id,
                        "attempt_number": attempt_number,
                        "request_sha256": request_digest,
                        "status": PilotAttemptStatus.SUCCEEDED,
                        "returned_model_version": response.returned_model_version,
                        "provider_request_id": response.provider_request_id,
                        "finish_reason": response.finish_reason,
                        "response_sha256": response_sha256,
                        "error_type": None,
                        "error_message": None,
                        "started_at": started_at,
                        "completed_at": completed_at,
                    }
                    attempt = AmplePilotAttempt.model_validate({**attempt_payload, "attempt_sha256": artifact_sha256(attempt_payload)})
                    _append_unique(args.attempts, attempt, "attempt_id")
                    prior_attempts.append(attempt)
                    record = _build_pilot_record(
                        scenario=scenario,
                        model_id=model.model_id,
                        model_snapshot_sha256=artifact_sha256(model),
                        expected_model_version=model.returned_model_version,
                        prompt_review_manifest_sha256=prompt_review.manifest_sha256,
                        cue=cue,
                        integrity=integrity,
                        prompt_sha256=prompt_sha256,
                        request_sha256=request_digest,
                        random_seed=random_seed,
                        response=response,
                        completed_at=completed_at,
                    )
                    _append_unique(args.records, record, "pilot_record_id")
                    record_by_id[record_id] = record
                    break
                if record_id not in record_by_id:
                    raise RuntimeError(f"ample-pilot retry policy exhausted for {record_id}; resolve before continuing")
    print(f"Persisted the complete {len(record_by_id)}-record ample pilot to {args.records}")


if __name__ == "__main__":
    main()
