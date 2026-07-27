"""Paired estimates and scenario-cluster intervals for exploratory studies."""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from src.data_models.scoring import COMPOSITE_DOMAIN_COLUMNS

OUTCOMES = {
    "composite": "selective_risk_communication_score",
    **{domain.value: column for domain, column in COMPOSITE_DOMAIN_COLUMNS.items()},
}


def material_priority_scenario_effects(frame: pd.DataFrame) -> pd.DataFrame:
    """Return concerned-minus-neutral effects under concise system guidance."""
    if set(frame["word_budget"]) != {"concise"} or set(frame["expressed_concern"]) != {"neutral", "concerned"}:
        raise ValueError("material_priority_v1 requires concise-instruction neutral and concerned cells only")
    columns = list(OUTCOMES.values())
    table = frame.groupby(["scenario_id", "use_case_id", "model_id", "expressed_concern"], observed=True)[columns].mean().unstack("expressed_concern")
    if set(table.columns.get_level_values("expressed_concern")) != {"neutral", "concerned"}:
        raise ValueError("material-priority pairing is incomplete")
    effects = table.xs("concerned", axis=1, level="expressed_concern") - table.xs("neutral", axis=1, level="expressed_concern")
    effects = effects.rename(columns={column: name for name, column in OUTCOMES.items()})
    return effects.groupby(["scenario_id", "use_case_id"], observed=True).mean().reset_index()


def brevity_locus_scenario_effects(frame: pd.DataFrame, primary_reference: pd.DataFrame) -> pd.DataFrame:
    """Return user-requested minus system-requested concision effects."""
    if set(frame["word_budget"]) != {"user_concise"} or set(frame["expressed_concern"]) != {"neutral"}:
        raise ValueError("brevity_locus_v1 requires only its user-concise neutral cell")
    reference = primary_reference.loc[(primary_reference["word_budget"] == "concise") & (primary_reference["expressed_concern"] == "neutral")]
    keys = ["scenario_id", "use_case_id", "model_id"]
    columns = list(OUTCOMES.values())
    brevity = frame.groupby(keys, observed=True)[columns].mean()
    tight_reference = reference.groupby(keys, observed=True)[columns].mean()
    paired = brevity.join(tight_reference, how="inner", lsuffix="__brevity", rsuffix="__tight")
    if len(paired) != 60:
        raise ValueError("brevity-locus comparison requires all 60 scenario-model pairs")
    effects = pd.DataFrame(index=paired.index)
    for outcome_name, column in OUTCOMES.items():
        effects[outcome_name] = paired[f"{column}__brevity"] - paired[f"{column}__tight"]
    return effects.groupby(["scenario_id", "use_case_id"], observed=True).mean().reset_index()


def scenario_cluster_estimates(
    scenario_effects: pd.DataFrame,
    draws: int = 10_000,
    seed: int = 7,
) -> Tuple[Dict[str, float], Dict[str, Tuple[float, float]]]:
    """Average paired effects and bootstrap scenarios within each use case without p-values."""
    if draws < 1:
        raise ValueError("exploratory bootstrap draws must be positive")
    if len(scenario_effects) != 20 or scenario_effects["use_case_id"].nunique() != 10:
        raise ValueError("exploratory analysis requires 20 scenarios across ten use cases")
    outcome_columns = [column for column in scenario_effects if column not in {"scenario_id", "use_case_id"}]
    estimates = {column: float(scenario_effects[column].mean()) for column in outcome_columns}
    generator = np.random.default_rng(seed)
    samples = np.empty((draws, len(outcome_columns)), dtype=float)
    grouped = [group[outcome_columns].to_numpy(dtype=float) for _, group in scenario_effects.groupby("use_case_id", observed=True)]
    for draw in range(draws):
        selected = np.concatenate(
            [values[generator.integers(0, len(values), size=len(values))] for values in grouped],
            axis=0,
        )
        samples[draw] = selected.mean(axis=0)
    intervals = {
        column: (float(np.quantile(samples[:, index], 0.025)), float(np.quantile(samples[:, index], 0.975)))
        for index, column in enumerate(outcome_columns)
    }
    return estimates, intervals
