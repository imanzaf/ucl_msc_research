"""The two prespecified scenario-level paired contrasts and Holm correction."""

from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean
from typing import Dict, List, Sequence

from pydantic import Field

from srcv2.common import ImmutableModel
from srcv2.models.enums import Affect, ExactFactBudget


class UserStateScore(ImmutableModel):
    """Store one frozen D outcome for user-state aggregation."""

    scenario_id: str
    use_case_id: str
    model_slug: str
    affect: Affect
    query_length: str
    signed_directional_gap: float = Field(ge=-1, le=1)


class BudgetScore(ImmutableModel):
    """Store one exact-selection D outcome for the ordered budget contrast."""

    scenario_id: str
    use_case_id: str
    model_slug: str
    exact_fact_budget: ExactFactBudget
    signed_directional_gap: float = Field(ge=-1, le=1)


class ScenarioContrast(ImmutableModel):
    """Store one scenario-clustered contrast for bootstrap inference."""

    scenario_id: str
    use_case_id: str
    value: float


class BootstrapInterval(ImmutableModel):
    """Report a reproducible use-case-stratified scenario bootstrap interval."""

    estimate: float
    lower: float
    upper: float
    confidence_level: float
    bootstrap_iterations: int
    random_seed: int


class ConfirmatoryTest(ImmutableModel):
    """Report one prespecified contrast before and after Holm correction."""

    test_name: str
    estimate: float
    raw_p_value: float = Field(ge=0, le=1)
    holm_p_value: float = Field(ge=0, le=1)
    interval: BootstrapInterval
    scenario_count: int
    analysis_model_slugs: List[str] = Field(min_length=1)


def anxious_neutral_contrasts(scores: Sequence[UserStateScore]) -> List[ScenarioContrast]:
    """Average anxious-minus-neutral D across query length and model within scenarios."""
    grouped: Dict[tuple[str, str, str], Dict[Affect, List[float]]] = defaultdict(lambda: defaultdict(list))
    for score in scores:
        if score.affect in {Affect.ANXIOUS, Affect.NEUTRAL}:
            grouped[(score.scenario_id, score.use_case_id, score.model_slug)][score.affect].append(score.signed_directional_gap)
    by_scenario: Dict[tuple[str, str], List[float]] = defaultdict(list)
    for (scenario_id, use_case_id, _), values in grouped.items():
        if len(values[Affect.ANXIOUS]) != 2 or len(values[Affect.NEUTRAL]) != 2:
            raise ValueError("each scenario-model requires two anxious and two neutral user-state outcomes")
        by_scenario[(scenario_id, use_case_id)].append(mean(values[Affect.ANXIOUS]) - mean(values[Affect.NEUTRAL]))
    if len(by_scenario) != 30 or any(len(values) != 7 for values in by_scenario.values()):
        raise ValueError("anxious-neutral contrast requires all thirty scenarios and seven models")
    return [ScenarioContrast(scenario_id=key[0], use_case_id=key[1], value=mean(values)) for key, values in sorted(by_scenario.items())]


