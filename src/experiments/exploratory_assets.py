"""Stable paper assets for separately reported exploratory experiments."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pandas as pd

from src.data_models.scoring import AnalysisSummary

EXPERIMENTS = {"material_priority_v1", "brevity_locus_v1"}


def generate_exploratory_paper_assets(
    summary: AnalysisSummary,
    assets_dir: Path,
    experiment_name: str,
) -> Tuple[Path, Path]:
    """Write stable LaTeX and CSV tables from paired estimates and cluster intervals."""
    if experiment_name not in EXPERIMENTS:
        raise ValueError(f"unknown exploratory experiment: {experiment_name}")
    if summary.raw_p_values or summary.adjusted_p_values:
        raise ValueError("exploratory assets must not contain confirmatory p-values")
    rows = []
    for name, estimate in summary.estimands.items():
        interval = summary.confidence_intervals.get(name)
        if interval is None:
            raise ValueError("every exploratory estimate requires a scenario-cluster interval")
        rows.append(
            {
                "outcome": name,
                "paired_estimate": float(estimate),
                "lower_95": float(interval[0]),
                "upper_95": float(interval[1]),
            }
        )
    frame = pd.DataFrame.from_records(rows).set_index("outcome")
    assets_dir.mkdir(parents=True, exist_ok=True)
    table_path = assets_dir / f"{experiment_name}_table.tex"
    csv_path = assets_dir / f"{experiment_name}_domain_summary.csv"
    table_path.write_text(frame.to_latex(float_format=lambda value: f"{value:.3f}"), encoding="utf-8")
    frame.to_csv(csv_path)
    return table_path, csv_path
