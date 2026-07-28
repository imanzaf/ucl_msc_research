"""Regenerate stable risk_comm_v1 paper assets from separate analysis summaries."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.data_models.scoring import AnalysisSummary
from src.experiments.assets import CONFIRMATORY_ANALYSIS_ID, SECONDARY_ANALYSIS_ID, generate_paper_assets
from src.experiments.layout import validate_experiment_path
from src.paths import REPO_ROOT
from src.storage import read_model_json


def main() -> None:
    """Read both summaries and regenerate the fixed LaTeX/PDF asset names."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmatory-summary", type=Path, required=True)
    parser.add_argument("--secondary-summary", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_experiment_path(args.confirmatory_summary, REPO_ROOT, "results_tree")
    validate_experiment_path(args.secondary_summary, REPO_ROOT, "results_tree")
    validate_experiment_path(args.assets_dir, REPO_ROOT, "assets_dir")
    confirmatory = read_model_json(args.confirmatory_summary, AnalysisSummary)
    secondary = read_model_json(args.secondary_summary, AnalysisSummary)
    if confirmatory.analysis_id != CONFIRMATORY_ANALYSIS_ID or not confirmatory.converged:
        raise ValueError("paper assets require the converged confirmatory analysis summary")
    if secondary.analysis_id != SECONDARY_ANALYSIS_ID or not secondary.converged:
        raise ValueError("paper assets require the converged secondary analysis summary")
    if secondary.raw_p_values or secondary.adjusted_p_values:
        raise ValueError("the secondary summary must not contain confirmatory p-values")
    confirmatory_intervals = {name: (float(values[0]), float(values[1])) for name, values in confirmatory.confidence_intervals.items()}
    secondary_intervals = {name: (float(values[0]), float(values[1])) for name, values in secondary.confidence_intervals.items()}
    confirmatory_path, secondary_path, figure_path = generate_paper_assets(
        assets_dir=args.assets_dir,
        confirmatory_estimates={name: float(value) for name, value in confirmatory.estimands.items()},
        confirmatory_intervals=confirmatory_intervals,
        adjusted_p_values={name: float(value) for name, value in confirmatory.adjusted_p_values.items()},
        secondary_estimates={name: float(value) for name, value in secondary.estimands.items()},
        secondary_intervals=secondary_intervals,
    )
    print(f"Wrote {confirmatory_path}, {secondary_path}, and {figure_path}")


if __name__ == "__main__":
    main()
