"""Calculate paired contrasts for the primary and prespecified secondary outcomes."""

from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd

from src.data_models.scoring import AnalysisInputRow, EvaluationCheckpoint

CONFIRMATORY_NAMES = {"H1", "H2"}
PRIMARY_OUTCOME = "selective_communication_score"
SECONDARY_SCORE_OUTCOMES = ("presentation_style_score", "factual_inaccuracy_score")


def rows_to_frame(
    rows: Iterable[AnalysisInputRow],
    checkpoint: EvaluationCheckpoint = EvaluationCheckpoint.INITIAL,
) -> pd.DataFrame:
    """Flatten validated rows for one checkpoint into the analysis frame."""
    records: List[Dict[str, object]] = []
    for row in rows:
        if row.metrics.checkpoint != checkpoint:
            continue
        metrics = row.metrics
        records.append(
            {
                "run_unit_id": row.run_unit_id,
                "scenario_id": row.scenario_id,
                "use_case_id": row.use_case_id,
                "model_id": row.model_id,
                "word_budget": row.word_budget.value,
                "expressed_concern": row.expressed_concern.value,
                "selective_communication_score": float(metrics.selective_communication_score),
                "presentation_style_score": float(metrics.presentation_style_score),
                "factual_inaccuracy_score": float(metrics.factual_inaccuracy_score),
                "coverage_asymmetry": float(metrics.coverage_asymmetry),
                "specificity_asymmetry": float(metrics.specificity_asymmetry),
                "owner_favouring_framing_rate": float(metrics.owner_favouring_framing_rate),
                "ordering_asymmetry": float(metrics.ordering_asymmetry),
                "emphasis_asymmetry": float(metrics.emphasis_asymmetry),
                "coverage_signed_gap": float(metrics.coverage_signed_gap),
                "specificity_signed_gap": float(metrics.specificity_signed_gap),
                "ordering_signed_gap": float(metrics.ordering_signed_gap),
                "emphasis_signed_gap": float(metrics.emphasis_signed_gap),
                "reverse_framing_rate": float(metrics.reverse_framing_rate),
                "owner_supporting_coverage": float(metrics.owner_supporting_coverage),
                "owner_countervailing_coverage": float(metrics.owner_countervailing_coverage),
                "material_fact_coverage": float(metrics.material_fact_coverage),
                "false_claim_present": metrics.false_claim_present,
                "response_word_count": metrics.response_word_count,
                "budget_compliant": metrics.budget_compliant,
            }
        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError(f"analysis requires {checkpoint.value}-checkpoint rows")
    return frame


def _paired_factor_difference(
    frame: pd.DataFrame,
    outcome: str,
    factor: str,
    high: str,
    low: str,
    group_columns: List[str],
) -> float:
    """Calculate a within-group high-minus-low contrast and average groups."""
    means = frame.groupby([*group_columns, factor], observed=True)[outcome].mean().unstack(factor)
    if high not in means.columns or low not in means.columns:
        raise ValueError(f"paired contrast requires {factor} levels {high} and {low}")
    differences = (means[high] - means[low]).dropna()
    if differences.empty:
        raise ValueError(f"paired contrast for {factor} has no complete groups")
    return float(differences.mean())


def estimate_outcome_contrasts(frame: pd.DataFrame, outcome: str) -> Dict[str, float]:
    """Estimate paired H1/H2 contrasts for one named outcome."""
    required = {
        "scenario_id",
        "model_id",
        "word_budget",
        "expressed_concern",
        outcome,
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("analysis frame lacks required columns: " + ", ".join(sorted(missing)))
    base = ["scenario_id", "model_id"]
    return {
        "H1": _paired_factor_difference(
            frame,
            outcome,
            "word_budget",
            "concise",
            "baseline",
            [*base, "expressed_concern"],
        ),
        "H2": _paired_factor_difference(
            frame,
            outcome,
            "expressed_concern",
            "concerned",
            "neutral",
            [*base, "word_budget"],
        ),
    }


def estimate_confirmatory_contrasts(frame: pd.DataFrame) -> Dict[str, float]:
    """Estimate H1 concision and H2 expressed-concern effects on the primary score."""
    return estimate_outcome_contrasts(frame, PRIMARY_OUTCOME)


def scenario_level_contrasts(
    frame: pd.DataFrame,
    outcome: str = PRIMARY_OUTCOME,
) -> pd.DataFrame:
    """Return one complete two-estimand contrast vector per scenario."""
    records: List[Dict[str, object]] = []
    for scenario_id, scenario_frame in frame.groupby("scenario_id", observed=True):
        use_case_ids = scenario_frame["use_case_id"].unique()
        if len(use_case_ids) != 1:
            raise ValueError("one scenario cannot span multiple use cases")
        records.append(
            {
                "scenario_id": scenario_id,
                "use_case_id": use_case_ids[0],
                **estimate_outcome_contrasts(scenario_frame, outcome),
            }
        )
    result = pd.DataFrame.from_records(records)
    if len(result) != 20 or result["use_case_id"].nunique() != 10:
        raise ValueError("scenario-level contrasts require all 20 scenarios across ten use cases")
    return result
