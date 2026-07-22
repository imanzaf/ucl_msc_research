"""Calculate primary and secondary scenario-paired contrasts."""

from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd

from src.data_models.scoring import AnalysisInputRow, EvaluationCheckpoint


def rows_to_frame(rows: Iterable[AnalysisInputRow]) -> pd.DataFrame:
    """Flatten validated initial-checkpoint analysis rows into a pandas frame."""
    records: List[Dict[str, object]] = []
    for row in rows:
        if row.metrics.checkpoint != EvaluationCheckpoint.INITIAL:
            continue
        records.append(
            {
                "run_unit_id": row.run_unit_id,
                "scenario_id": row.scenario_id,
                "use_case_id": row.use_case_id,
                "model_id": row.model_id,
                "source_order": row.source_order,
                "word_budget": row.word_budget,
                "emotional_cue": row.emotional_cue,
                "integrity": row.integrity,
                "pairwise_disclosure_gap": float(row.metrics.pairwise_disclosure_gap),
                "adverse_coverage": float(row.metrics.adverse_coverage),
                "unsupported_reassurance": float(row.metrics.unsupported_reassurance),
                "budget_compliant": row.metrics.budget_compliant,
                "refusal": row.metrics.refusal,
                "generic_risk_disclaimer": row.metrics.generic_risk_disclaimer,
                "false_claim_count": row.metrics.false_claim_count,
                "material_coverage": float(row.metrics.material_coverage),
                "response_word_count": row.metrics.response_word_count,
            }
        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError("analysis requires initial-checkpoint rows")
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


def estimate_primary_contrasts(frame: pd.DataFrame) -> Dict[str, float]:
    """Estimate the three integrity-absent primary contrasts from paired blocks."""
    required_columns = {
        "scenario_id",
        "use_case_id",
        "model_id",
        "source_order",
        "word_budget",
        "emotional_cue",
        "integrity",
        "pairwise_disclosure_gap",
        "adverse_coverage",
        "unsupported_reassurance",
    }
    missing = required_columns - set(frame.columns)
    if missing:
        raise ValueError("analysis frame lacks required columns: " + ", ".join(sorted(missing)))
    primary = frame.loc[frame["integrity"] == "absent"]
    base_groups = ["scenario_id", "model_id", "source_order"]
    h1 = _paired_factor_difference(
        primary,
        "pairwise_disclosure_gap",
        "word_budget",
        "tight",
        "ample",
        [*base_groups, "emotional_cue"],
    )
    h2a = _paired_factor_difference(
        primary,
        "adverse_coverage",
        "emotional_cue",
        "worried",
        "neutral",
        [*base_groups, "word_budget"],
    )
    h2b = _paired_factor_difference(
        primary,
        "unsupported_reassurance",
        "emotional_cue",
        "worried",
        "neutral",
        [*base_groups, "word_budget"],
    )
    return {"H1": h1, "H2a": h2a, "H2b": h2b}


def estimate_mitigation_contrasts(frame: pd.DataFrame) -> Dict[str, float]:
    """Estimate the two secondary integrity contrasts from matched subset blocks."""
    base_groups = ["scenario_id", "model_id", "source_order"]
    tight = frame.loc[frame["word_budget"] == "tight"]
    m1 = _paired_factor_difference(
        tight,
        "pairwise_disclosure_gap",
        "integrity",
        "targeted",
        "absent",
        [*base_groups, "emotional_cue"],
    )
    means = frame.groupby([*base_groups, "emotional_cue", "integrity", "word_budget"], observed=True)["pairwise_disclosure_gap"].mean()
    complete = means.unstack(["integrity", "word_budget"])
    required_cells = [("targeted", "tight"), ("targeted", "ample"), ("absent", "tight"), ("absent", "ample")]
    if any(cell not in complete.columns for cell in required_cells):
        raise ValueError("M2 interaction requires all integrity × word-budget cells")
    m2_values = (
        (complete[("targeted", "tight")] - complete[("targeted", "ample")]) - (complete[("absent", "tight")] - complete[("absent", "ample")])
    ).dropna()
    if m2_values.empty:
        raise ValueError("M2 interaction has no complete scenario blocks")
    return {"M1": m1, "M2": float(m2_values.mean())}


def estimate_confirmatory_contrasts(frame: pd.DataFrame) -> Dict[str, float]:
    """Estimate the three preregistered primary contrasts from paired scenario blocks."""
    return estimate_primary_contrasts(frame)


def scenario_level_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one complete three-estimand contrast vector per evaluation scenario."""
    records: List[Dict[str, object]] = []
    for scenario_id, scenario_frame in frame.groupby("scenario_id", observed=True):
        use_case_ids = scenario_frame["use_case_id"].unique()
        if len(use_case_ids) != 1:
            raise ValueError("one scenario cannot span multiple use cases")
        records.append(
            {
                "scenario_id": scenario_id,
                "use_case_id": use_case_ids[0],
                **estimate_confirmatory_contrasts(scenario_frame),
            }
        )
    result = pd.DataFrame.from_records(records)
    if len(result) != 40 or result["use_case_id"].nunique() != 10:
        raise ValueError("scenario-level contrasts require all 40 scenarios across ten use cases")
    return result
