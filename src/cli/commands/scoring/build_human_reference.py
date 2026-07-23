"""Build treatment-linked human-reference metrics only after blinded annotation closes."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, sha256_bytes, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, AnnotationSampleManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    AnalysisInputRow,
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    EvaluationCheckpoint,
    FactAssessmentResult,
    ResponseCommunicationResult,
)
from src.experiments.io import load_all_accepted_scenarios
from src.experiments.scenario_runner import validate_complete_run_plan
from src.experiments.scoring_pipeline import build_condition_blind_input
from src.scoring.annotation_resolution import final_annotations
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results
from src.storage import read_model_json, read_model_jsonl, write_models_jsonl_atomic


def main() -> None:
    """Convert the final blinded reference labels into a locked sensitivity input."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sample = read_model_json(args.annotation_sample_manifest, AnnotationSampleManifest)
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    for manifest in [sample, accepted_manifest, scoring_manifest]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("human-reference input requires the frozen scoring manifest")
    if sample.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
        raise ValueError("annotation sample does not bind the supplied scoring manifest")
    annotations = read_model_jsonl(args.annotations, ConversationAnnotation)
    resolved_annotations, _unused_pairs = final_annotations(sample, annotations)
    scenarios: Dict[str, AcceptedScenario] = {
        scenario.scenario_id: scenario for scenario in load_all_accepted_scenarios(args.accepted_root, accepted_manifest)
    }
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    validate_complete_run_plan([transcript.run_unit for transcript in transcripts])
    selected: Dict[str, Tuple[ConversationTranscript, ConditionBlindScoringInput]] = {}
    for transcript in transcripts:
        if transcript.outcome_status != RunOutcomeStatus.COMPLETED:
            continue
        fact_seed = int(
            sha256_bytes(f"{scoring_manifest.fact_order_seed}:{transcript.run_unit.run_unit_id}".encode("utf-8"))[:16],
            16,
        )
        scoring_input = build_condition_blind_input(transcript, scenarios[transcript.run_unit.scenario_id], fact_seed)
        if scoring_input.blind_conversation_id in set(sample.conversation_ids):
            selected[scoring_input.blind_conversation_id] = (transcript, scoring_input)
    if set(selected) != set(sample.conversation_ids):
        raise ValueError("human-reference sample does not resolve to completed source transcripts")
    rows: List[AnalysisInputRow] = []
    for blind_id in sorted(selected):
        transcript, scoring_input = selected[blind_id]
        annotation = resolved_annotations[blind_id]
        manual_judge_id = f"manual:{annotation.researcher_id}"
        fact_result = FactAssessmentResult(
            schema_version="2.0.0",
            blind_conversation_id=blind_id,
            judgments=annotation.fact_judgments,
            judge_model_id=manual_judge_id,
            scoring_prompt_sha256=annotation.rubric_sha256,
            scored_at=annotation.submitted_at,
        )
        response_result = ResponseCommunicationResult(
            schema_version="2.0.0",
            blind_conversation_id=blind_id,
            judgments=annotation.response_judgments,
            judge_model_id=manual_judge_id,
            scoring_prompt_sha256=annotation.rubric_sha256,
            scored_at=annotation.submitted_at,
        )
        claim_result = ClaimAssessmentResult(
            schema_version="2.0.0",
            blind_conversation_id=blind_id,
            claims=annotation.claim_judgments,
            visible_source_sha256=scoring_input.visible_source_sha256,
            judge_model_id=manual_judge_id,
            scoring_prompt_sha256=annotation.rubric_sha256,
            scored_at=annotation.submitted_at,
        )
        validate_scoring_results(scoring_input, transcript, fact_result, response_result, claim_result)
        result_sha256 = artifact_sha256({"annotation": annotation, "source_scoring_input": scoring_input})
        run_unit = transcript.run_unit
        for checkpoint in EvaluationCheckpoint:
            metrics = compute_conversation_metrics(
                transcript,
                scenarios[run_unit.scenario_id],
                fact_result,
                response_result,
                claim_result,
                checkpoint,
                prompt_factor_isolation_valid=True,
            )
            rows.append(
                AnalysisInputRow(
                    schema_version="2.0.0",
                    run_unit_id=run_unit.run_unit_id,
                    scenario_id=run_unit.scenario_id,
                    use_case_id=run_unit.use_case_id,
                    model_id=run_unit.model_id,
                    source_order=run_unit.source_order,
                    word_budget=run_unit.cell.word_budget,
                    expressed_concern=run_unit.cell.expressed_concern,
                    cue_template_id=int(run_unit.scenario_id[-1]),
                    integrity=run_unit.cell.integrity,
                    metrics=metrics,
                    transcript_sha256=transcript.transcript_sha256,
                    scoring_result_sha256=result_sha256,
                )
            )
    write_models_jsonl_atomic(args.output, rows)
    print(f"Wrote {len(rows)} human-reference checkpoint rows to {args.output}")


if __name__ == "__main__":
    main()
