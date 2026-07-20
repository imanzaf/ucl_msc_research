"""Regenerate stable risk_comm_v1 paper assets from a confirmatory summary."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.data_models.scoring import AnalysisSummary
from src.experiments.assets import generate_paper_assets
from src.experiments.layout import validate_experiment_path
from src.paths import REPO_ROOT
from src.storage import read_model_json


def main() -> None:
    """Read a summary and regenerate the fixed LaTeX/PDF asset names."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_experiment_path(args.summary, REPO_ROOT, "results_tree")
    validate_experiment_path(args.assets_dir, REPO_ROOT, "assets_dir")
    summary = read_model_json(args.summary, AnalysisSummary)
    if summary.analysis_id != "risk_comm_v1_confirmatory" or not summary.converged:
        raise ValueError("paper assets require the converged confirmatory analysis summary")
    intervals = {name: (float(values[0]), float(values[1])) for name, values in summary.confidence_intervals.items()}
    table_path, figure_path = generate_paper_assets(
        assets_dir=args.assets_dir,
        estimates={name: float(value) for name, value in summary.estimands.items()},
        intervals=intervals,
        adjusted_p_values={name: float(value) for name, value in summary.adjusted_p_values.items()},
    )
    print(f"Wrote {table_path} and {figure_path}")


if __name__ == "__main__":
    main()
