"""Power simulation for the equal-weight selective-communication score."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Dict

import numpy as np
from scipy import stats

from src.analysis.estimands import CONFIRMATORY_NAMES

COMPONENT_COUNT = 2
COMPONENT_WEIGHTS = np.asarray([0.5, 0.5])
BASE_COMPONENT_SCORE = 0.35
NORMAL_95_PERCENT_CRITICAL_VALUE = 1.96


@dataclass(frozen=True)
class VarianceComponents:
    """Represent calibrated heterogeneity in the selective-score estimator."""

    pair_standard_deviation: float
    fact_standard_deviation: float
    scenario_standard_deviation: float
    model_standard_deviation: float
    scoring_error_standard_deviation: float

    def validate(self) -> None:
        """Reject negative or entirely degenerate calibration components."""
        values = [
            self.pair_standard_deviation,
            self.fact_standard_deviation,
            self.scenario_standard_deviation,
            self.model_standard_deviation,
            self.scoring_error_standard_deviation,
        ]
        if any(value < 0 for value in values) or not any(value > 0 for value in values):
            raise ValueError("power variance components must be nonnegative and not all zero")


def _selective_contrasts(
    effects: Dict[str, float],
    components: VarianceComponents,
    simulations: int,
    seed: int,
) -> Dict[str, np.ndarray]:
    """Simulate coverage and specificity over the complete repeated design."""
    components.validate()
    if simulations < 1:
        raise ValueError("power simulation requires positive draws")
    if set(effects) != CONFIRMATORY_NAMES:
        raise ValueError("power effects must cover exactly H1 and H2")
    generator = np.random.default_rng(seed)
    shape = (simulations, 20, 3, 2, 2, COMPONENT_COUNT)
    scenario = generator.normal(
        0,
        components.scenario_standard_deviation,
        size=(simulations, 20, 1, 2, 2, COMPONENT_COUNT),
    )
    model = generator.normal(
        0,
        components.model_standard_deviation,
        size=(simulations, 1, 3, 2, 2, COMPONENT_COUNT),
    )
    pair = generator.normal(
        0,
        components.pair_standard_deviation,
        size=(simulations, 20, 2, 1, 2, 2, COMPONENT_COUNT),
    ).mean(axis=2)
    fact = generator.normal(
        0,
        components.fact_standard_deviation,
        size=(simulations, 20, 4, 1, 2, 2, COMPONENT_COUNT),
    ).mean(axis=2)
    scoring = generator.normal(
        0,
        components.scoring_error_standard_deviation,
        size=shape,
    )
    components_array = BASE_COMPONENT_SCORE + scenario + model + pair + fact + scoring
    components_array[:, :, :, 1, :, :] += effects["H1"]
    components_array[:, :, :, :, 1, :] += effects["H2"]
    components_array = np.clip(components_array, 0.0, 1.0)
    scores = np.tensordot(components_array, COMPONENT_WEIGHTS, axes=([-1], [0]))
    h1 = scores[:, :, :, 1, :].mean(axis=(2, 3)) - scores[:, :, :, 0, :].mean(axis=(2, 3))
    h2 = scores[:, :, :, :, 1].mean(axis=(2, 3)) - scores[:, :, :, :, 0].mean(axis=(2, 3))
    return {"H1": h1, "H2": h2}


def _paired_p_values(scenario_effects: np.ndarray) -> np.ndarray:
    """Return vectorised two-sided scenario-level paired-test approximations."""
    standard_errors = scenario_effects.std(axis=1, ddof=1) / np.sqrt(scenario_effects.shape[1])
    statistics = np.divide(
        scenario_effects.mean(axis=1),
        standard_errors,
        out=np.zeros(scenario_effects.shape[0]),
        where=standard_errors > 0,
    )
    return 2 * stats.t.sf(
        np.abs(statistics),
        df=scenario_effects.shape[1] - 1,
    )


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
    components: VarianceComponents,
    simulations: int = 5_000,
    alpha: float = 0.05,
    seed: int = 7,
) -> Dict[str, float]:
    """Estimate H1/H2 power for selective communication under the two-test Holm family."""
    if not 0 < alpha < 1:
        raise ValueError("power alpha must lie strictly between zero and one")
    names = sorted(CONFIRMATORY_NAMES)
    contrasts = _selective_contrasts(effects, components, simulations, seed)
    p_values = np.column_stack([_paired_p_values(contrasts[name]) for name in names])
    rejected = _holm_rejections(p_values, alpha)
    return {name: float(rejected[:, index].mean()) for index, name in enumerate(names)}


def expected_secondary_interval_half_widths(
    contrast_standard_deviations: Dict[str, float],
    scenario_count: int = 20,
) -> Dict[str, float]:
    """Convert calibration contrast variation into expected 95% interval precision."""
    if scenario_count < 2:
        raise ValueError("secondary precision requires at least two scenarios")
    if not contrast_standard_deviations or any(value <= 0 for value in contrast_standard_deviations.values()):
        raise ValueError("secondary precision requires positive calibrated standard deviations")
    return {name: NORMAL_95_PERCENT_CRITICAL_VALUE * value / sqrt(scenario_count) for name, value in contrast_standard_deviations.items()}