def complete_budget_models(scores: Sequence[BudgetScore]) -> List[str]:
    """Identify a fixed model panel with one neutral k=2, k=4, and k=6 score in every scenario."""
    grouped: Dict[tuple[str, str, str], Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    for score in scores:
        if score.exact_fact_budget in {2, 4, 6}:
            grouped[(score.scenario_id, score.use_case_id, score.model_slug)][score.exact_fact_budget].append(score.signed_directional_gap)
    if any(len(values) > 1 for group in grouped.values() for values in group.values()):
        raise ValueError("each scenario-model-budget coordinate can occur only once")
    scenario_keys = {(scenario_id, use_case_id) for scenario_id, use_case_id, _ in grouped}
    if len(scenario_keys) != 30:
        raise ValueError("ordered budget contrast requires all thirty scenarios")
    model_slugs = {model_slug for _, _, model_slug in grouped}
    complete = [
        model_slug
        for model_slug in sorted(model_slugs)
        if all(
            all(len(grouped[(scenario_id, use_case_id, model_slug)][budget]) == 1 for budget in (2, 4, 6))
            for scenario_id, use_case_id in scenario_keys
        )
    ]
    if not complete:
        raise ValueError("ordered budget contrast requires at least one model with complete exact-k triplets across all scenarios")
    return complete


def ordered_budget_contrasts(scores: Sequence[BudgetScore]) -> List[ScenarioContrast]:
    """Compute k=2 minus k=6 over the fixed model panel with complete scenario triplets."""
    grouped: Dict[tuple[str, str, str], Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    for score in scores:
        if score.exact_fact_budget in {2, 4, 6}:
            grouped[(score.scenario_id, score.use_case_id, score.model_slug)][score.exact_fact_budget].append(score.signed_directional_gap)
    complete_models = complete_budget_models(scores)
    by_scenario: Dict[tuple[str, str], List[float]] = defaultdict(list)
    for (scenario_id, use_case_id, model_slug), values in grouped.items():
        if model_slug not in complete_models:
            continue
        by_scenario[(scenario_id, use_case_id)].append(values[2][0] - values[6][0])
    if len(by_scenario) != 30 or any(len(values) != len(complete_models) for values in by_scenario.values()):
        raise ValueError("ordered budget contrast requires the fixed complete model panel in all thirty scenarios")
    return [ScenarioContrast(scenario_id=key[0], use_case_id=key[1], value=mean(values)) for key, values in sorted(by_scenario.items())]


def sign_flip_p_value(values: Sequence[float], iterations: int = 99999, random_seed: int = 410506) -> float:
    """Calculate a reproducible two-sided paired randomization p-value."""
    if not values:
        raise ValueError("paired randomization requires at least one contrast")
    observed = abs(mean(values))
    if observed == 0:
        return 1.0
    randomizer = random.Random(random_seed)
    exceedances = 0
    for _ in range(iterations):
        permuted = abs(mean(value if randomizer.random() < 0.5 else -value for value in values))
        exceedances += permuted >= observed
    return (exceedances + 1) / (iterations + 1)


def holm_adjust(p_values: Dict[str, float]) -> Dict[str, float]:
    """Apply step-down Holm family-wise correction to exactly two confirmatory tests."""
    if len(p_values) != 2 or any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("the confirmatory family must contain exactly two valid p-values")
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: Dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * value))
        adjusted[name] = running
    return adjusted


def run_confirmatory_tests(
    user_state_scores: Sequence[UserStateScore],
    budget_scores: Sequence[BudgetScore],
    bootstrap_iterations: int = 10000,
    random_seed: int = 410506,
) -> List[ConfirmatoryTest]:
    """Run only the anxious-neutral and ordered-budget confirmatory tests."""
    from srcv2.analysis.resampling import stratified_cluster_bootstrap

    contrasts = {
        "anxious_vs_neutral_D": anxious_neutral_contrasts(user_state_scores),
        "ordered_k6_k4_k2_selection_D": ordered_budget_contrasts(budget_scores),
    }
    raw = {name: sign_flip_p_value([item.value for item in values], random_seed=random_seed) for name, values in contrasts.items()}
    adjusted = holm_adjust(raw)
    analysis_models = {
        "anxious_vs_neutral_D": sorted({score.model_slug for score in user_state_scores}),
        "ordered_k6_k4_k2_selection_D": complete_budget_models(budget_scores),
    }
    return [
        ConfirmatoryTest(
            test_name=name,
            estimate=mean(item.value for item in values),
            raw_p_value=raw[name],
            holm_p_value=adjusted[name],
            interval=stratified_cluster_bootstrap(values, iterations=bootstrap_iterations, random_seed=random_seed),
            scenario_count=len(values),
            analysis_model_slugs=analysis_models[name],
        )
        for name, values in contrasts.items()
    ]
