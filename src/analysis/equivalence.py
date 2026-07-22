"""Two one-sided equivalence checks against preregistered smallest effects."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class EquivalenceResult:
    """Return TOST p-values and whether both one-sided tests reject."""

    lower_p_value: float
    upper_p_value: float
    equivalent: bool


def two_one_sided_test(values: np.ndarray, lower_bound: float, upper_bound: float, alpha: float = 0.05) -> EquivalenceResult:
    """Test whether a paired-effect distribution lies inside fixed equivalence bounds."""
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("equivalence test requires at least two one-dimensional observations")
    if lower_bound >= upper_bound:
        raise ValueError("lower equivalence bound must be below upper bound")
    standard_error = float(stats.sem(values))
    if standard_error == 0:
        mean_value = float(np.mean(values))
        equivalent = lower_bound < mean_value < upper_bound
        return EquivalenceResult(0.0 if mean_value > lower_bound else 1.0, 0.0 if mean_value < upper_bound else 1.0, equivalent)
    degrees_of_freedom = len(values) - 1
    mean_value = float(np.mean(values))
    lower_statistic = (mean_value - lower_bound) / standard_error
    upper_statistic = (mean_value - upper_bound) / standard_error
    lower_p_value = float(stats.t.sf(lower_statistic, degrees_of_freedom))
    upper_p_value = float(stats.t.cdf(upper_statistic, degrees_of_freedom))
    return EquivalenceResult(
        lower_p_value=lower_p_value,
        upper_p_value=upper_p_value,
        equivalent=lower_p_value < alpha and upper_p_value < alpha,
    )
