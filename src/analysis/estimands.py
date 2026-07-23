"""Calculate the two confirmatory scenario-paired composite contrasts."""

from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd

from src.data_models.scoring import AnalysisInputRow, EvaluationCheckpoint

CONFIRMATORY_NAMES = {"H1", "H2"}


def rows_to_frame(
    rows: Iterable[AnalysisInputRow],
    checkpoint: EvaluationCheckpoint = EvaluationCheckpoint.INITIAL,
) -> pd.DataFrame:
    """Flatten validated rows for one checkpoint into the locked analysis frame."""
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
                "source_order": row.source_order.value,
                "cue_template_id": row.cue_template_id,
                "word_budget": row.word_budget.value,
                "expressed_concern": row.expressed_concern.value,
                "selective_risk_communication_score": float(metrics.selective_risk_communication_score),
                "coverage_asymmetry": float(metrics.coverage_asymmetry),
                "specificity_asymmetry": float(metrics.specificity_asymmetry),
                "framing_reassurance_distortion": float(metrics.framing_reassurance_distortion),
                "salience_asymmetry": float(metrics.salience_asymmetry),
                "factual_integrity_failure": float(metrics.factual_integrity_failure),
                "pairwise_disclosure_gap": float(metrics.pairwise_disclosure_gap),
                "coverage_signed_gap": float(metrics.coverage_signed_gap),
                "coverage_reverse_gap": float(metrics.coverage_reverse_gap),
                "specificity_signed_gap": float(metrics.specificity_signed_gap),
                "specificity_reverse_gap": float(metrics.specificity_reverse_gap),
                "ordering_signed_gap": float(metrics.ordering_signed_gap),
                "ordering_reverse_gap": float(metrics.ordering_reverse_gap),
                "emphasis_signed_gap": float(metrics.emphasis_signed_gap),
                "emphasis_reverse_gap": float(metrics.emphasis_reverse_gap),
                "adverse_coverage": float(metrics.adverse_coverage),
                "unsupported_reassurance": float(metrics.unsupported_reassurance),
                "budget_compliant": metrics.budget_compliant,
                "refusal": metrics.refusal,
                "material_coverage": float(metrics.material_coverage),
                "response_word_count": metrics.response_word_count,
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
    """Calculate a within-group high-minus-low factor contrast and average groups."""
    means = frame.groupby([*group_columns, factor], observed=True)[outcome].mean().unstack(factor)
    if high not in means.columns or low not in means.columns:
        raise ValueError(f"paired contrast requires {factor} levels {high} and {low}")
    differences = (means[high] - means[low]).dropna()
    if differences.empty:
        raise ValueError(f"paired contrast for {factor} has no complete groups")
    return float(differences.mean())


def estimate_confirmatory_contrasts(frame: pd.DataFrame) -> Dict[str, float]:
    """Estimate H1 budget and H2 expressed-concern effects on the initial composite."""
    required = {
        "scenario_id",
        "model_id",
        "word_budget",
        "expressed_concern",
        "selective_risk_communication_score",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("analysis frame lacks required columns: " + ", ".join(sorted(missing)))
    base = ["scenario_id", "model_id"]
    h1 = _paired_factor_difference(
        frame,
        "selective_risk_communication_score",
        "word_budget",
        "tight",
        "ample",
        [*base, "expressed_concern"],
    )
    h2 = _paired_factor_difference(
        frame,
        "selective_risk_communication_score",
        "expressed_concern",
        "concerned",
        "neutral",
        [*base, "word_budget"],
    )
    return {"H1": h1, "H2": h2}


def estimate_outcome_contrasts(frame: pd.DataFrame, outcome: str) -> Dict[str, float]:
    """Estimate the same paired H1/H2 contrasts for a prespecified secondary outcome."""
    if outcome not in frame:
        raise ValueError(f"analysis frame lacks secondary outcome: {outcome}")
    transformed = frame.copy()
    transformed["selective_risk_communication_score"] = transformed[outcome]
    return estimate_confirmatory_contrasts(transformed)


def scenario_level_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one complete two-estimand contrast vector per scenario."""
    records: List[Dict[str, object]] = []
    for scenario_id, scenario_frame in frame.groupby("scenario_id", observed=True):
        use_case_ids = scenario_frame["use_case_id"].unique()
        if len(use_case_ids) != 1:
            raise ValueError("one scenario cannot span multiple use cases")
        records.append({"scenario_id": scenario_id, "use_case_id": use_case_ids[0], **estimate_confirmatory_contrasts(scenario_frame)})
    result = pd.DataFrame.from_records(records)
    if len(result) != 40 or result["use_case_id"].nunique() != 10:
        raise ValueError("scenario-level contrasts require all 40 scenarios across ten use cases")
    return result
