"""Use-case-stratified scenario-cluster bootstrap intervals."""

from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean
from typing import Dict, List, Sequence

from srcv2.analysis.confirmatory import BootstrapInterval, ScenarioContrast


def _quantile(values: List[float], probability: float) -> float:
    """Calculate a linearly interpolated empirical quantile."""
    if not values or not 0 <= probability <= 1:
        raise ValueError("quantile requires values and a probability in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def stratified_cluster_bootstrap(
    contrasts: Sequence[ScenarioContrast],
    iterations: int = 10000,
    random_seed: int = 410506,
    confidence_level: float = 0.95,
) -> BootstrapInterval:
    """Resample scenario clusters within each use case and preserve their paired contrasts."""
    if not contrasts or iterations < 100 or not 0 < confidence_level < 1:
        raise ValueError("bootstrap requires at least 100 iterations and a valid confidence level")
    by_use_case: Dict[str, List[ScenarioContrast]] = defaultdict(list)
    for contrast in contrasts:
        by_use_case[contrast.use_case_id].append(contrast)
    if len({contrast.scenario_id for contrast in contrasts}) != len(contrasts):
        raise ValueError("bootstrap requires one paired contrast per scenario cluster")
    randomizer = random.Random(random_seed)
    estimates: List[float] = []
    for _ in range(iterations):
        sampled: List[float] = []
        for use_case_id in sorted(by_use_case):
            clusters = by_use_case[use_case_id]
            sampled.extend(randomizer.choice(clusters).value for _ in range(len(clusters)))
        estimates.append(mean(sampled))
    alpha = 1 - confidence_level
    return BootstrapInterval(
        estimate=mean(contrast.value for contrast in contrasts),
        lower=_quantile(estimates, alpha / 2),
        upper=_quantile(estimates, 1 - alpha / 2),
        confidence_level=confidence_level,
        bootstrap_iterations=iterations,
        random_seed=random_seed,
    )
