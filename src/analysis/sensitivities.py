"""Prespecified composite, model, and use-case sensitivities."""

from __future__ import annotations

from functools import partial
from typing import Callable, Dict, List, Tuple

import pandas as pd

from src.analysis.estimands import estimate_confirmatory_contrasts, estimate_outcome_contrasts
from src.data_models.scoring import COMPOSITE_DOMAIN_COLUMNS, FROZEN_COMPOSITE_WEIGHTS

DOMAIN_COLUMNS = {domain.value: column for domain, column in COMPOSITE_DOMAIN_COLUMNS.items()}
FROZEN_WEIGHTS = {domain.value: float(weight) for domain, weight in FROZEN_COMPOSITE_WEIGHTS.items()}
SECONDARY_OUTCOMES = {
    **DOMAIN_COLUMNS,
    "coverage_signed_gap": "coverage_signed_gap",
    "coverage_reverse_gap": "coverage_reverse_gap",
    "specificity_signed_gap": "specificity_signed_gap",
    "specificity_reverse_gap": "specificity_reverse_gap",
    "ordering_signed_gap": "ordering_signed_gap",
    "ordering_reverse_gap": "ordering_reverse_gap",
    "emphasis_signed_gap": "emphasis_signed_gap",
    "emphasis_reverse_gap": "emphasis_reverse_gap",
}


def _prefixed(prefix: str, estimates: Dict[str, float]) -> Dict[str, float]:
    """Prefix estimand names for collision-free summaries."""
    return {f"{prefix}::{name}": value for name, value in estimates.items()}


def _with_score(frame: pd.DataFrame, score: pd.Series) -> pd.DataFrame:
    """Return a copy with only the composite estimator replaced."""
    transformed = frame.copy()
    transformed["selective_risk_communication_score"] = score
    return transformed


def equal_domain_composite(frame: pd.DataFrame) -> pd.Series:
    """Calculate the prespecified equal-domain composite sensitivity."""
    columns = list(DOMAIN_COLUMNS.values())
    if set(columns) - set(frame.columns):
        raise ValueError("equal-domain sensitivity requires all five domain columns")
    return frame[columns].mean(axis=1)


def leave_one_domain_out_composite(frame: pd.DataFrame, omitted_domain: str) -> pd.Series:
    """Renormalise frozen weights after omitting exactly one domain for sensitivity."""
    if omitted_domain not in DOMAIN_COLUMNS:
        raise ValueError(f"unknown composite domain: {omitted_domain}")
    retained = [domain for domain in DOMAIN_COLUMNS if domain != omitted_domain]
    denominator = sum(FROZEN_WEIGHTS[domain] for domain in retained)
    return sum(frame[DOMAIN_COLUMNS[domain]] * (FROZEN_WEIGHTS[domain] / denominator) for domain in retained)


def estimate_sensitivities_with_messages(
    frame: pd.DataFrame,
    cumulative_frame: pd.DataFrame | None = None,
    spontaneous_change_frame: pd.DataFrame | None = None,
) -> Tuple[Dict[str, float], List[str]]:
    """Calculate all prespecified sensitivities and surface non-estimable subsets."""
    outputs: Dict[str, float] = {}
    messages: List[str] = []

    def add(prefix: str, estimator: Callable[[], Dict[str, float]]) -> None:
        """Add estimates or retain an explicit failure message."""
        try:
            outputs.update(_prefixed(prefix, estimator()))
        except ValueError as error:
            messages.append(f"{prefix}: {error}")

    for model_id in sorted(frame["model_id"].unique()):
        add(f"model={model_id}", partial(estimate_confirmatory_contrasts, frame.loc[frame["model_id"] == model_id]))
    for use_case_id in sorted(frame["use_case_id"].unique()):
        add(f"leave_use_case_out={use_case_id}", partial(estimate_confirmatory_contrasts, frame.loc[frame["use_case_id"] != use_case_id]))
    add(
        "equal_domain_composite",
        partial(estimate_confirmatory_contrasts, _with_score(frame, equal_domain_composite(frame))),
    )
    for domain in DOMAIN_COLUMNS:
        add(
            f"leave_domain_out={domain}",
            partial(estimate_confirmatory_contrasts, _with_score(frame, leave_one_domain_out_composite(frame, domain))),
        )
    for name, column in SECONDARY_OUTCOMES.items():
        add(f"secondary_initial={name}", partial(estimate_outcome_contrasts, frame, column))
    if cumulative_frame is not None:
        add("secondary_checkpoint=cumulative", partial(estimate_confirmatory_contrasts, cumulative_frame))
    if spontaneous_change_frame is not None:
        add("secondary_spontaneous_additional_communication", partial(estimate_confirmatory_contrasts, spontaneous_change_frame))
    return outputs, messages
