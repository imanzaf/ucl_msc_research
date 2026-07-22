"""Run locked R robustness models and validate their JSON summary boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.data_models.common import file_sha256
from src.data_models.scoring import AnalysisSummary


def run_r_robustness_models(
    input_csv: Path,
    output_json: Path,
    input_sha256: str,
    r_script: Path,
    working_directory: Path,
) -> AnalysisSummary:
    """Run lmer/glmer/clmm robustness models and surface any convergence failure."""
    resolved_input = input_csv.resolve()
    resolved_output = output_json.resolve()
    resolved_script = r_script.resolve()
    resolved_working_directory = working_directory.resolve()
    if file_sha256(resolved_input) != input_sha256:
        raise ValueError("R robustness input hash does not match the supplied digest")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    command = ["Rscript", str(resolved_script), str(resolved_input), str(resolved_output), input_sha256]
    completed = subprocess.run(command, cwd=resolved_working_directory, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"R robustness analysis failed: {completed.stderr.strip() or completed.stdout.strip()}")
    summary = AnalysisSummary.model_validate_json(resolved_output.read_text(encoding="utf-8"))
    if summary.source_data_sha256 != input_sha256:
        raise RuntimeError("R robustness summary does not bind the exact input CSV")
    if not summary.converged:
        raise RuntimeError("R robustness model did not converge: " + "; ".join(summary.convergence_messages))
    return summary
