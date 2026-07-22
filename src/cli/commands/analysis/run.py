"""Run gated Python inference, sensitivities, equivalence, R robustness, and assets."""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.analysis.bootstrap import stratified_scenario_bootstrap
from src.analysis.equivalence import two_one_sided_test
from src.analysis.estimands import rows_to_frame, scenario_level_contrasts
from src.analysis.multiplicity import holm_adjust
from src.analysis.provenance import analysis_code_sha256
from src.analysis.r_models import run_r_robustness_models
from src.analysis.sensitivities import estimate_sensitivities_with_messages
from src.data_models.common import file_sha256, validate_model_self_hash
from src.data_models.manifests import (
    AnnotationSampleManifest,
    ExperimentManifest,
    FreezeStatus,
    PreregistrationManifest,
    ProtocolDeviationManifest,
    SmallestEffectManifest,
)
from src.data_models.scenarios import ScenarioStage
from src.data_models.scoring import (
    AnalysisEngine,
    AnalysisInputRow,
    AnalysisMissingnessReport,
    AnalysisSummary,
    EvaluationCheckpoint,
    FactAnalysisInputRow,
    ScoringValidationReport,
)
from src.experiments.assets import generate_paper_assets
from src.experiments.layout import validate_experiment_path
from src.paths import REPO_ROOT
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic

CONFIRMATORY_NAMES = {"H1", "H2a", "H2b", "M1", "M2"}


