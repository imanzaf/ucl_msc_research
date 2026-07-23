"""Resolve terminal scoring escalations from condition-blind human annotations."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    ClaimAssessmentResult,
    EvaluationCheckpoint,
    FactAssessmentResult,
    ManualScoringQueueRecord,
    ManualScoringResolution,
    ResponseCommunicationResult,
)
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.scenario_runner import validate_complete_run_plan
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results
from src.storage import read_model_json, read_model_jsonl, write_models_jsonl_atomic


def build_manual_resolution(
    queue_record: ManualScoringQueueRecord,
    annotation: ConversationAnnotation,
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
) -> ManualScoringResolution:
    """Validate one blinded annotation and convert it to analysis-equivalent scoring."""
    if transcript.outcome_status != RunOutcomeStatus.COMPLETED:
        raise ValueError("manual scoring may resolve only a completed conversation")
    if queue_record.run_unit_id != transcript.run_unit.run_unit_id or queue_record.transcript_sha256 != transcript.transcript_sha256:
        raise ValueError("manual-scoring queue record does not bind the supplied transcript")
    scoring_input_sha256 = artifact_sha256(queue_record.scoring_input)
    if annotation.blind_conversation_id != queue_record.scoring_input.blind_conversation_id:
        raise ValueError("manual annotation does not bind the queued blind conversation")
    if annotation.scoring_input_sha256 != scoring_input_sha256:
        raise ValueError("manual annotation does not bind the exact condition-blind scoring input")
    manual_judge_id = f"manual:{annotation.researcher_id}"
    fact_result = FactAssessmentResult(
        schema_version="2.0.0",
        blind_conversation_id=annotation.blind_conversation_id,
        judgments=annotation.fact_judgments,
        judge_model_id=manual_judge_id,
        scoring_prompt_sha256=annotation.rubric_sha256,
        scored_at=annotation.submitted_at,
    )
    response_result = ResponseCommunicationResult(
        schema_version="2.0.0",
        blind_conversation_id=annotation.blind_conversation_id,
        judgments=annotation.response_judgments,
        judge_model_id=manual_judge_id,
        scoring_prompt_sha256=annotation.rubric_sha256,
        scored_at=annotation.submitted_at,
    )
    claim_result = ClaimAssessmentResult(
        schema_version="2.0.0",
        blind_conversation_id=annotation.blind_conversation_id,
        claims=annotation.claim_judgments,
        visible_source_sha256=queue_record.scoring_input.visible_source_sha256,
        judge_model_id=manual_judge_id,
        scoring_prompt_sha256=annotation.rubric_sha256,
        scored_at=annotation.submitted_at,
    )
    validate_scoring_results(queue_record.scoring_input, transcript, fact_result, response_result, claim_result)
    metrics = [
        compute_conversation_metrics(
            transcript,
            scenario,
            fact_result,
            response_result,
            claim_result,
            checkpoint,
            prompt_factor_isolation_valid=True,
        )
        for checkpoint in EvaluationCheckpoint
    ]
    payload = {
        "schema_version": "2.0.0",
        "run_unit_id": queue_record.run_unit_id,
        "transcript_sha256": transcript.transcript_sha256,
        "scoring_execution_manifest_sha256": queue_record.scoring_execution_manifest_sha256,
        "scoring_contract_sha256": queue_record.scoring_contract_sha256,
        "queue_record_sha256": queue_record.record_sha256,
        "scoring_input": queue_record.scoring_input,
        "fact_result": fact_result,
        "response_result": response_result,
        "claim_result": claim_result,
        "metrics": metrics,
        "annotation_id": annotation.annotation_id,
        "researcher_id": annotation.researcher_id,
        "rubric_sha256": annotation.rubric_sha256,
        "resolved_at": annotation.submitted_at,
    }
    return ManualScoringResolution.model_validate({**payload, "resolution_sha256": artifact_sha256(payload)})


def main() -> None:
    """Resolve every queued conversation exactly once and write immutable records."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual-queue", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("manual scoring requires a frozen scoring manifest")
    queue_records = read_model_jsonl(args.manual_queue, ManualScoringQueueRecord)
    annotations = read_model_jsonl(args.annotations, ConversationAnnotation)
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    validate_complete_run_plan([transcript.run_unit for transcript in transcripts])
    transcript_by_id = {transcript.run_unit.run_unit_id: transcript for transcript in transcripts}
    scenario_by_id: Dict[str, AcceptedScenario] = {
        scenario.scenario_id: scenario for scenario in load_accepted_evaluation_scenarios(args.accepted_root, accepted_manifest)
    }
    annotation_by_blind_id: Dict[str, ConversationAnnotation] = {}
    for annotation in annotations:
        if annotation.blind_conversation_id in annotation_by_blind_id:
            raise ValueError("manual resolution input requires exactly one final annotation per blind conversation")
        annotation_by_blind_id[annotation.blind_conversation_id] = annotation
    resolutions: List[ManualScoringResolution] = []
    for queue_record in queue_records:
        selected_annotation = annotation_by_blind_id.get(queue_record.scoring_input.blind_conversation_id)
        if selected_annotation is None:
            raise ValueError(f"manual-scoring queue remains unresolved: {queue_record.run_unit_id}")
        transcript = transcript_by_id[queue_record.run_unit_id]
        resolutions.append(build_manual_resolution(queue_record, selected_annotation, transcript, scenario_by_id[transcript.run_unit.scenario_id]))
    if len(annotations) != len(resolutions):
        raise ValueError("manual annotations contain a conversation that is not in the terminal scoring queue")
    write_models_jsonl_atomic(args.output, resolutions)
    print(f"Resolved {len(resolutions)} terminal scoring failures to {args.output}")


if __name__ == "__main__":
    main()
