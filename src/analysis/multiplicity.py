"""Deterministic Holm family-wise correction for the five confirmatory tests."""

from __future__ import annotations

from typing import Dict


def holm_adjust(p_values: Dict[str, float]) -> Dict[str, float]:
    """Return monotone Holm-adjusted p-values while preserving hypothesis names."""
    if not p_values:
        raise ValueError("Holm correction requires at least one p-value")
    if any(value < 0 or value > 1 for value in p_values.values()):
        raise ValueError("p-values must lie in [0, 1]")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    family_size = len(ordered)
    adjusted: Dict[str, float] = {}
    running_maximum = 0.0
    for index, (name, value) in enumerate(ordered):
        candidate = min(1.0, (family_size - index) * value)
        running_maximum = max(running_maximum, candidate)
        adjusted[name] = running_maximum
    return {name: adjusted[name] for name in p_values}
