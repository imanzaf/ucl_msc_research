"""Stable LaTeX paper assets for every final-protocol experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable

from srcv2.paths import EXPERIMENT_NAMES, experiment_paths
from srcv2.storage import atomic_write_bytes


def _escape_latex(value: str) -> str:
    """Escape the limited special characters used in generated table cells."""
    return value.replace("_", r"\_").replace("%", r"\%")


def generate_paper_asset(experiment: str, rows: Iterable[Dict[str, object]]) -> Path:
    """Generate one stable result-summary table for an experiment."""
    if experiment not in EXPERIMENT_NAMES:
        raise ValueError(f"unknown experiment: {experiment}")
    materialized = list(rows)
    columns = sorted({key for row in materialized for key in row}) or ["status"]
    if not materialized:
        materialized = [{"status": "Results not yet available."}]
        columns = ["status"]
    alignment = "l" * len(columns)
    lines = [r"\begin{tabular}{" + alignment + "}", r"\toprule", " & ".join(_escape_latex(column) for column in columns) + r" \\", r"\midrule"]
    for row in materialized:
        lines.append(" & ".join(_escape_latex(str(row.get(column, ""))) for column in columns) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    output = experiment_paths(experiment)["assets"] / f"{experiment}_table.tex"
    atomic_write_bytes(output, ("\n".join(lines) + "\n").encode("utf-8"))
    return output


def generate_all_placeholder_assets() -> list[Path]:
    """Create stable placeholders for all active and deferred experiments."""
    return [generate_paper_asset(experiment, []) for experiment in EXPERIMENT_NAMES]
