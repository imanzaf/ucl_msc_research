"""Run paired selective-communication analyses for one exploratory experiment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from src.analysis.estimands import rows_to_frame
from src.analysis.exploratory import brevity_locus_scenario_effects, material_priority_scenario_effects, scenario_cluster_estimates
from src.analysis.outcomes import apply_validation_disposition
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.scoring import AnalysisEngine, AnalysisInputRow, AnalysisSummary, ValidationDispositionManifest
from src.data_models.study import EXPERIMENT_DIMENSIONS, ExperimentName
from src.experiments.exploratory_assets import generate_exploratory_paper_assets
from src.experiments.layout import validate_experiment_path
from src.paths import REPO_ROOT
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def _load_optional_manual_frame(
    path: Optional[Path],
    experiment_name: ExperimentName,
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Load and hash one optional experiment-local manual-scoring input."""
    if path is None:
        return None, None
    validate_experiment_path(path, REPO_ROOT, "results_tree", experiment_name.value)
    return rows_to_frame(read_model_jsonl(path, AnalysisInputRow)), file_sha256(path)


def _material_priority_effects(
    frame: pd.DataFrame,
    primary_reference_input: Optional[Path],
    primary_reference_manual_input: Optional[Path],
) -> Tuple[pd.DataFrame, str, Optional[str], Optional[str]]:
    """Build material-priority scenario effects without a primary reference."""
    if primary_reference_input is not None or primary_reference_manual_input is not None:
        raise ValueError("material_priority_v1 does not use primary reference inputs")
    return (
        material_priority_scenario_effects(frame),
        "concerned_minus_neutral_under_tight_budget_scenario_cluster_bootstrap",
        None,
        None,
    )


def _brevity_locus_effects(
    frame: pd.DataFrame,
    primary_reference_input: Optional[Path],
    primary_reference_manual_input: Optional[Path],
    disposition: ValidationDispositionManifest,
) -> Tuple[pd.DataFrame, str, str, Optional[str]]:
    """Build brevity-locus effects against the primary tight-neutral reference."""
    if primary_reference_input is None:
        raise ValueError("brevity_locus_v1 requires the primary tight-neutral reference input")
    validate_experiment_path(primary_reference_input, REPO_ROOT, "results_tree", ExperimentName.RISK_COMM_V1.value)
    reference_rows = read_model_jsonl(primary_reference_input, AnalysisInputRow)
    primary_frame = rows_to_frame(reference_rows)
    if len(primary_frame) != EXPERIMENT_DIMENSIONS[ExperimentName.RISK_COMM_V1].conversation_count:
        raise ValueError("brevity_locus_v1 requires the complete 480-row primary reference")
    primary_manual_frame, primary_manual_sha256 = _load_optional_manual_frame(
        primary_reference_manual_input,
        ExperimentName.RISK_COMM_V1,
    )
    primary_reference = apply_validation_disposition(primary_frame, disposition, primary_manual_frame)
    return (
        brevity_locus_scenario_effects(frame, primary_reference),
        "user_brevity_minus_primary_tight_neutral_scenario_cluster_bootstrap",
        file_sha256(primary_reference_input),
        primary_manual_sha256,
    )


def _remove_withheld_secondary_effects(
    effects: pd.DataFrame,
    disposition: ValidationDispositionManifest,
) -> pd.DataFrame:
    """Remove secondary outcomes withheld by the blinded validation disposition."""
    excluded = set()
    if disposition.presentation_result_withheld:
        excluded.update(
            {
                "presentation_style",
                "framing",
                "ordering",
                "emphasis",
            }
        )
    if disposition.factual_inaccuracy_result_withheld:
        excluded.add("factual_inaccuracy")
    return effects.drop(columns=sorted(excluded), errors="ignore")


def main() -> None:
    """Write paired estimates, 95% scenario-cluster intervals, and stable assets without p-values."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment-name", choices=[ExperimentName.MATERIAL_PRIORITY_V1.value, ExperimentName.BREVITY_LOCUS_V1.value], required=True
    )
    parser.add_argument("--analysis-input", type=Path, required=True)
    parser.add_argument("--primary-reference-input", type=Path)
    parser.add_argument("--primary-reference-manual-input", type=Path)
    parser.add_argument("--validation-disposition-manifest", type=Path, required=True)
    parser.add_argument("--manual-analysis-input", type=Path)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--draws", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    experiment_name = ExperimentName(args.experiment_name)
    validate_experiment_path(args.analysis_input, REPO_ROOT, "results_tree", experiment_name.value)
    validate_experiment_path(args.output_summary, REPO_ROOT, "results_tree", experiment_name.value)
    validate_experiment_path(args.assets_dir, REPO_ROOT, "assets_dir", experiment_name.value)
    disposition = read_model_json(args.validation_disposition_manifest, ValidationDispositionManifest)
    validate_model_self_hash(disposition, "manifest_sha256")
    if disposition.confirmatory_inference_withheld:
        raise PermissionError("the frozen scoring disposition withholds the selective-communication outcome")
    rows = read_model_jsonl(args.analysis_input, AnalysisInputRow)
    frame = rows_to_frame(rows)
    expected_count = EXPERIMENT_DIMENSIONS[experiment_name].conversation_count
    if len(frame) != expected_count:
        raise ValueError(f"{experiment_name.value} analysis requires exactly {expected_count} initial rows")
    manual_frame, manual_sha256 = _load_optional_manual_frame(args.manual_analysis_input, experiment_name)
    frame = apply_validation_disposition(frame, disposition, manual_frame)
    if experiment_name == ExperimentName.MATERIAL_PRIORITY_V1:
        scenario_effects, method, reference_sha256, primary_manual_sha256 = _material_priority_effects(
            frame,
            args.primary_reference_input,
            args.primary_reference_manual_input,
        )
    else:
        scenario_effects, method, reference_sha256, primary_manual_sha256 = _brevity_locus_effects(
            frame,
            args.primary_reference_input,
            args.primary_reference_manual_input,
            disposition,
        )
    scenario_effects = _remove_withheld_secondary_effects(
        scenario_effects,
        disposition,
    )
    estimates, intervals = scenario_cluster_estimates(scenario_effects, args.draws, args.seed)
    source_sha256 = artifact_sha256(
        {
            "analysis_input": file_sha256(args.analysis_input),
            "primary_reference_input": reference_sha256,
            "primary_reference_manual_input": primary_manual_sha256,
            "manual_analysis_input": manual_sha256,
            "validation_disposition": disposition.manifest_sha256,
        }
    )
    summary = AnalysisSummary(
        schema_version="2.0.0",
        analysis_id=f"{experiment_name.value}_exploratory",
        engine=AnalysisEngine.PYTHON,
        method=method,
        estimands={name: Decimal(str(value)) for name, value in estimates.items()},
        confidence_intervals={name: [Decimal(str(value)) for value in interval] for name, interval in intervals.items()},
        raw_p_values={},
        adjusted_p_values={},
        converged=True,
        convergence_messages=[],
        source_data_sha256=source_sha256,
        generated_at=datetime.now(timezone.utc),
    )
    write_model_json_atomic(args.output_summary, summary)
    generate_exploratory_paper_assets(summary, args.assets_dir, experiment_name.value)
    print(f"Wrote paired exploratory estimates and stable assets for {experiment_name.value}")


if __name__ == "__main__":
    main()
