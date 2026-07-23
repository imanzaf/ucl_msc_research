"""Join terminal execution and resolved scoring into analysis rows plus missingness."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.common import artifact_sha256, file_sha256, utc_now, validate_model_self_hash
from src.data_models.experiments import EXPECTED_CONVERSATION_COUNT, ConversationTranscript, RunOutcomeStatus
from src.data_models.manifests import AcceptedScenarioManifest, ExperimentManifest, FreezeStatus, ScoringExecutionManifest
from src.data_models.scenarios import DecisionOption, FactPolarity, decision_alignment
from src.data_models.scoring import (
    AnalysisInputRow,
    AnalysisMissingnessReport,
    ConversationMetrics,
    DisclosureState,
    FactAnalysisInputRow,
    ManualScoringResolution,
    MissingRunRecord,
    ScoredConversationBundle,
)
from src.data_models.study import EXPERIMENT_DIMENSIONS, ExperimentName, cue_template_id
from src.experiments.io import load_accepted_evaluation_scenarios
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import validate_complete_run_plan, validate_exploratory_run_plan
from src.paths import REPO_ROOT
from src.prompts.scoring_contracts import scoring_contract_sha256
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic


def _validate_scoring_provenance(
    scoring_manifest_sha256: str,
    scoring_contract_digest: str,
    artifact_manifest_sha256: str,
    artifact_contract_sha256: str,
) -> None:
    """Require one scoring artifact to bind the frozen execution contract."""
    if artifact_manifest_sha256 != scoring_manifest_sha256:
        raise ValueError("scoring artifact was produced under a different scoring-execution manifest")
    if artifact_contract_sha256 != scoring_contract_digest:
        raise ValueError("scoring artifact was produced under different condition-blind scoring contracts")


def build_analysis_rows(
    transcripts: List[ConversationTranscript],
    bundles: List[ScoredConversationBundle],
    manual_resolutions: List[ManualScoringResolution],
    scoring_manifest_sha256: str,
    scoring_contract_digest: str,
    experiment_name: ExperimentName = ExperimentName.RISK_COMM_V1,
    expected_conversation_count: int = EXPECTED_CONVERSATION_COUNT,
) -> Tuple[List[AnalysisInputRow], List[MissingRunRecord]]:
    """Join all completed outcomes and preserve exhausted provider calls as missing."""
    if len(transcripts) != expected_conversation_count:
        raise ValueError(
            f"{experiment_name.value} analysis input requires the complete " f"{expected_conversation_count}-unit terminal transcript ledger"
        )
    transcript_by_id: Dict[str, ConversationTranscript] = {}
    for transcript in transcripts:
        run_unit_id = transcript.run_unit.run_unit_id
        if run_unit_id in transcript_by_id:
            raise ValueError(f"duplicate transcript run-unit id: {run_unit_id}")
        transcript_by_id[run_unit_id] = transcript
    run_units = [transcript.run_unit for transcript in transcripts]
    if experiment_name == ExperimentName.RISK_COMM_V1:
        validate_complete_run_plan(run_units)
    else:
        validate_exploratory_run_plan(
            run_units,
            expected_conversation_count,
            expected_cells=EXPERIMENT_DIMENSIONS[experiment_name].cell_count,
        )

    metric_by_id: Dict[str, Tuple[List[ConversationMetrics], str, str]] = {}
    for bundle in bundles:
        if bundle.run_unit_id in metric_by_id:
            raise ValueError(f"duplicate scored run-unit id: {bundle.run_unit_id}")
        _validate_scoring_provenance(
            scoring_manifest_sha256,
            scoring_contract_digest,
            bundle.scoring_execution_manifest_sha256,
            bundle.scoring_contract_sha256,
        )
        metric_by_id[bundle.run_unit_id] = (bundle.metrics, bundle.bundle_sha256, bundle.transcript_sha256)
    for resolution in manual_resolutions:
        if resolution.run_unit_id in metric_by_id:
            raise ValueError(f"run unit has both automated and manual scoring: {resolution.run_unit_id}")
        _validate_scoring_provenance(
            scoring_manifest_sha256,
            scoring_contract_digest,
            resolution.scoring_execution_manifest_sha256,
            resolution.scoring_contract_sha256,
        )
        metric_by_id[resolution.run_unit_id] = (
            resolution.metrics,
            resolution.resolution_sha256,
            resolution.transcript_sha256,
        )

    completed_ids = {run_unit_id for run_unit_id, transcript in transcript_by_id.items() if transcript.outcome_status == RunOutcomeStatus.COMPLETED}
    if set(metric_by_id) != completed_ids:
        missing_scores = sorted(completed_ids - set(metric_by_id))
        invalid_scores = sorted(set(metric_by_id) - completed_ids)
        raise ValueError(
            "scoring must resolve every completed transcript and no failed transcript; "
            f"unscored_completed={missing_scores[:3]}, scored_failed={invalid_scores[:3]}"
        )

    rows: List[AnalysisInputRow] = []
    for run_unit_id in sorted(completed_ids):
        transcript = transcript_by_id[run_unit_id]
        metrics, scoring_result_sha256, bound_transcript_sha256 = metric_by_id[run_unit_id]
        if bound_transcript_sha256 != transcript.transcript_sha256:
            raise ValueError(f"scoring artifact binds a different transcript: {run_unit_id}")
        run_unit = transcript.run_unit
        for metric in sorted(metrics, key=lambda item: item.checkpoint.value):
            rows.append(
                AnalysisInputRow(
                    schema_version="2.0.0",
                    run_unit_id=run_unit_id,
                    scenario_id=run_unit.scenario_id,
                    use_case_id=run_unit.use_case_id,
                    model_id=run_unit.model_id,
                    cue_template_id=cue_template_id(run_unit.scenario_id),
                    word_budget=run_unit.cell.word_budget,
                    expressed_concern=run_unit.cell.expressed_concern,
                    integrity=run_unit.cell.integrity,
                    metrics=metric,
                    transcript_sha256=transcript.transcript_sha256,
                    scoring_result_sha256=scoring_result_sha256,
                )
            )
    missing_runs: List[MissingRunRecord] = []
    for transcript in sorted(transcripts, key=lambda item: item.run_unit.run_unit_id):
        if transcript.outcome_status == RunOutcomeStatus.COMPLETED:
            continue
        if transcript.failure_reason is None:
            raise ValueError("a non-completed transcript requires a typed failure reason")
        missing_runs.append(
            MissingRunRecord(
                run_unit_id=transcript.run_unit.run_unit_id,
                scenario_id=transcript.run_unit.scenario_id,
                use_case_id=transcript.run_unit.use_case_id,
                model_id=transcript.run_unit.model_id,
                cell_id=transcript.run_unit.cell.cell_id,
                failure_reason=transcript.failure_reason,
                transcript_sha256=transcript.transcript_sha256,
                terminal_attempt_count=len(transcript.initial_attempts) + len(transcript.follow_up_attempts),
            )
        )
    return rows, missing_runs


def build_fact_analysis_rows(
    transcripts: List[ConversationTranscript],
    bundles: List[ScoredConversationBundle],
    manual_resolutions: List[ManualScoringResolution],
    fact_metadata_by_scenario: Dict[str, Dict[str, Tuple[DecisionOption, FactPolarity, str]]],
) -> List[FactAnalysisInputRow]:
    """Join material-fact judgments to immutable conditions for ordinal R robustness."""
    result_by_id = {bundle.run_unit_id: bundle.fact_result for bundle in bundles}
    result_by_id.update({resolution.run_unit_id: resolution.fact_result for resolution in manual_resolutions})
    hash_by_id = {bundle.run_unit_id: bundle.bundle_sha256 for bundle in bundles}
    hash_by_id.update({resolution.run_unit_id: resolution.resolution_sha256 for resolution in manual_resolutions})
    transcript_by_id = {
        transcript.run_unit.run_unit_id: transcript for transcript in transcripts if transcript.outcome_status == RunOutcomeStatus.COMPLETED
    }
    disclosure_ordinal = {DisclosureState.OMITTED: 0, DisclosureState.PARTIAL: 1, DisclosureState.FULL: 2}
    rows: List[FactAnalysisInputRow] = []
    for run_unit_id in sorted(result_by_id):
        transcript = transcript_by_id[run_unit_id]
        run_unit = transcript.run_unit
        metadata_by_fact = fact_metadata_by_scenario[run_unit.scenario_id]
        for judgment in result_by_id[run_unit_id].judgments:
            if judgment.fact_id not in metadata_by_fact:
                continue
            fact_option, fact_polarity, pair_id = metadata_by_fact[judgment.fact_id]
            rows.append(
                FactAnalysisInputRow(
                    schema_version="2.0.0",
                    run_unit_id=run_unit_id,
                    scenario_id=run_unit.scenario_id,
                    use_case_id=run_unit.use_case_id,
                    fact_id=judgment.fact_id,
                    pair_id=pair_id,
                    fact_option=fact_option,
                    fact_polarity=fact_polarity,
                    decision_alignment=decision_alignment(fact_option, fact_polarity),
                    checkpoint=judgment.checkpoint,
                    disclosure_ordinal=disclosure_ordinal[judgment.disclosure],
                    model_id=run_unit.model_id,
                    cue_template_id=cue_template_id(run_unit.scenario_id),
                    word_budget=run_unit.cell.word_budget,
                    expressed_concern=run_unit.cell.expressed_concern,
                    integrity=run_unit.cell.integrity,
                    transcript_sha256=transcript.transcript_sha256,
                    scoring_result_sha256=hash_by_id[run_unit_id],
                )
            )
    if len(rows) != len(transcript_by_id) * 4 * 2:
        raise ValueError("fact-level analysis requires four material facts at both checkpoints per completed conversation")
    return rows


def main() -> None:
    """Write one experiment's analyzable subset and self-hashed missingness report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--scored-bundles", type=Path, required=True)
    parser.add_argument("--manual-resolutions", type=Path, required=True)
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--scoring-execution-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fact-analysis-output", type=Path, required=True)
    parser.add_argument("--missingness-report", type=Path, required=True)
    args = parser.parse_args()
    experiment_manifest = read_model_json(args.experiment_manifest, ExperimentManifest)
    experiment_name = experiment_manifest.experiment_name
    expected_count = EXPERIMENT_DIMENSIONS[experiment_name].conversation_count
    validate_experiment_path(args.transcripts, REPO_ROOT, "result", experiment_name.value)
    for output_path in [args.output, args.fact_analysis_output, args.missingness_report]:
        validate_experiment_path(output_path, REPO_ROOT, "results_tree", experiment_name.value)
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    scoring_manifest = read_model_json(args.scoring_execution_manifest, ScoringExecutionManifest)
    validate_model_self_hash(experiment_manifest, "manifest_sha256")
    validate_model_self_hash(accepted_manifest, "manifest_sha256")
    validate_model_self_hash(scoring_manifest, "manifest_sha256")
    if experiment_manifest.freeze_status != FreezeStatus.FROZEN or scoring_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("analysis joining requires frozen experiment and scoring-execution manifests")
    if experiment_manifest.scoring_execution_manifest_sha256 != scoring_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the scoring-execution manifest")
    if experiment_manifest.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("experiment manifest does not bind the supplied accepted scenarios")
    if scoring_manifest.scoring_contract_sha256 != scoring_contract_sha256():
        raise ValueError("scoring-execution manifest does not bind the active scoring contracts")
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    bundles = read_model_jsonl(args.scored_bundles, ScoredConversationBundle)
    manual_resolutions = read_model_jsonl(args.manual_resolutions, ManualScoringResolution)
    rows, missing_runs = build_analysis_rows(
        transcripts,
        bundles,
        manual_resolutions,
        scoring_manifest.manifest_sha256,
        scoring_manifest.scoring_contract_sha256,
        experiment_name,
        expected_count,
    )
    write_models_jsonl_atomic(args.output, rows)
    scenarios = load_accepted_evaluation_scenarios(args.accepted_root, accepted_manifest)
    fact_rows = build_fact_analysis_rows(
        transcripts,
        bundles,
        manual_resolutions,
        {
            scenario.scenario_id: {fact.fact_id: (fact.option, fact.polarity, fact.pair_id) for fact in scenario.material_facts}
            for scenario in scenarios
        },
    )
    write_models_jsonl_atomic(args.fact_analysis_output, fact_rows)
    payload = {
        "schema_version": "2.0.0",
        "expected_run_count": expected_count,
        "completed_run_count": len({row.run_unit_id for row in rows}),
        "failed_run_count": len(missing_runs),
        "manually_resolved_count": len(manual_resolutions),
        "automated_scored_count": len(bundles),
        "analysis_row_count": len(rows),
        "missing_runs": missing_runs,
        "transcript_ledger_sha256": file_sha256(args.transcripts),
        "analysis_input_sha256": file_sha256(args.output),
        "fact_analysis_input_sha256": file_sha256(args.fact_analysis_output),
        "generated_at": utc_now(),
    }
    report = AnalysisMissingnessReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.missingness_report, report)
    print(f"Wrote {len(rows)} analysis rows; preserved {len(missing_runs)} exhausted provider calls as missing")


if __name__ == "__main__":
    main()
