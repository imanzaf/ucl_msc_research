"""Validate versioned C1 output before freezing the redesigned scoring contract."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from src.cli.commands.calibration.run_c1 import DEFAULT_EXPERIMENT_NAME
from src.data_models.common import artifact_sha256, file_sha256, utc_now
from src.data_models.scoring import (
    C1ScoringDiagnosticReport,
    ManualScoringQueueRecord,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringAttemptStatus,
    ScoringCallArtifact,
    ScoringContract,
)
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import read_model_jsonl, write_model_json_atomic


def validate_c1_records(
    bundles: List[ScoredConversationBundle],
    calls: List[ScoringCallArtifact],
    queued: List[ManualScoringQueueRecord],
    expected_conversation_count: int = 40,
) -> int:
    """Validate complete, linked eighteen-call C1 records and return the success count."""
    if queued:
        raise ValueError("C1 redesigned-output validation requires no manual queue")
    bundles_by_id = {bundle.run_unit_id: bundle for bundle in bundles}
    if len(bundles) != expected_conversation_count or len(bundles_by_id) != expected_conversation_count:
        raise ValueError(f"C1 redesigned-output validation requires {expected_conversation_count} unique bundles")
    expected_call_count = expected_conversation_count * 18
    if len(calls) != expected_call_count:
        raise ValueError(f"C1 redesigned-output validation requires {expected_call_count} call artifacts")
    calls_by_key = {(call.run_unit_id, call.scored_response, call.contract, call.fact_id): call for call in calls}
    if len(calls_by_key) != expected_call_count:
        raise ValueError("C1 scoring calls contain a duplicate response-contract-fact key")
    expected_keys = {
        key
        for run_unit_id, bundle in bundles_by_id.items()
        for response in ScoredResponse
        for key in [
            *[
                (run_unit_id, response, contract, fact.fact_id)
                for contract in (ScoringContract.CONTENT, ScoringContract.PRESENTATION)
                for fact in bundle.scoring_inputs[response].facts
            ],
            (run_unit_id, response, ScoringContract.ACCURACY, None),
        ]
    }
    if set(calls_by_key) != expected_keys:
        raise ValueError("C1 call artifacts do not provide all eighteen calls for every bundle")
    active_contract_sha256 = scoring_contract_sha256()
    if {bundle.scoring_contract_sha256 for bundle in bundles} != {active_contract_sha256}:
        raise ValueError("C1 bundles do not use the active scoring contract")
    for (run_unit_id, response, contract, fact_id), call in calls_by_key.items():
        bundle = bundles_by_id[run_unit_id]
        if call.scoring_execution_manifest_sha256 != bundle.scoring_execution_manifest_sha256:
            raise ValueError("C1 call artifact and bundle use different scoring manifests")
        if call.scoring_input_sha256 != artifact_sha256(bundle.scoring_inputs[response]):
            raise ValueError("C1 call artifact does not bind its isolated bundle input")
        call_result = {
            ScoringContract.CONTENT: call.content_result,
            ScoringContract.PRESENTATION: call.presentation_result,
            ScoringContract.ACCURACY: call.accuracy_result,
        }[contract]
        if contract == ScoringContract.CONTENT:
            bundle_judgment = next(item for item in bundle.content_results[response].judgments if item.fact_id == fact_id)
            if artifact_sha256(call_result.judgment) != artifact_sha256(bundle_judgment):
                raise ValueError("C1 fact-content call does not match its bundle judgment")
        elif contract == ScoringContract.PRESENTATION:
            bundle_findings = [item for item in bundle.presentation_results[response].findings if item.fact_id == fact_id]
            if artifact_sha256(call_result.findings) != artifact_sha256(bundle_findings):
                raise ValueError("C1 fact-presentation call does not match its bundle findings")
        elif artifact_sha256(call_result) != artifact_sha256(bundle.accuracy_results[response]):
            raise ValueError("C1 accuracy call does not match its bundle result")
    successful_attempt_count = sum(attempt.status == ScoringAttemptStatus.SUCCEEDED for call in calls for attempt in call.attempts)
    if successful_attempt_count != expected_call_count:
        raise ValueError("C1 call artifacts require one success per response-contract-fact key")
    return successful_attempt_count


def main() -> None:
    """Require 40 valid bundles and 720 successful isolated provider calls."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-name", default=DEFAULT_EXPERIMENT_NAME)
    parser.add_argument("--scored-bundles", type=Path, required=True)
    parser.add_argument("--scoring-calls", type=Path, required=True)
    parser.add_argument("--manual-queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundles = read_model_jsonl(args.scored_bundles, ScoredConversationBundle)
    calls = read_model_jsonl(args.scoring_calls, ScoringCallArtifact)
    queued = read_model_jsonl(args.manual_queue, ManualScoringQueueRecord)
    successful_attempt_count = validate_c1_records(bundles, calls, queued)
    payload = {
        "schema_version": "3.0.0",
        "experiment_name": args.experiment_name,
        "scoring_contract_sha256": scoring_contract_sha256(),
        "expected_conversation_count": 40,
        "validated_conversation_count": len(bundles),
        "successful_provider_call_count": successful_attempt_count,
        "response_isolation_valid": True,
        "output_validation_passed": True,
        "source_bundles_sha256": file_sha256(args.scored_bundles),
        "source_calls_sha256": file_sha256(args.scoring_calls),
        "generated_at": utc_now(),
    }
    report = C1ScoringDiagnosticReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, report)
    print(f"Validated redesigned C1 scoring output to {args.output}")


if __name__ == "__main__":
    main()
