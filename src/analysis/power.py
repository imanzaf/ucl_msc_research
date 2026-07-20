"""Calibration-based power simulation for the repeated, use-case-clustered design."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np
from scipy import stats

CONFIRMATORY_NAMES = {"H1", "H2a", "H2b", "M1", "M2"}


@dataclass(frozen=True)
class VarianceComponents:
    """Represent calibrated heterogeneity at each repeated-design level."""

    use_case_standard_deviation: float
    scenario_standard_deviation: float
    model_standard_deviation: float
    scoring_error_standard_deviation: float

    def validate(self) -> None:
        """Reject negative or entirely degenerate calibration components."""
        values = [
            self.use_case_standard_deviation,
            self.scenario_standard_deviation,
            self.model_standard_deviation,
            self.scoring_error_standard_deviation,
        ]
        if any(value < 0 for value in values) or not any(value > 0 for value in values):
            raise ValueError("power variance components must be nonnegative and not all zero")


def simulate_repeated_design_p_values(
    effect: float,
    components: VarianceComponents,
    simulations: int,
    seed: int,
) -> np.ndarray:
    """Simulate clustered use-case tests after averaging repeated scenarios and models."""
    components.validate()
    if simulations < 1:
        raise ValueError("power simulation requires positive draws")
    generator = np.random.default_rng(seed)
    shape = (simulations, 10, 4, 3)
    use_case_effect = generator.normal(0, components.use_case_standard_deviation, size=(simulations, 10, 1, 1))
    scenario_effect = generator.normal(0, components.scenario_standard_deviation, size=(simulations, 10, 4, 1))
    model_effect = generator.normal(0, components.model_standard_deviation, size=(simulations, 1, 1, 3))
    scoring_error = generator.normal(0, components.scoring_error_standard_deviation, size=shape)
    repeated_effects = effect + use_case_effect + scenario_effect + model_effect + scoring_error
    use_case_means = repeated_effects.mean(axis=(2, 3))
    standard_errors = use_case_means.std(axis=1, ddof=1) / np.sqrt(10)
    statistics = np.divide(use_case_means.mean(axis=1), standard_errors, out=np.zeros(simulations), where=standard_errors > 0)
    return 2 * stats.t.sf(np.abs(statistics), df=9)


def _holm_rejections(p_values: np.ndarray, alpha: float) -> np.ndarray:
    """Apply Holm's sequential family-wise procedure within each simulation."""
    order = np.argsort(p_values, axis=1)
    ordered = np.take_along_axis(p_values, order, axis=1)
    thresholds = alpha / np.arange(p_values.shape[1], 0, -1)
    sequential = np.cumprod(ordered <= thresholds, axis=1).astype(bool)
    rejected = np.zeros_like(sequential)
    np.put_along_axis(rejected, order, sequential, axis=1)
    return rejected


def simulate_holm_corrected_power(
    effects: Dict[str, float],
    components: Dict[str, VarianceComponents],
    simulations: int = 5_000,
    alpha: float = 0.05,
    seed: int = 7,
) -> Dict[str, float]:
    """Estimate per-hypothesis rejection probability under the five-test Holm family."""
    if set(effects) != CONFIRMATORY_NAMES or set(components) != CONFIRMATORY_NAMES:
        raise ValueError("power inputs must cover exactly H1, H2a, H2b, M1, and M2")
    if not 0 < alpha < 1:
        raise ValueError("power alpha must lie strictly between zero and one")
    names = sorted(CONFIRMATORY_NAMES)
    p_values = np.column_stack(
        [simulate_repeated_design_p_values(effects[name], components[name], simulations, seed + index) for index, name in enumerate(names)]
    )
    rejected = _holm_rejections(p_values, alpha)
    return {name: float(rejected[:, index].mean()) for index, name in enumerate(names)}
