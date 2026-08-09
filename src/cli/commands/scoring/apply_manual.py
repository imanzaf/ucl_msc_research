"""Apply source-linked manual annotations to queued and automated scoring artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.cli.commands.scoring.resolve_manual import build_manual_edit, build_manual_resolution
from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    ConditionBlindScoringInput,
    ConversationMetrics,
    EffectiveScoringRecord,
    ManualScoringEdit,
    ManualScoringQueueRecord,
    ManualScoringResolution,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringResultSource,
)
from src.experiments.io import load_all_accepted_scenarios
from src.storage import read_model_json, read_model_jsonl, write_models_jsonl_atomic


def _blind_id(scoring_inputs: Dict[ScoredResponse, ConditionBlindScoringInput]) -> str:
    """Return the single blind identifier from a response-keyed scoring-input map."""
    values = list(scoring_inputs.values())
    blind_ids = {item.blind_conversation_id for item in values}
    if len(blind_ids) != 1:
        raise ValueError("scoring inputs must share exactly one blind conversation id")
    return next(iter(blind_ids))


def _index_annotations(annotations: List[ConversationAnnotation]) -> Dict[str, ConversationAnnotation]:
    """Index annotations by blind identifier while rejecting duplicates."""
    indexed: Dict[str, ConversationAnnotation] = {}
    for record in annotations:
        key = record.blind_conversation_id
        if key in indexed:
            raise ValueError(f"duplicate manual annotation blind id: {key}")
        indexed[key] = record
    return indexed


def _effective_record(
    run_unit_id: str,
    transcript_sha256: str,
    source_type: ScoringResultSource,
    source_scoring_sha256: str,
    metrics: List[ConversationMetrics],
    calculated_at: datetime,
) -> EffectiveScoringRecord:
    """Build one self-hashed effective scoring record from the selected source."""
    payload = {
        "schema_version": "1.0.0",
        "run_unit_id": run_unit_id,
        "transcript_sha256": transcript_sha256,
        "source_type": source_type,
        "source_scoring_sha256": source_scoring_sha256,
        "metrics": metrics,
        "calculated_at": calculated_at,
    }
    return EffectiveScoringRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)})


def main() -> None:
    """Write manual edits and terminal resolutions while retaining original automated bundles."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--scored-bundles", type=Path, required=True)
    parser.add_argument("--manual-queue", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--edit-reason", required=True)
    parser.add_argument("--edits-output", type=Path, required=True)
    parser.add_argument("--resolutions-output", type=Path, required=True)
    parser.add_argument("--effective-scores-output", type=Path, required=True)
    args = parser.parse_args()

    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("manual scoring requires a frozen scoring-execution manifest")

    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    transcript_by_run = {transcript.run_unit.run_unit_id: transcript for transcript in transcripts}
    if len(transcripts) != len(transcript_by_run):
        raise ValueError("transcript ledger contains duplicate run-unit ids")

    scenarios: Dict[str, AcceptedScenario] = {
        scenario.scenario_id: scenario for scenario in load_all_accepted_scenarios(args.accepted_root, accepted_manifest)
    }
    bundles = read_model_jsonl(args.scored_bundles, ScoredConversationBundle)
    queue_records = read_model_jsonl(args.manual_queue, ManualScoringQueueRecord)
    annotations = read_model_jsonl(args.annotations, ConversationAnnotation)
    bundle_by_blind = {_blind_id(bundle.scoring_inputs): bundle for bundle in bundles}
    queue_by_blind = {_blind_id(record.scoring_inputs): record for record in queue_records}
    annotation_by_blind = _index_annotations(annotations)
    if len(bundle_by_blind) != len(bundles) or len(queue_by_blind) != len(queue_records):
        raise ValueError("scoring sources contain duplicate blind conversation ids")
    if set(bundle_by_blind) & set(queue_by_blind):
        raise ValueError("a conversation cannot have both an automated bundle and a terminal queue record")
    for source in [*bundles, *queue_records]:
        if source.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
            raise ValueError("scoring source does not bind the supplied scoring-execution manifest")
        if source.scoring_contract_sha256 != scoring_manifest.scoring_contract_sha256:
            raise ValueError("scoring source does not bind the frozen scoring contract")
    if not set(queue_by_blind).issubset(annotation_by_blind):
        missing = sorted(set(queue_by_blind) - set(annotation_by_blind))
        raise ValueError(f"manual queue remains unresolved: {missing[:3]}")
    unknown = sorted(set(annotation_by_blind) - set(bundle_by_blind) - set(queue_by_blind))
    if unknown:
        raise ValueError(f"manual annotations contain unknown scoring inputs: {unknown[:3]}")

    edits: List[ManualScoringEdit] = []
    resolutions: List[ManualScoringResolution] = []
    for blind_id, annotation in sorted(annotation_by_blind.items()):
        if blind_id in bundle_by_blind:
            bundle = bundle_by_blind[blind_id]
            transcript = transcript_by_run[bundle.run_unit_id]
            edits.append(
                build_manual_edit(
                    bundle,
                    annotation,
                    transcript,
                    scenarios[transcript.run_unit.scenario_id],
                    args.edit_reason,
                )
            )
            continue
        queue_record = queue_by_blind[blind_id]
        transcript = transcript_by_run[queue_record.run_unit_id]
        resolutions.append(
            build_manual_resolution(
                queue_record,
                annotation,
                transcript,
                scenarios[transcript.run_unit.scenario_id],
            )
        )

    write_models_jsonl_atomic(args.edits_output, edits)
    write_models_jsonl_atomic(args.resolutions_output, resolutions)
    edit_by_run = {edit.run_unit_id: edit for edit in edits}
    resolution_by_run = {resolution.run_unit_id: resolution for resolution in resolutions}
    bundle_by_run = {bundle.run_unit_id: bundle for bundle in bundles}
    effective_records: List[EffectiveScoringRecord] = []
    for transcript in sorted(transcripts, key=lambda item: item.run_unit.run_unit_id):
        if transcript.outcome_status != RunOutcomeStatus.COMPLETED:
            continue
        run_unit_id = transcript.run_unit.run_unit_id
        if run_unit_id in edit_by_run:
            edit = edit_by_run[run_unit_id]
            effective_records.append(
                _effective_record(
                    run_unit_id,
                    transcript.transcript_sha256,
                    ScoringResultSource.MANUAL_EDIT,
                    edit.edit_sha256,
                    edit.metrics,
                    edit.edited_at,
                )
            )
            continue
        if run_unit_id in bundle_by_run:
            bundle = bundle_by_run[run_unit_id]
            effective_records.append(
                _effective_record(
                    run_unit_id,
                    transcript.transcript_sha256,
                    ScoringResultSource.AUTOMATED,
                    bundle.bundle_sha256,
                    bundle.metrics,
                    bundle.completed_at,
                )
            )
            continue
        if run_unit_id in resolution_by_run:
            resolution = resolution_by_run[run_unit_id]
            effective_records.append(
                _effective_record(
                    run_unit_id,
                    transcript.transcript_sha256,
                    ScoringResultSource.MANUAL_RESOLUTION,
                    resolution.resolution_sha256,
                    resolution.metrics,
                    resolution.resolved_at,
                )
            )
            continue
        raise ValueError(f"completed transcript has no effective scoring source: {run_unit_id}")
    write_models_jsonl_atomic(args.effective_scores_output, effective_records)
    print(
        f"Wrote {len(edits)} source-linked manual edits to {args.edits_output} and "
        f"{len(resolutions)} terminal resolutions to {args.resolutions_output}; "
        f"materialized {len(effective_records)} effective scores to {args.effective_scores_output}"
    )


if __name__ == "__main__":
    main()
