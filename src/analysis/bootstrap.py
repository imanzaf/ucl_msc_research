"""Use-case-stratified scenario cluster bootstrap for confirmatory estimands."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from src.analysis.estimands import PRIMARY_OUTCOME, estimate_outcome_contrasts


def resample_scenarios_within_use_case(frame: pd.DataFrame, generator: np.random.Generator) -> pd.DataFrame:
    """Resample scenario clusters, never individual facts or conversations."""
    sampled_parts: List[pd.DataFrame] = []
    for use_case_id, use_case_frame in frame.groupby("use_case_id", observed=True):
        scenario_ids = sorted(use_case_frame["scenario_id"].unique())
        sampled_ids = generator.choice(scenario_ids, size=len(scenario_ids), replace=True)
        for draw_index, scenario_id in enumerate(sampled_ids):
            cluster = use_case_frame.loc[use_case_frame["scenario_id"] == scenario_id].copy()
            cluster["scenario_id"] = f"{use_case_id}__BOOT{draw_index:02d}"
            sampled_parts.append(cluster)
    if not sampled_parts:
        raise ValueError("bootstrap frame contains no scenario clusters")
    return pd.concat(sampled_parts, ignore_index=True)


def stratified_scenario_bootstrap(
    frame: pd.DataFrame,
    outcome: str = PRIMARY_OUTCOME,
    draws: int = 10_000,
    seed: int = 7,
) -> Tuple[Dict[str, float], Dict[str, Tuple[float, float]], pd.DataFrame]:
    """Estimate H1/H2 and percentile intervals for one named outcome."""
    if draws < 1:
        raise ValueError("bootstrap draws must be positive")
    point_estimates = estimate_outcome_contrasts(frame, outcome)
    generator = np.random.default_rng(seed)
    sampled_estimates = [
        estimate_outcome_contrasts(
            resample_scenarios_within_use_case(frame, generator),
            outcome,
        )
        for _ in range(draws)
    ]
    draw_frame = pd.DataFrame.from_records(sampled_estimates)
    intervals = {estimand: (float(draw_frame[estimand].quantile(0.025)), float(draw_frame[estimand].quantile(0.975))) for estimand in point_estimates}
    return point_estimates, intervals, draw_frame
