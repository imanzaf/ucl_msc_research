"""Freeze the exact Python/R source surface that can change analysis results."""

from __future__ import annotations

from pathlib import Path

from src.data_models.common import path_bundle_sha256

ANALYSIS_CODE_PATHS = [
    "analysis/r",
    "src/analysis",
    "src/cli/commands/analysis",
    "src/data_models/scoring.py",
    "src/experiments/assets.py",
    "src/scoring",
]


def analysis_code_sha256(repository_root: Path) -> str:
    """Hash every file that can construct, validate, estimate, or render analysis outcomes."""
    return path_bundle_sha256(repository_root, ANALYSIS_CODE_PATHS)
