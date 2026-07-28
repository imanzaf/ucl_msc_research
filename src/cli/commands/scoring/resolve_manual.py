"""Resolve terminal scoring escalations from six-contract human annotations."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    EvaluationCheckpoint,
    ManualScoringQueueRecord,
    ManualScoringResolution,
    PresentationAssessmentResult,
    ScoredResponse,
)
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.scenario_runner import validate_complete_run_plan
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results
from src.storage import read_model_json, read_model_jsonl, write_models_jsonl_atomic

ManualResults = Tuple[
    Dict[ScoredResponse, ContentAssessmentResult],
    Dict[ScoredResponse, PresentationAssessmentResult],
    Dict[ScoredResponse, AccuracyAssessmentResult],
]


def build_manual_results(
    annotation: ConversationAnnotation,
    scoring_inputs: Dict[ScoredResponse, ConditionBlindScoringInput],
    transcript: ConversationTranscript,
) -> ManualResults:
    """Convert one complete annotation into six validated manual result objects."""
    if annotation.scoring_input_sha256 != artifact_sha256(scoring_inputs):
        raise ValueError("manual annotation does not bind the exact pair of isolated scoring inputs")
    blind_ids = {item.blind_conversation_id for item in scoring_inputs.values()}
    if blind_ids != {annotation.blind_conversation_id}:
        raise ValueError("manual annotation does not bind the scoring inputs' blind conversation")
    manual_judge_id = f"manual:{annotation.researcher_id}"
    content_results: Dict[ScoredResponse, ContentAssessmentResult] = {}
    presentation_results: Dict[ScoredResponse, PresentationAssessmentResult] = {}
    accuracy_results: Dict[ScoredResponse, AccuracyAssessmentResult] = {}
    for response in ScoredResponse:
        scoring_input = scoring_inputs[response]
        content_results[response] = ContentAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=annotation.blind_conversation_id,
            scored_response=response,
            judgments=annotation.content_judgments[response],
            judge_model_id=manual_judge_id,
            scoring_prompt_sha256=annotation.rubric_sha256,
            scored_at=annotation.submitted_at,
        )
        presentation_results[response] = PresentationAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=annotation.blind_conversation_id,
            scored_response=response,
            findings=annotation.presentation_findings[response],
            judge_model_id=manual_judge_id,
            scoring_prompt_sha256=annotation.rubric_sha256,
            scored_at=annotation.submitted_at,
        )
        accuracy_results[response] = AccuracyAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=annotation.blind_conversation_id,
            scored_response=response,
            findings=annotation.accuracy_findings[response],
            visible_facts_sha256=scoring_input.visible_facts_sha256,
            judge_model_id=manual_judge_id,
            scoring_prompt_sha256=annotation.rubric_sha256,
            scored_at=annotation.submitted_at,
        )
        validate_scoring_results(
            scoring_input,
            transcript,
            content_results[response],
            presentation_results[response],
            accuracy_results[response],
        )
    return content_results, presentation_results, accuracy_results


def build_manual_resolution(
    queue_record: ManualScoringQueueRecord,
    annotation: ConversationAnnotation,
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
) -> ManualScoringResolution:
    """Convert one blinded annotation to an analysis-equivalent manual resolution."""
    if transcript.outcome_status != RunOutcomeStatus.COMPLETED:
        raise ValueError("manual scoring may resolve only a completed conversation")
    if queue_record.run_unit_id != transcript.run_unit.run_unit_id or queue_record.transcript_sha256 != transcript.transcript_sha256:
        raise ValueError("manual queue record does not bind the supplied transcript")
    content_results, presentation_results, accuracy_results = build_manual_results(
        annotation,
        queue_record.scoring_inputs,
        transcript,
    )
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
    payload = {
        "schema_version": "3.0.0",
        "run_unit_id": queue_record.run_unit_id,
        "transcript_sha256": transcript.transcript_sha256,
        "scoring_execution_manifest_sha256": queue_record.scoring_execution_manifest_sha256,
        "scoring_contract_sha256": queue_record.scoring_contract_sha256,
        "queue_record_sha256": queue_record.record_sha256,
        "scoring_inputs": queue_record.scoring_inputs,
        "content_results": content_results,
        "presentation_results": presentation_results,
        "accuracy_results": accuracy_results,
        "metrics": metrics,
        "annotation_id": annotation.annotation_id,
        "researcher_id": annotation.researcher_id,
        "rubric_sha256": annotation.rubric_sha256,
        "resolved_at": annotation.submitted_at,
    }
    return ManualScoringResolution.model_validate({**payload, "resolution_sha256": artifact_sha256(payload)})


def main() -> None:
    """Resolve every queued conversation exactly once."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual-queue", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    accepted_manifest = read_model_json(
        args.accepted_scenario_manifest,
        AcceptedScenarioManifest,
    )
    scoring_manifest = read_model_json(
        args.scoring_execution_manifest,
        ScoringExecutionManifest,
    )
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("manual scoring requires a frozen scoring manifest")
    queue_records = read_model_jsonl(args.manual_queue, ManualScoringQueueRecord)
    annotations = read_model_jsonl(args.annotations, ConversationAnnotation)
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    validate_complete_run_plan([transcript.run_unit for transcript in transcripts])
    transcript_by_id = {transcript.run_unit.run_unit_id: transcript for transcript in transcripts}
    scenario_by_id = {
        scenario.scenario_id: scenario
        for scenario in load_accepted_evaluation_scenarios(
            args.accepted_root,
            accepted_manifest,
        )
    }
    annotation_by_blind_id: Dict[str, ConversationAnnotation] = {}
    for annotation in annotations:
        if annotation.blind_conversation_id in annotation_by_blind_id:
            raise ValueError("manual resolution requires one annotation per conversation")
        annotation_by_blind_id[annotation.blind_conversation_id] = annotation
    resolutions: List[ManualScoringResolution] = []
    for queue_record in queue_records:
        blind_id = next(iter(queue_record.scoring_inputs.values())).blind_conversation_id
        annotation = annotation_by_blind_id.get(blind_id)
        if annotation is None:
            raise ValueError(f"manual queue remains unresolved: {queue_record.run_unit_id}")
        transcript = transcript_by_id[queue_record.run_unit_id]
        resolutions.append(
            build_manual_resolution(
                queue_record,
                annotation,
                transcript,
                scenario_by_id[transcript.run_unit.scenario_id],
            )
        )
    if len(annotations) != len(resolutions):
        raise ValueError("annotations contain a conversation outside the manual queue")
    write_models_jsonl_atomic(args.output, resolutions)
    print(f"Resolved {len(resolutions)} terminal scoring failures to {args.output}")


if __name__ == "__main__":
    main()
