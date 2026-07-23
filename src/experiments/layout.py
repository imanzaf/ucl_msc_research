"""Enforce separate stable layouts for all three versioned experiments."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

EXPERIMENT_NAME = "risk_comm_v1"
EXPERIMENT_NAMES = {"risk_comm_v1", "material_priority_v1", "brevity_locus_v1"}
TIMESTAMP_PATTERN = re.compile(r"^\d{8}T\d{6}_(results\.jsonl|run\.log)$")


def experiment_root(repository_root: Path, experiment_name: str = EXPERIMENT_NAME) -> Path:
    """Return the permitted output root for one independently manifested experiment."""
    if experiment_name not in EXPERIMENT_NAMES:
        raise ValueError(f"unknown experiment name: {experiment_name}")
    return (repository_root / "data/outputs/experiments" / experiment_name).resolve()


def validate_experiment_path(path: Path, repository_root: Path, kind: str, experiment_name: str = EXPERIMENT_NAME) -> Path:
    """Resolve and validate one config, result, cache, checkpoint, asset, or log path."""
    root = experiment_root(repository_root, experiment_name)
    resolved = path.resolve()
    if kind == "config" and resolved != root / "config.json":
        raise ValueError(f"experiment config must be data/outputs/experiments/{experiment_name}/config.json")
    if kind == "cache" and resolved != root / "cache":
        raise ValueError(f"experiment cache must be data/outputs/experiments/{experiment_name}/cache/")
    if kind == "results_tree":
        results_root = root / "results"
        if resolved != results_root and not resolved.is_relative_to(results_root):
            raise ValueError(f"experiment result path is outside the fixed {experiment_name} results tree")
        return resolved
    if kind == "assets_dir" and resolved != root / "assets":
        raise ValueError(f"experiment assets directory must be data/outputs/experiments/{experiment_name}/assets/")
    if kind == "manifest" and resolved.parent != root / "manifests":
        raise ValueError(f"experiment manifest path is outside the fixed {experiment_name} manifests directory")
    expected_parents = {
        "result": root / "results",
        "log": root / "logs",
        "checkpoint": root / "checkpoints",
        "asset": root / "assets",
    }
    if kind in expected_parents and resolved.parent != expected_parents[kind]:
        raise ValueError(f"experiment {kind} path is outside the fixed {experiment_name} layout")
    if kind in {"result", "log"} and TIMESTAMP_PATTERN.fullmatch(resolved.name) is None:
        raise ValueError(f"experiment {kind} filename must use the frozen UTC timestamp convention")
    if kind in {"result", "log"}:
        try:
            datetime.strptime(resolved.name.split("_", 1)[0], "%Y%m%dT%H%M%S")
        except ValueError as error:
            raise ValueError(f"experiment {kind} filename contains an invalid UTC timestamp") from error
    if kind not in {"config", "cache", "assets_dir", "manifest", *expected_parents}:
        raise ValueError(f"unknown experiment path kind: {kind}")
    return resolved
