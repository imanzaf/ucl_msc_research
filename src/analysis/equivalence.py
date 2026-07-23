"""Cluster-aware 90% bootstrap intervals for equivalence decisions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.analysis.bootstrap import resample_scenarios_within_use_case
from src.analysis.estimands import estimate_confirmatory_contrasts


@dataclass(frozen=True)
class EquivalenceResult:
    """Return a 90% scenario-cluster interval and its bound decision."""

    lower_interval: float
    upper_interval: float
    equivalent: bool


def cluster_bootstrap_equivalence(
    frame: pd.DataFrame,
    estimand: str,
    lower_bound: float,
    upper_bound: float,
    draws: int = 10_000,
    seed: int = 7,
) -> EquivalenceResult:
    """Declare equivalence only when the cluster-aware 90% interval lies inside bounds."""
    if lower_bound >= upper_bound:
        raise ValueError("lower equivalence bound must be below upper bound")
    if draws < 1:
        raise ValueError("equivalence bootstrap draws must be positive")
    generator = np.random.default_rng(seed)
    estimates = np.array([estimate_confirmatory_contrasts(resample_scenarios_within_use_case(frame, generator))[estimand] for _ in range(draws)])
    lower, upper = (float(value) for value in np.quantile(estimates, [0.05, 0.95]))
    return EquivalenceResult(lower, upper, lower_bound < lower and upper < upper_bound)
