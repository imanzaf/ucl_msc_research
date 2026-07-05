"""Programmatic scoring helpers for benchmark responses."""

from src.scoring.metrics import (
    COMPOSITE_SCORE_WEIGHTS,
    DISCLOSURE_REQUIREMENT_WEIGHTS,
    POLARITY_MATERIALITY_WEIGHTS,
    calculate_response_metrics,
    calculate_user_harm_metrics,
)

__all__ = [
    "COMPOSITE_SCORE_WEIGHTS",
    "DISCLOSURE_REQUIREMENT_WEIGHTS",
    "POLARITY_MATERIALITY_WEIGHTS",
    "calculate_response_metrics",
    "calculate_user_harm_metrics",
]
