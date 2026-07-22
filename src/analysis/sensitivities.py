"""Preregistered model, use-case, and quality-filter sensitivities."""

from __future__ import annotations

from functools import partial
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import statsmodels.api as sm

from src.analysis.estimands import estimate_confirmatory_contrasts, estimate_primary_contrasts


def _prefixed(prefix: str, estimates: Dict[str, float]) -> Dict[str, float]:
    """Prefix estimand names for collision-free schema-validated summaries."""
    return {f"{prefix}::{name}": value for name, value in estimates.items()}


def _binary_threshold_estimates(frame: pd.DataFrame, fact_frame: pd.DataFrame, threshold: str) -> Dict[str, float]:
    """Rebuild conversation outcomes from fact-level binary disclosure states."""
    required = {"run_unit_id", "fact_id", "fact_valence", "disclosure_ordinal"}
    if required - set(fact_frame.columns):
        raise ValueError("binary disclosure sensitivity requires fact-level run, fact, valence, and ordinal fields")
    counts = fact_frame.groupby("run_unit_id", observed=True)["fact_id"].nunique()
    if counts.empty or not counts.eq(4).all():
        raise ValueError("binary disclosure sensitivity requires four unique material facts per run unit")
    binary = fact_frame.copy()
    transformed = frame.copy()
    if threshold == "full":
        binary["binary_disclosure"] = (binary["disclosure_ordinal"] == 2).astype(float)
    elif threshold == "present":
        binary["binary_disclosure"] = (binary["disclosure_ordinal"] > 0).astype(float)
    else:
        raise ValueError(f"unknown disclosure threshold: {threshold}")
    valence_means = binary.groupby(["run_unit_id", "fact_valence"], observed=True)["binary_disclosure"].mean().unstack("fact_valence")
    if not {"adverse", "favourable"}.issubset(valence_means.columns):
        raise ValueError("binary disclosure sensitivity requires adverse and favourable facts in every run")
    derived = valence_means.assign(
        pairwise_disclosure_gap=valence_means["favourable"] - valence_means["adverse"],
        adverse_coverage=valence_means["adverse"],
        material_coverage=(valence_means["favourable"] + valence_means["adverse"]) / 2,
    ).reset_index()[["run_unit_id", "pairwise_disclosure_gap", "adverse_coverage", "material_coverage"]]
    transformed = transformed.drop(columns=["pairwise_disclosure_gap", "adverse_coverage", "material_coverage"]).merge(
        derived,
        on="run_unit_id",
        how="left",
        validate="one_to_one",
    )
    if transformed[["pairwise_disclosure_gap", "adverse_coverage", "material_coverage"]].isna().any().any():
        raise ValueError("fact-level binary outcomes do not cover every conversation")
    return estimate_confirmatory_contrasts(transformed)


def _response_length_mediation(frame: pd.DataFrame) -> Dict[str, float]:
    """Estimate the preregistered response-length-adjusted disclosure association."""
    design = pd.DataFrame(
        {
            "tight": (frame["word_budget"] == "tight").astype(float),
            "worried": (frame["emotional_cue"] == "worried").astype(float),
            "integrity": (frame["integrity"] == "targeted").astype(float),
            "response_word_count": frame["response_word_count"].astype(float),
        }
    )
    fitted = sm.OLS(frame["pairwise_disclosure_gap"].astype(float), sm.add_constant(design), missing="raise").fit()
    return {f"coefficient={name}": float(value) for name, value in fitted.params.items()}


def _human_reference_differences(frame: pd.DataFrame, human_frame: pd.DataFrame) -> Dict[str, float]:
    """Measure outcome-level automated-minus-human bias on the locked human subset."""
    outcomes = ["pairwise_disclosure_gap", "adverse_coverage", "unsupported_reassurance"]
    merged = human_frame[["run_unit_id", *outcomes]].merge(
        frame[["run_unit_id", *outcomes]],
        on="run_unit_id",
        how="inner",
        suffixes=("_human", "_automated"),
        validate="one_to_one",
    )
    if len(merged) != len(human_frame):
        raise ValueError("human-reference rows do not all join to the automated analysis input")
    return {f"automated_minus_human={outcome}": float((merged[f"{outcome}_automated"] - merged[f"{outcome}_human"]).mean()) for outcome in outcomes}


def estimate_sensitivities_with_messages(
    frame: pd.DataFrame,
    human_frame: Optional[pd.DataFrame] = None,
    fact_frame: Optional[pd.DataFrame] = None,
) -> Tuple[Dict[str, float], List[str]]:
    """Calculate every sensitivity independently and surface non-estimable subsets."""
    outputs: Dict[str, float] = {}
    messages: List[str] = []

    def add(prefix: str, estimator: Callable[[], Dict[str, float]]) -> None:
        """Add one estimate surface or retain its explicit failure message."""
        try:
            outputs.update(_prefixed(prefix, estimator()))
        except ValueError as error:
            messages.append(f"{prefix}: {error}")

    primary_from_full = estimate_primary_contrasts(frame)
    primary_only = estimate_primary_contrasts(frame.loc[frame["integrity"] == "absent"])
    if primary_from_full != primary_only:
        raise ValueError("primary estimates changed when mitigation rows were excluded")
    outputs.update(_prefixed("mitigation_excluded", primary_only))
    for model_id in sorted(frame["model_id"].unique()):
        add(f"model={model_id}", partial(estimate_confirmatory_contrasts, frame.loc[frame["model_id"] == model_id]))
    for use_case_id in sorted(frame["use_case_id"].unique()):
        add(
            f"leave_use_case_out={use_case_id}",
            partial(estimate_confirmatory_contrasts, frame.loc[frame["use_case_id"] != use_case_id]),
        )
    add("budget_compliant_only", partial(estimate_confirmatory_contrasts, frame.loc[frame["budget_compliant"]]))
    add("refusals_excluded", partial(estimate_confirmatory_contrasts, frame.loc[~frame["refusal"]]))
    if fact_frame is None:
        messages.append("binary_disclosure: no locked fact-level analysis input supplied")
    else:
        add("binary_full_vs_not_full", partial(_binary_threshold_estimates, frame, fact_frame, "full"))
        add("binary_present_vs_omitted", partial(_binary_threshold_estimates, frame, fact_frame, "present"))
    add("response_length_mediation", partial(_response_length_mediation, frame))
    if human_frame is None:
        messages.append("human_only_validation: no locked human-reference analysis input supplied")
    else:
        add("human_only_validation", partial(_human_reference_differences, frame, human_frame))
    return outputs, messages
