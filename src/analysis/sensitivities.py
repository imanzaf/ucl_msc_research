"""Prespecified model, use-case, outcome, and checkpoint estimates."""

from __future__ import annotations

from functools import partial
from typing import Callable, Dict, List, Mapping, Tuple

import pandas as pd

from src.analysis.estimands import PRIMARY_OUTCOME, SECONDARY_SCORE_OUTCOMES, estimate_confirmatory_contrasts, estimate_outcome_contrasts
from src.data_models.scoring import EvaluationCheckpoint

SCORE_OUTCOMES = (PRIMARY_OUTCOME, *SECONDARY_SCORE_OUTCOMES)


def _prefixed(prefix: str, estimates: Dict[str, float]) -> Dict[str, float]:
    """Prefix estimand names for collision-free summaries."""
    return {f"{prefix}::{name}": value for name, value in estimates.items()}


def estimate_sensitivities_with_messages(
    initial_frame: pd.DataFrame,
    checkpoint_frames: Mapping[EvaluationCheckpoint, pd.DataFrame] | None = None,
) -> Tuple[Dict[str, float], List[str]]:
    """Estimate prespecified subsets and secondary scores without extra hypothesis tests."""
    outputs: Dict[str, float] = {}
    messages: List[str] = []

    def add(prefix: str, estimator: Callable[[], Dict[str, float]]) -> None:
        """Add estimates or retain an explicit non-estimability message."""
        try:
            outputs.update(_prefixed(prefix, estimator()))
        except ValueError as error:
            messages.append(f"{prefix}: {error}")

    for model_id in sorted(initial_frame["model_id"].unique()):
        add(
            f"model={model_id}",
            partial(
                estimate_confirmatory_contrasts,
                initial_frame.loc[initial_frame["model_id"] == model_id],
            ),
        )
    for use_case_id in sorted(initial_frame["use_case_id"].unique()):
        add(
            f"leave_use_case_out={use_case_id}",
            partial(
                estimate_confirmatory_contrasts,
                initial_frame.loc[initial_frame["use_case_id"] != use_case_id],
            ),
        )
    for outcome in SECONDARY_SCORE_OUTCOMES:
        add(
            f"secondary_initial={outcome}",
            partial(estimate_outcome_contrasts, initial_frame, outcome),
        )
    for checkpoint, frame in (checkpoint_frames or {}).items():
        if checkpoint == EvaluationCheckpoint.INITIAL:
            continue
        for outcome in SCORE_OUTCOMES:
            add(
                f"secondary_checkpoint={checkpoint.value}:{outcome}",
                partial(estimate_outcome_contrasts, frame, outcome),
            )
    return outputs, messages
