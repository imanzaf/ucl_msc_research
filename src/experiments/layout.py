"""Enforce the fixed risk_comm_v1 experiment directory and stable artifact layout."""

from __future__ import annotations

import re
from pathlib import Path

EXPERIMENT_NAME = "risk_comm_v1"
TIMESTAMP_PATTERN = re.compile(r"^\d{8}T\d{6}_(results\.jsonl|run\.log)$")


def experiment_root(repository_root: Path) -> Path:
    """Return the only permitted output root for the V9 main experiment."""
    return (repository_root / "data/outputs/experiments" / EXPERIMENT_NAME).resolve()


def validate_experiment_path(path: Path, repository_root: Path, kind: str) -> Path:
    """Resolve and validate one config, result, cache, checkpoint, asset, or log path."""
    root = experiment_root(repository_root)
    resolved = path.resolve()
    if kind == "config" and resolved != root / "config.json":
        raise ValueError("experiment config must be data/outputs/experiments/risk_comm_v1/config.json")
    if kind == "cache" and resolved != root / "cache":
        raise ValueError("experiment cache must be data/outputs/experiments/risk_comm_v1/cache/")
    if kind == "results_tree":
        results_root = root / "results"
        if resolved != results_root and not resolved.is_relative_to(results_root):
            raise ValueError("experiment result path is outside the fixed risk_comm_v1 results tree")
        return resolved
    if kind == "assets_dir" and resolved != root / "assets":
        raise ValueError("experiment assets directory must be data/outputs/experiments/risk_comm_v1/assets/")
    expected_parents = {
        "result": root / "results",
        "log": root / "logs",
        "checkpoint": root / "checkpoints",
        "asset": root / "assets",
    }
    if kind in expected_parents and resolved.parent != expected_parents[kind]:
        raise ValueError(f"experiment {kind} path is outside the fixed risk_comm_v1 layout")
    if kind in {"result", "log"} and TIMESTAMP_PATTERN.fullmatch(resolved.name) is None:
        raise ValueError(f"experiment {kind} filename must use the frozen UTC timestamp convention")
    if kind not in {"config", "cache", "assets_dir", *expected_parents}:
        raise ValueError(f"unknown experiment path kind: {kind}")
    return resolved
