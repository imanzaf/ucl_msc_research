"""Select balanced calibration/evaluation annotations and publish blind local inputs."""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.common import artifact_sha256, file_sha256, sha256_bytes, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, AnnotationSampleManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import AcceptedScenario, ScenarioStage
from src.data_models.scoring import AnnotationScoringPackage
from src.experiments.io import load_all_accepted_scenarios
from src.experiments.scenario_runner import validate_calibration_run_plan, validate_complete_run_plan
from src.experiments.scoring_pipeline import build_condition_blind_inputs
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def _group_seed(seed: int, key: str) -> int:
    """Derive one deterministic selection seed per declared sampling stratum."""
    return int(sha256_bytes(f"{seed}:{key}".encode("utf-8"))[:16], 16)


def _select_calibration(
    transcripts: List[ConversationTranscript],
    seed: int,
) -> Tuple[List[ConversationTranscript], Dict[str, Decimal]]:
    """Sample two available models per C1/primary-cell stratum using the recorded seed."""
    selected: List[ConversationTranscript] = []
    grouped: Dict[Tuple[str, str], List[ConversationTranscript]] = {}
    for transcript in transcripts:
        grouped.setdefault((transcript.run_unit.scenario_id, transcript.run_unit.cell.cell_id), []).append(transcript)
    probabilities: Dict[str, Decimal] = {}
    for key in sorted(grouped):
        candidates = sorted(grouped[key], key=lambda item: item.run_unit.model_id)
        if len(candidates) < 2:
            raise ValueError("each calibration scenario/cell stratum requires at least two completed model conversations")
        stratum = f"calibration:{key[0]}:{key[1]}"
        random.Random(_group_seed(seed, stratum)).shuffle(candidates)
        selected.extend(candidates[:2])
        probabilities[stratum] = Decimal(2) / Decimal(len(candidates))
    if len(selected) != 80:
        raise ValueError("calibration annotation selection must contain exactly 80 conversations")
    return selected, probabilities


def _select_evaluation(
    transcripts: List[ConversationTranscript],
    seed: int,
) -> Tuple[List[ConversationTranscript], Dict[str, Decimal]]:
    """Sample one conversation in each scenario × budget × expressed-concern stratum."""
    selected: List[ConversationTranscript] = []
    by_scenario: Dict[str, List[ConversationTranscript]] = {}
    for transcript in transcripts:
        by_scenario.setdefault(transcript.run_unit.scenario_id, []).append(transcript)
    probabilities: Dict[str, Decimal] = {}
    for scenario_id in sorted(by_scenario):
        candidates = by_scenario[scenario_id]
        for word_budget in ["baseline", "concise"]:
            for expressed_concern in ["neutral", "concerned"]:
                matches = sorted(
                    [
                        item
                        for item in candidates
                        if item.run_unit.cell.concision.value == word_budget and item.run_unit.cell.expressed_concern.value == expressed_concern
                    ],
                    key=lambda item: item.run_unit.run_unit_id,
                )
                if not matches:
                    raise ValueError("evaluation annotation stratum has no completed conversation")
                stratum = f"evaluation:{scenario_id}:{word_budget}:{expressed_concern}"
                selected.append(random.Random(_group_seed(seed, stratum)).choice(matches))
                probabilities[stratum] = Decimal(1) / Decimal(len(matches))
    if len(selected) != 160:
        raise ValueError("evaluation annotation selection must contain exactly 160 conversations")
    return selected, probabilities


def _strata_summary(transcripts: List[ConversationTranscript]) -> Dict[str, int]:
    """Count the locked sample across scenario, model, and treatment strata."""
    summary: Dict[str, int] = {"total": len(transcripts)}
    for transcript in transcripts:
        unit = transcript.run_unit
        for key in [
            f"use_case:{unit.use_case_id}",
            f"model:{unit.model_id}",
            f"cell:{unit.cell.cell_id}",
        ]:
            summary[key] = summary.get(key, 0) + 1
    return summary


def main() -> None:
    """Validate a complete run, freeze its sample, and write only condition-blind inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=[stage.value for stage in ScenarioStage], required=True)
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--scoring-input-root", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    stage = ScenarioStage(args.stage)
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("annotation sampling requires the frozen scoring package and fact-order seed")
    scenarios: Dict[str, AcceptedScenario] = {
        scenario.scenario_id: scenario for scenario in load_all_accepted_scenarios(args.accepted_root, accepted_manifest)
    }
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    if stage == ScenarioStage.CALIBRATION:
        validate_calibration_run_plan([transcript.run_unit for transcript in transcripts])
        selected, probabilities = _select_calibration(
            [transcript for transcript in transcripts if transcript.outcome_status == RunOutcomeStatus.COMPLETED],
            args.seed,
        )
    else:
        validate_complete_run_plan([transcript.run_unit for transcript in transcripts])
        selected, probabilities = _select_evaluation(
            [transcript for transcript in transcripts if transcript.outcome_status == RunOutcomeStatus.COMPLETED],
            args.seed,
        )
    blind_ids: List[str] = []
    for transcript in selected:
        run_unit_id = transcript.run_unit.run_unit_id
        fact_seed = int(sha256_bytes(f"{scoring_manifest.fact_order_seed}:{run_unit_id}".encode("utf-8"))[:16], 16)
        scoring_inputs = build_condition_blind_inputs(
            transcript,
            scenarios[transcript.run_unit.scenario_id],
            fact_seed,
        )
        blind_id = next(iter(scoring_inputs.values())).blind_conversation_id
        package = AnnotationScoringPackage(
            schema_version="3.0.0",
            blind_conversation_id=blind_id,
            scoring_inputs=scoring_inputs,
        )
        write_model_json_atomic(
            args.scoring_input_root / f"{blind_id}.json",
            package,
        )
        blind_ids.append(blind_id)
    payload = {
        "schema_version": "2.0.0",
        "sample_id": f"risk_comm_{stage.value}_annotation_v1",
        "sample_stage": stage,
        "random_seed": args.seed,
        "conversation_ids": sorted(blind_ids),
        "strata_summary": _strata_summary(selected),
        "selection_probabilities": probabilities,
        "scoring_execution_manifest_sha256": scoring_manifest.manifest_sha256,
        "source_transcripts_sha256": file_sha256(args.transcripts),
        "frozen_at": datetime.now(timezone.utc),
    }
    manifest = AnnotationSampleManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output_manifest, manifest)
    print(f"Wrote {len(blind_ids)} blind {stage.value} inputs and their frozen sample manifest")


if __name__ == "__main__":
    main()
