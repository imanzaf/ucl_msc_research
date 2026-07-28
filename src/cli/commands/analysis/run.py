"""Run gated primary and secondary analyses for the three separate scores."""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from src.analysis.bootstrap import stratified_scenario_bootstrap
from src.analysis.estimands import CONFIRMATORY_NAMES, PRIMARY_OUTCOME, SECONDARY_SCORE_OUTCOMES, rows_to_frame
from src.analysis.outcomes import apply_validation_disposition
from src.analysis.provenance import analysis_code_sha256
from src.analysis.r_models import run_r_robustness_models
from src.analysis.sign_flip import confirmatory_sign_flip_tests
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest, ExperimentManifest, FreezeStatus, PreregistrationManifest, ProtocolDeviationManifest
from src.data_models.scenarios import ScenarioStage
from src.data_models.scoring import (
    AnalysisEngine,
    AnalysisInputRow,
    AnalysisMissingnessReport,
    AnalysisSummary,
    EvaluationCheckpoint,
    FactAnalysisInputRow,
    ScoringValidationReport,
    ValidationDispositionManifest,
)
from src.experiments.assets import CONFIRMATORY_ANALYSIS_ID, SECONDARY_ANALYSIS_ID, generate_paper_assets
from src.experiments.layout import validate_experiment_path
from src.paths import REPO_ROOT
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def parse_args() -> argparse.Namespace:
    """Parse frozen inputs and separate primary/secondary output paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-input", type=Path, required=True)
    parser.add_argument("--fact-analysis-input", type=Path, required=True)
    parser.add_argument("--human-reference-analysis-input", type=Path, required=True)
    parser.add_argument("--manual-analysis-input", type=Path)
    parser.add_argument("--missingness-report", type=Path, required=True)
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--preregistration-manifest", type=Path, required=True)
    parser.add_argument("--annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--scoring-validation-report", type=Path, required=True)
    parser.add_argument("--validation-disposition-manifest", type=Path, required=True)
    parser.add_argument("--analysis-plan", type=Path, required=True)
    parser.add_argument("--protocol-deviations", type=Path, required=True)
    parser.add_argument("--confirmatory-summary", type=Path, required=True)
    parser.add_argument("--secondary-summary", type=Path, required=True)
    parser.add_argument("--r-input-csv", type=Path, required=True)
    parser.add_argument("--r-output-summary", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--draws", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def _validate_analysis_rows(
    rows: List[AnalysisInputRow],
    missingness: AnalysisMissingnessReport,
    analysis_input: Path,
) -> None:
    """Require three checkpoint rows per completed unit and bind missingness."""
    validate_model_self_hash(missingness, "report_sha256")
    if missingness.analysis_input_sha256 != file_sha256(analysis_input):
        raise ValueError("missingness report does not bind the exact analysis input")
    if len(rows) != missingness.analysis_row_count:
        raise ValueError("analysis rows disagree with the missingness report")
    keys = {(row.run_unit_id, row.metrics.checkpoint) for row in rows}
    if len(keys) != len(rows):
        raise ValueError("analysis input contains a duplicate run-unit/checkpoint row")
    run_ids = {row.run_unit_id for row in rows}
    if len(run_ids) != missingness.completed_run_count:
        raise ValueError("scored run-unit count disagrees with the missingness report")
    if any({row.metrics.checkpoint for row in rows if row.run_unit_id == run_id} != set(EvaluationCheckpoint) for run_id in run_ids):
        raise ValueError("every analysis run unit requires initial, follow-up, and cumulative rows")
    expected_scenarios = {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 3)}
    if {row.scenario_id for row in rows} != expected_scenarios:
        raise ValueError("confirmatory analysis requires all 20 evaluation scenarios")


def _validate_fact_analysis_rows(
    rows: List[FactAnalysisInputRow],
    missingness: AnalysisMissingnessReport,
    fact_analysis_input: Path,
) -> None:
    """Require four binary material-fact rows at every checkpoint."""
    if missingness.fact_analysis_input_sha256 != file_sha256(fact_analysis_input):
        raise ValueError("missingness report does not bind the exact fact-level input")
    if len(rows) != missingness.completed_run_count * 4 * len(EvaluationCheckpoint):
        raise ValueError("fact input requires four material facts at all three checkpoints")
    keys = {(row.run_unit_id, row.fact_id, row.checkpoint) for row in rows}
    if len(keys) != len(rows):
        raise ValueError("fact input contains duplicate fact/checkpoint rows")


def _validate_manual_rows(
    rows: List[AnalysisInputRow],
    automated_rows: List[AnalysisInputRow],
) -> None:
    """Require manual scoring to cover the exact automated row set once."""
    keys = {(row.run_unit_id, row.metrics.checkpoint) for row in rows}
    automated_keys = {(row.run_unit_id, row.metrics.checkpoint) for row in automated_rows}
    if len(keys) != len(rows) or keys != automated_keys:
        raise ValueError("manual input must cover every automated run/checkpoint exactly once")


def _validate_analysis_gates(
    experiment: ExperimentManifest,
    preregistration: PreregistrationManifest,
    annotation_sample: AnnotationSampleManifest,
    scoring_report: ScoringValidationReport,
    disposition: ValidationDispositionManifest,
    analysis_plan: Path,
    protocol_deviations: ProtocolDeviationManifest,
) -> None:
    """Refuse inference unless frozen hashes and blinded validation decisions align."""
    for manifest, hash_field in [
        (experiment, "manifest_sha256"),
        (preregistration, "manifest_sha256"),
        (annotation_sample, "manifest_sha256"),
        (scoring_report, "report_sha256"),
        (disposition, "manifest_sha256"),
        (protocol_deviations, "manifest_sha256"),
    ]:
        validate_model_self_hash(manifest, hash_field)
    if experiment.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("analysis requires a frozen experiment manifest")
    if preregistration.experiment_manifest_sha256 != experiment.manifest_sha256:
        raise ValueError("preregistration does not bind the supplied experiment")
    if preregistration.analysis_plan_sha256 != file_sha256(analysis_plan):
        raise ValueError("preregistration does not bind the supplied analysis plan")
    if protocol_deviations.preregistration_manifest_sha256 != preregistration.manifest_sha256:
        raise ValueError("protocol-deviation register does not bind the preregistration")
    if protocol_deviations.experiment_manifest_sha256 != experiment.manifest_sha256:
        raise ValueError("protocol-deviation register does not bind the experiment")
    if annotation_sample.sample_stage != ScenarioStage.EVALUATION:
        raise ValueError("analysis requires the frozen evaluation annotation sample")
    if scoring_report.validation_sample_manifest_sha256 != annotation_sample.manifest_sha256:
        raise ValueError("scoring validation does not bind the annotation sample")
    if annotation_sample.scoring_execution_manifest_sha256 != experiment.scoring_execution_manifest_sha256:
        raise ValueError("annotations do not bind the experiment scoring package")
    if disposition.validation_report_sha256 != scoring_report.report_sha256:
        raise ValueError("validation disposition does not bind the scoring report")
    if set(disposition.failed_constructs) != set(scoring_report.failed_constructs):
        raise ValueError("validation disposition does not cover the failed constructs")
    if disposition.confirmatory_inference_withheld:
        raise PermissionError("validation disposition withholds primary selective-communication inference")
    head_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if preregistration.analysis_commit != head_commit:
        raise ValueError("current analysis commit differs from the preregistered commit")
    if preregistration.analysis_code_sha256 != analysis_code_sha256(REPO_ROOT):
        raise ValueError("current analysis source differs from the preregistered bundle")


def _summary(
    analysis_id: str,
    method: str,
    estimates: Dict[str, float],
    intervals: Dict[str, Tuple[float, float]],
    raw_p_values: Dict[str, float],
    adjusted_p_values: Dict[str, float],
    source_sha256: str,
) -> AnalysisSummary:
    """Build one strict analysis summary."""
    return AnalysisSummary(
        schema_version="2.0.0",
        analysis_id=analysis_id,
        engine=AnalysisEngine.PYTHON,
        method=method,
        estimands={name: Decimal(str(value)) for name, value in estimates.items()},
        confidence_intervals={name: [Decimal(str(value)) for value in interval] for name, interval in intervals.items()},
        raw_p_values={name: Decimal(str(value)) for name, value in raw_p_values.items()},
        adjusted_p_values={name: Decimal(str(value)) for name, value in adjusted_p_values.items()},
        converged=True,
        convergence_messages=[],
        source_data_sha256=source_sha256,
        generated_at=datetime.now(timezone.utc),
    )


def _secondary_bootstraps(
    frames: Dict[EvaluationCheckpoint, pd.DataFrame],
    disposition: ValidationDispositionManifest,
    draws: int,
    seed: int,
) -> Tuple[Dict[str, float], Dict[str, Tuple[float, float]]]:
    """Estimate secondary score/checkpoint effects and intervals without p-values."""
    requests: List[Tuple[EvaluationCheckpoint, str]] = [(EvaluationCheckpoint.INITIAL, outcome) for outcome in SECONDARY_SCORE_OUTCOMES]
    requests.extend(
        (checkpoint, outcome)
        for checkpoint in (
            EvaluationCheckpoint.FOLLOW_UP,
            EvaluationCheckpoint.CUMULATIVE,
        )
        for outcome in (
            PRIMARY_OUTCOME,
            *SECONDARY_SCORE_OUTCOMES,
        )
    )
    estimates: Dict[str, float] = {}
    intervals: Dict[str, Tuple[float, float]] = {}
    request_index = 0
    for checkpoint, outcome in requests:
        if outcome == "presentation_style_score" and disposition.presentation_result_withheld:
            continue
        if outcome == "factual_inaccuracy_score" and disposition.factual_inaccuracy_result_withheld:
            continue
        points, bounds, _ = stratified_scenario_bootstrap(
            frames[checkpoint],
            outcome=outcome,
            draws=draws,
            seed=seed + request_index,
        )
        request_index += 1
        for hypothesis in sorted(CONFIRMATORY_NAMES):
            name = f"{checkpoint.value}:{outcome}:{hypothesis}"
            estimates[name] = points[hypothesis]
            intervals[name] = bounds[hypothesis]
    return estimates, intervals


def main() -> None:
    """Run the sole primary tests and interval-only secondary analyses."""
    args = parse_args()
    if args.draws != 10_000:
        raise ValueError("scenario bootstrap is frozen at exactly 10,000 draws")
    for result_path in [
        args.analysis_input,
        args.fact_analysis_input,
        args.human_reference_analysis_input,
        args.missingness_report,
        args.scoring_validation_report,
        args.validation_disposition_manifest,
        args.confirmatory_summary,
        args.secondary_summary,
        args.r_input_csv,
        args.r_output_summary,
    ]:
        validate_experiment_path(result_path, REPO_ROOT, "results_tree")
    validate_experiment_path(args.assets_dir, REPO_ROOT, "assets_dir")

    experiment = read_model_json(args.experiment_manifest, ExperimentManifest)
    preregistration = read_model_json(
        args.preregistration_manifest,
        PreregistrationManifest,
    )
    annotation_sample = read_model_json(
        args.annotation_sample_manifest,
        AnnotationSampleManifest,
    )
    scoring_report = read_model_json(
        args.scoring_validation_report,
        ScoringValidationReport,
    )
    disposition = read_model_json(
        args.validation_disposition_manifest,
        ValidationDispositionManifest,
    )
    protocol_deviations = read_model_json(
        args.protocol_deviations,
        ProtocolDeviationManifest,
    )
    missingness = read_model_json(
        args.missingness_report,
        AnalysisMissingnessReport,
    )
    _validate_analysis_gates(
        experiment,
        preregistration,
        annotation_sample,
        scoring_report,
        disposition,
        args.analysis_plan,
        protocol_deviations,
    )

    rows = read_model_jsonl(args.analysis_input, AnalysisInputRow)
    _validate_analysis_rows(rows, missingness, args.analysis_input)
    fact_rows = read_model_jsonl(args.fact_analysis_input, FactAnalysisInputRow)
    _validate_fact_analysis_rows(fact_rows, missingness, args.fact_analysis_input)
    manual_frames: Dict[EvaluationCheckpoint, pd.DataFrame | None] = {checkpoint: None for checkpoint in EvaluationCheckpoint}
    manual_source_sha256 = None
    if args.manual_analysis_input is not None:
        validate_experiment_path(
            args.manual_analysis_input,
            REPO_ROOT,
            "results_tree",
        )
        manual_rows = read_model_jsonl(
            args.manual_analysis_input,
            AnalysisInputRow,
        )
        _validate_manual_rows(manual_rows, rows)
        manual_frames = {checkpoint: rows_to_frame(manual_rows, checkpoint) for checkpoint in EvaluationCheckpoint}
        manual_source_sha256 = file_sha256(args.manual_analysis_input)

    frames = {
        checkpoint: apply_validation_disposition(
            rows_to_frame(rows, checkpoint),
            disposition,
            manual_frames[checkpoint],
        )
        for checkpoint in EvaluationCheckpoint
    }
    human_rows = read_model_jsonl(
        args.human_reference_analysis_input,
        AnalysisInputRow,
    )
    human_keys = {(row.run_unit_id, row.metrics.checkpoint) for row in human_rows}
    if len(human_keys) != len(human_rows) or len(human_rows) != len(annotation_sample.conversation_ids) * len(EvaluationCheckpoint):
        raise ValueError("human reference must contain all three checkpoints for the frozen sample")
    if not {row.run_unit_id for row in human_rows}.issubset({row.run_unit_id for row in rows}):
        raise ValueError("human reference contains a run outside the automated input")

    source_sha256 = artifact_sha256(
        {
            "automated_analysis_input": file_sha256(args.analysis_input),
            "manual_analysis_input": manual_source_sha256,
            "validation_disposition": disposition.manifest_sha256,
        }
    )
    confirmatory_estimates, confirmatory_intervals, _ = stratified_scenario_bootstrap(
        frames[EvaluationCheckpoint.INITIAL],
        outcome=PRIMARY_OUTCOME,
        draws=args.draws,
        seed=args.seed,
    )
    p_values, adjusted = confirmatory_sign_flip_tests(
        frames[EvaluationCheckpoint.INITIAL],
        permutations=100_000,
        seed=args.seed,
    )
    confirmatory = _summary(
        CONFIRMATORY_ANALYSIS_ID,
        "initial_selective_scenario_paired_sign_flip_100000_holm_and_bootstrap_10000",
        confirmatory_estimates,
        confirmatory_intervals,
        p_values,
        adjusted,
        source_sha256,
    )
    secondary_estimates, secondary_intervals = _secondary_bootstraps(
        frames,
        disposition,
        args.draws,
        args.seed + 100,
    )
    secondary = _summary(
        SECONDARY_ANALYSIS_ID,
        "paired_effects_with_scenario_bootstrap_10000_no_confirmatory_p_values",
        secondary_estimates,
        secondary_intervals,
        {},
        {},
        source_sha256,
    )
    write_model_json_atomic(args.confirmatory_summary, confirmatory)
    write_model_json_atomic(args.secondary_summary, secondary)

    initial_fact_records = [
        {
            "run_unit_id": row.run_unit_id,
            "scenario_id": row.scenario_id,
            "use_case_id": row.use_case_id,
            "fact_id": row.fact_id,
            "pair_id": row.pair_id,
            "fact_option": row.fact_option,
            "fact_polarity": row.fact_polarity,
            "decision_alignment": row.decision_alignment,
            "model_id": row.model_id,
            "word_budget": row.word_budget,
            "expressed_concern": row.expressed_concern,
            "fact_present": int(row.fact_present),
        }
        for row in fact_rows
        if row.checkpoint == EvaluationCheckpoint.INITIAL
    ]
    fact_frame = pd.DataFrame.from_records(initial_fact_records)
    conversation_scores = frames[EvaluationCheckpoint.INITIAL][["run_unit_id", PRIMARY_OUTCOME]]
    r_frame = fact_frame.merge(
        conversation_scores,
        on="run_unit_id",
        how="left",
        validate="many_to_one",
    )
    args.r_input_csv.parent.mkdir(parents=True, exist_ok=True)
    r_frame.to_csv(args.r_input_csv, index=False)
    run_r_robustness_models(
        args.r_input_csv,
        args.r_output_summary,
        file_sha256(args.r_input_csv),
        REPO_ROOT / "analysis/r/run_mixed_models.R",
        REPO_ROOT / "analysis/r",
    )
    generate_paper_assets(
        args.assets_dir,
        confirmatory_estimates,
        confirmatory_intervals,
        adjusted,
        secondary_estimates,
        secondary_intervals,
    )
    print("Wrote the selective-communication confirmatory panel and interval-only secondary panel")


if __name__ == "__main__":
    main()
