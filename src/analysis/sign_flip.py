"""Seeded scenario-level paired sign-flip inference for H1 and H2."""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from src.analysis.estimands import CONFIRMATORY_NAMES, scenario_level_contrasts
from src.analysis.multiplicity import holm_adjust


def paired_sign_flip_p_value(values: np.ndarray, permutations: int = 100_000, seed: int = 7) -> float:
    """Return a two-sided Monte Carlo sign-flip p-value with finite-sample correction."""
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("sign-flip inference requires a one-dimensional scenario contrast vector")
    if permutations != 100_000:
        raise ValueError("confirmatory sign-flip inference is frozen at 100,000 permutations")
    if not np.isfinite(values).all():
        raise ValueError("sign-flip contrasts must be finite")
    observed = abs(float(values.mean()))
    generator = np.random.default_rng(seed)
    extreme = 0
    remaining = permutations
    while remaining:
        batch = min(10_000, remaining)
        signs = generator.choice(np.array([-1.0, 1.0]), size=(batch, len(values)))
        permuted = np.abs((signs * values).mean(axis=1))
        extreme += int(np.count_nonzero(permuted >= observed))
        remaining -= batch
    return (extreme + 1) / (permutations + 1)


def confirmatory_sign_flip_tests(
    frame: pd.DataFrame,
    permutations: int = 100_000,
    seed: int = 7,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Test both frozen hypotheses and Holm-adjust their two-sided p-values."""
    scenario_effects = scenario_level_contrasts(frame)
    raw = {
        name: paired_sign_flip_p_value(scenario_effects[name].to_numpy(dtype=float), permutations, seed + index)
        for index, name in enumerate(sorted(CONFIRMATORY_NAMES))
    }
    return raw, holm_adjust(raw)