def parse_args() -> argparse.Namespace:
    """Parse frozen analysis inputs, gate records, and output paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-input", type=Path, required=True)
    parser.add_argument("--fact-analysis-input", type=Path, required=True)
    parser.add_argument("--human-reference-analysis-input", type=Path, required=True)
    parser.add_argument("--missingness-report", type=Path, required=True)
    parser.add_argument("--experiment-manifest", type=Path, required=True)
    parser.add_argument("--preregistration-manifest", type=Path, required=True)
    parser.add_argument("--annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--scoring-validation-report", type=Path, required=True)
    parser.add_argument("--smallest-effect-manifest", type=Path, required=True)
    parser.add_argument("--analysis-plan", type=Path, required=True)
    parser.add_argument("--protocol-deviations", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--sensitivity-summary", type=Path, required=True)
    parser.add_argument("--equivalence-summary", type=Path, required=True)
    parser.add_argument("--r-input-csv", type=Path, required=True)
    parser.add_argument("--r-output-summary", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--draws", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def _validate_analysis_rows(rows: List[AnalysisInputRow], missingness: AnalysisMissingnessReport, analysis_input: Path) -> None:
    """Require two checkpoint rows per completed unit and bind all terminal missingness."""
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
        raise ValueError("every analysis run unit requires initial and cumulative checkpoints")
    if {row.scenario_id for row in rows} != {f"CF{use_case:03d}_R{replication}" for use_case in range(1, 11) for replication in range(1, 5)}:
        raise ValueError("confirmatory analysis requires analyzable observations from all 40 evaluation scenarios")


def _validate_fact_analysis_rows(
    rows: List[FactAnalysisInputRow],
    missingness: AnalysisMissingnessReport,
    fact_analysis_input: Path,
) -> None:
    """Require four material facts at two checkpoints for every completed conversation."""
    if missingness.fact_analysis_input_sha256 != file_sha256(fact_analysis_input):
        raise ValueError("missingness report does not bind the exact fact-level analysis input")
    if len(rows) != missingness.completed_run_count * 8:
        raise ValueError("fact-level input requires four material facts at both checkpoints per completed conversation")
    keys = {(row.run_unit_id, row.fact_id, row.checkpoint) for row in rows}
    if len(keys) != len(rows):
        raise ValueError("fact-level analysis input contains duplicate fact/checkpoint rows")


def _validate_analysis_gates(
    experiment: ExperimentManifest,
    preregistration: PreregistrationManifest,
    annotation_sample: AnnotationSampleManifest,
    scoring_report: ScoringValidationReport,
    smallest_effects: SmallestEffectManifest,
    analysis_plan: Path,
    protocol_deviations: ProtocolDeviationManifest,
) -> None:
    """Refuse inference unless frozen manifests, hashes, commit, and headline gates align."""
    for manifest, hash_field in [
        (experiment, "manifest_sha256"),
        (preregistration, "manifest_sha256"),
        (annotation_sample, "manifest_sha256"),
        (smallest_effects, "manifest_sha256"),
        (scoring_report, "report_sha256"),
        (protocol_deviations, "manifest_sha256"),
    ]:
        validate_model_self_hash(manifest, hash_field)
    if experiment.freeze_status != FreezeStatus.FROZEN or smallest_effects.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("analysis requires frozen experiment and smallest-effect manifests")
    if preregistration.experiment_manifest_sha256 != experiment.manifest_sha256:
        raise ValueError("preregistration does not bind the supplied experiment manifest")
    if preregistration.smallest_effects_sha256 != smallest_effects.manifest_sha256:
        raise ValueError("preregistration does not bind the smallest-effect manifest")
    if preregistration.analysis_plan_sha256 != file_sha256(analysis_plan):
        raise ValueError("preregistration does not bind the supplied analysis plan bytes")
    if protocol_deviations.preregistration_manifest_sha256 != preregistration.manifest_sha256:
        raise ValueError("protocol-deviation register does not bind the preregistration")
    if protocol_deviations.experiment_manifest_sha256 != experiment.manifest_sha256:
        raise ValueError("protocol-deviation register does not bind the experiment manifest")
    if annotation_sample.sample_stage != ScenarioStage.EVALUATION:
        raise ValueError("headline analysis requires the frozen evaluation annotation sample")
    if scoring_report.validation_sample_manifest_sha256 != annotation_sample.manifest_sha256:
        raise ValueError("scoring validation report does not bind the frozen annotation sample")
    if annotation_sample.scoring_execution_manifest_sha256 != experiment.scoring_execution_manifest_sha256:
        raise ValueError("evaluation annotations do not bind the experiment's frozen scoring package")
    required_passes = {"intra_rater_disclosure", "judge_reference_disclosure", "omission_recall", "reassurance"}
    if not scoring_report.reassurance_used_in_headline or not required_passes.issubset(scoring_report.passed_constructs):
        raise ValueError("headline analysis is blocked until disclosure, omission, and reassurance gates pass")
    head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    if preregistration.analysis_commit != head_commit:
        raise ValueError("current analysis code commit differs from the preregistered analysis commit")
    if preregistration.analysis_code_sha256 != analysis_code_sha256(REPO_ROOT):
        raise ValueError("current analysis source bytes differ from the preregistered analysis bundle")


def _summary(
    analysis_id: str,
    method: str,
    estimates: Dict[str, float],
    intervals: Dict[str, List[float]],
    raw_p_values: Dict[str, float],
    adjusted_p_values: Dict[str, float],
    source_sha256: str,
    converged: bool = True,
    convergence_messages: List[str] | None = None,
) -> AnalysisSummary:
    """Build one strict Python analysis summary."""
    return AnalysisSummary(
        schema_version="1.0.0",
        analysis_id=analysis_id,
        engine=AnalysisEngine.PYTHON,
        method=method,
        estimands={name: Decimal(str(value)) for name, value in estimates.items()},
        confidence_intervals={name: [Decimal(str(value)) for value in interval] for name, interval in intervals.items()},
        raw_p_values={name: Decimal(str(value)) for name, value in raw_p_values.items()},
        adjusted_p_values={name: Decimal(str(value)) for name, value in adjusted_p_values.items()},
        converged=converged,
        convergence_messages=convergence_messages or [],
        source_data_sha256=source_sha256,
        generated_at=datetime.now(timezone.utc),
    )


def main() -> None:
    """Enforce all gates, run locked analyses, and write stable paper assets."""
    args = parse_args()
    if args.draws != 10_000:
        raise ValueError("the confirmatory bootstrap is frozen at exactly 10,000 draws")
    result_paths = [
        args.analysis_input,
        args.fact_analysis_input,
        args.human_reference_analysis_input,
        args.missingness_report,
        args.scoring_validation_report,
        args.output_summary,
        args.sensitivity_summary,
        args.equivalence_summary,
        args.r_input_csv,
        args.r_output_summary,
    ]
    for result_path in result_paths:
        validate_experiment_path(result_path, REPO_ROOT, "results_tree")
    validate_experiment_path(args.assets_dir, REPO_ROOT, "assets_dir")
    experiment = read_model_json(args.experiment_manifest, ExperimentManifest)
    preregistration = read_model_json(args.preregistration_manifest, PreregistrationManifest)
    annotation_sample = read_model_json(args.annotation_sample_manifest, AnnotationSampleManifest)
    scoring_report = read_model_json(args.scoring_validation_report, ScoringValidationReport)
    smallest_effects = read_model_json(args.smallest_effect_manifest, SmallestEffectManifest)
    protocol_deviations = read_model_json(args.protocol_deviations, ProtocolDeviationManifest)
    missingness = read_model_json(args.missingness_report, AnalysisMissingnessReport)
    _validate_analysis_gates(
        experiment,
        preregistration,
        annotation_sample,
        scoring_report,
        smallest_effects,
        args.analysis_plan,
        protocol_deviations,
    )
    rows = read_model_jsonl(args.analysis_input, AnalysisInputRow)
    _validate_analysis_rows(rows, missingness, args.analysis_input)
    fact_rows = read_model_jsonl(args.fact_analysis_input, FactAnalysisInputRow)
    _validate_fact_analysis_rows(fact_rows, missingness, args.fact_analysis_input)
    source_sha256 = file_sha256(args.analysis_input)
    frame = rows_to_frame(rows)
    human_rows = read_model_jsonl(args.human_reference_analysis_input, AnalysisInputRow)
    human_keys = {(row.run_unit_id, row.metrics.checkpoint) for row in human_rows}
    if len(human_keys) != len(human_rows) or len(human_rows) != len(annotation_sample.conversation_ids) * 2:
        raise ValueError("human-reference analysis input must contain both checkpoints for the frozen annotation sample")
    if not {row.run_unit_id for row in human_rows}.issubset({row.run_unit_id for row in rows}):
        raise ValueError("human-reference analysis input contains a run outside the automated analysis input")
    human_frame = rows_to_frame(human_rows)
    fact_records = [
        {
            "run_unit_id": row.run_unit_id,
            "scenario_id": row.scenario_id,
            "use_case_id": row.use_case_id,
            "fact_id": row.fact_id,
            "fact_valence": row.fact_valence,
            "model_id": row.model_id,
            "source_order": row.source_order,
            "word_budget": row.word_budget,
            "emotional_cue": row.emotional_cue,
            "integrity": row.integrity,
            "disclosure_ordinal": row.disclosure_ordinal,
        }
        for row in fact_rows
        if row.checkpoint == EvaluationCheckpoint.INITIAL
    ]
    fact_frame = pd.DataFrame.from_records(fact_records)
    estimates, intervals, draws = stratified_scenario_bootstrap(frame, draws=args.draws, seed=args.seed)
    if set(estimates) != CONFIRMATORY_NAMES:
        raise ValueError("confirmatory bootstrap did not return all five preregistered estimands")
    p_values = {name: min(1.0, 2 * min(float((draws[name] <= 0).mean()), float((draws[name] >= 0).mean()))) for name in estimates}
    adjusted = holm_adjust(p_values)
    confirmatory = _summary(
        "risk_comm_v1_confirmatory",
        "use_case_stratified_scenario_bootstrap_10000_draws_holm",
        estimates,
        {name: list(interval) for name, interval in intervals.items()},
        p_values,
        adjusted,
        source_sha256,
    )
    sensitivity_estimates, sensitivity_messages = estimate_sensitivities_with_messages(frame, human_frame, fact_frame)
    sensitivity = _summary(
        "risk_comm_v1_sensitivities",
        "model_leave_use_case_out_budget_compliant_refusal_exclusion",
        sensitivity_estimates,
        {},
        {},
        {},
        source_sha256,
        converged=not sensitivity_messages,
        convergence_messages=sensitivity_messages,
    )
    scenario_effects = scenario_level_contrasts(frame)
    equivalence_p_values: Dict[str, float] = {}
    equivalence_flags: Dict[str, float] = {}
    for name, bound in smallest_effects.absolute_bounds.items():
        result = two_one_sided_test(scenario_effects[name].to_numpy(), -float(bound), float(bound))
        equivalence_p_values[f"{name}::lower"] = result.lower_p_value
        equivalence_p_values[f"{name}::upper"] = result.upper_p_value
        equivalence_flags[name] = float(result.equivalent)
    equivalence = _summary(
        "risk_comm_v1_equivalence",
        "scenario_level_two_one_sided_tests_against_frozen_smallest_effects",
        equivalence_flags,
        {},
        equivalence_p_values,
        {},
        source_sha256,
    )
    write_model_json_atomic(args.output_summary, confirmatory)
    write_model_json_atomic(args.sensitivity_summary, sensitivity)
    write_model_json_atomic(args.equivalence_summary, equivalence)
    args.r_input_csv.parent.mkdir(parents=True, exist_ok=True)
    conversation_metrics = frame[["run_unit_id", "pairwise_disclosure_gap", "unsupported_reassurance"]]
    r_frame = fact_frame.merge(conversation_metrics, on="run_unit_id", how="left", validate="many_to_one")
    r_frame.to_csv(args.r_input_csv, index=False)
    run_r_robustness_models(
        args.r_input_csv,
        args.r_output_summary,
        file_sha256(args.r_input_csv),
        REPO_ROOT / "analysis/r/run_mixed_models.R",
        REPO_ROOT / "analysis/r",
    )
    generate_paper_assets(args.assets_dir, estimates, intervals, adjusted)
    print(f"Wrote gated Python/R summaries and stable paper assets under {args.assets_dir.parent}")


if __name__ == "__main__":
    main()
