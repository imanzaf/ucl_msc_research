"""Scenario-level paired tests with research-question-specific multiplicity control."""

from __future__ import annotations

import random
from collections import defaultdict
from statistics import mean
from typing import Dict, List, Sequence

from pydantic import Field

from srcv2.analysis.commercial_interest import CommercialInterestContrast
from srcv2.common import ImmutableModel
from srcv2.models.enums import Affect, AnalysisInterpretation, CommercialInterestTask, ExactFactBudget, MultiplicityFamily, OwnershipRole
from srcv2.models.experiments import InformationBudgetCell, UserStateCell
from srcv2.models.scoring import ResponseOutcomesRecord

COMMERCIAL_TEST_NAMES = (
    "commercial_standard_D",
    "commercial_single_fact_D",
    "commercial_exact_k4_D",
    "commercial_exact_k2_D",
    "commercial_ownership_flip_D",
)

TEST_NAMES_BY_FAMILY = {
    MultiplicityFamily.RQ1: COMMERCIAL_TEST_NAMES,
    MultiplicityFamily.RQ2: ("anxious_vs_neutral_D",),
    MultiplicityFamily.RQ3: ("ordered_k6_k4_k2_selection_D",),
}
TEST_FAMILY_BY_NAME = {test_name: family for family, test_names in TEST_NAMES_BY_FAMILY.items() for test_name in test_names}


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
    """Report one primary contrast with its within-research-question p-value."""

    interpretation: AnalysisInterpretation = AnalysisInterpretation.CONFIRMATORY
    test_name: str
    estimate: float
    raw_p_value: float = Field(ge=0, le=1)
    within_family_p_value: float = Field(ge=0, le=1)
    multiplicity_family: MultiplicityFamily
    multiplicity_family_size: int = Field(ge=1)
    interval: BootstrapInterval
    scenario_count: int
    analysis_model_slugs: List[str] = Field(min_length=1)


def user_state_scores_from_outcomes(outcomes: Sequence[ResponseOutcomesRecord]) -> List[UserStateScore]:
    """Extract user-state directional scores from frozen response outcomes."""
    scores: List[UserStateScore] = []
    for outcome in outcomes:
        if not isinstance(outcome.cell, UserStateCell):
            raise ValueError("user-state confirmatory inputs require user-state response outcomes")
        scores.append(
            UserStateScore(
                scenario_id=outcome.scenario_id,
                use_case_id=outcome.use_case_id,
                model_slug=outcome.model_slug,
                affect=outcome.cell.affect,
                query_length=outcome.cell.query_length.value,
                signed_directional_gap=outcome.prose_selection.signed_directional_gap,
            )
        )
    return scores


def budget_scores_from_outcomes(outcomes: Sequence[ResponseOutcomesRecord]) -> List[BudgetScore]:
    """Extract neutral exact-selection directional scores from frozen response outcomes."""
    scores: List[BudgetScore] = []
    for outcome in outcomes:
        if not isinstance(outcome.cell, InformationBudgetCell):
            raise ValueError("budget confirmatory inputs require information-budget response outcomes")
        if outcome.cell.affect != Affect.NEUTRAL:
            continue
        if outcome.exact_selection is None:
            raise ValueError("neutral budget confirmatory inputs require usable exact selections")
        scores.append(
            BudgetScore(
                scenario_id=outcome.scenario_id,
                use_case_id=outcome.use_case_id,
                model_slug=outcome.model_slug,
                exact_fact_budget=outcome.cell.exact_fact_budget,
                signed_directional_gap=outcome.exact_selection.signed_directional_gap,
            )
        )
    return scores


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


def _commercial_test_name(contrast: CommercialInterestContrast) -> str | None:
    """Map one commercial prose-direction contrast to its confirmatory task name."""
    if contrast.task == CommercialInterestTask.STANDARD and contrast.outcome_name == "prose_signed_directional_gap":
        return "commercial_standard_D"
    if contrast.task == CommercialInterestTask.SINGLE_FACT and contrast.outcome_name == "prose_signed_directional_gap":
        return "commercial_single_fact_D"
    if contrast.task == CommercialInterestTask.EXACT_BUDGET and contrast.outcome_name == "prose_signed_directional_gap":
        if contrast.exact_fact_budget == ExactFactBudget.FACTS_4:
            return "commercial_exact_k4_D"
        if contrast.exact_fact_budget == ExactFactBudget.FACTS_2:
            return "commercial_exact_k2_D"
    if contrast.task == CommercialInterestTask.OWNERSHIP_FLIP and contrast.outcome_name == "prose_option_coordinate_signed_directional_gap":
        return "commercial_ownership_flip_D"
    return None


def _owner_relative_commercial_value(contrast: CommercialInterestContrast) -> float:
    """Recode fixed-option ownership contrasts so positive values favour the employer."""
    if contrast.task != CommercialInterestTask.OWNERSHIP_FLIP:
        return contrast.treatment_minus_control
    if contrast.ownership_role == OwnershipRole.EMPLOYER_OWNS_A:
        return contrast.treatment_minus_control
    if contrast.ownership_role == OwnershipRole.EMPLOYER_OWNS_B:
        return -contrast.treatment_minus_control
    raise ValueError("ownership-flip confirmatory contrasts require employer ownership of option A or B")


def commercial_directional_contrasts(contrasts: Sequence[CommercialInterestContrast]) -> Dict[str, List[ScenarioContrast]]:
    """Average matched commercial instruction effects within each scenario and task."""
    grouped: Dict[tuple[str, str, str], List[float]] = defaultdict(list)
    for contrast in contrasts:
        test_name = _commercial_test_name(contrast)
        if test_name is None:
            continue
        grouped[(test_name, contrast.scenario_id, contrast.use_case_id)].append(_owner_relative_commercial_value(contrast))

    scenario_contrasts: Dict[str, List[ScenarioContrast]] = {name: [] for name in COMMERCIAL_TEST_NAMES}
    for (test_name, scenario_id, use_case_id), values in sorted(grouped.items()):
        expected_count = 84 if test_name == "commercial_ownership_flip_D" else 21
        if len(values) != expected_count:
            raise ValueError(f"{test_name} requires {expected_count} matched coordinates per scenario")
        scenario_contrasts[test_name].append(ScenarioContrast(scenario_id=scenario_id, use_case_id=use_case_id, value=mean(values)))

    expected_scenarios = {
        "commercial_standard_D": 30,
        "commercial_single_fact_D": 30,
        "commercial_exact_k4_D": 30,
        "commercial_exact_k2_D": 30,
        "commercial_ownership_flip_D": 11,
    }
    for test_name, expected_count in expected_scenarios.items():
        if len(scenario_contrasts[test_name]) != expected_count:
            raise ValueError(f"{test_name} requires {expected_count} complete scenario contrasts")
    return scenario_contrasts


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
    """Apply step-down Holm family-wise correction to a confirmatory family."""
    if not p_values or any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("the confirmatory family must contain valid p-values")
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: Dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, round((total - index) * value, 12)))
        adjusted[name] = running
    return adjusted


def adjust_within_research_questions(p_values: Dict[str, float]) -> Dict[str, float]:
    """Apply Holm separately to RQ1 and the singleton RQ2 and RQ3 families."""
    expected_names = set(TEST_FAMILY_BY_NAME)
    if set(p_values) != expected_names:
        missing = sorted(expected_names - set(p_values))
        unexpected = sorted(set(p_values) - expected_names)
        raise ValueError(f"primary p-values do not match the declared research-question families; missing={missing}, unexpected={unexpected}")
    adjusted: Dict[str, float] = {}
    for test_names in TEST_NAMES_BY_FAMILY.values():
        family_p_values = {test_name: p_values[test_name] for test_name in test_names}
        adjusted.update(holm_adjust(family_p_values))
    return adjusted


def run_confirmatory_tests(
    user_state_scores: Sequence[UserStateScore],
    budget_scores: Sequence[BudgetScore],
    commercial_contrasts: Sequence[CommercialInterestContrast],
    bootstrap_iterations: int = 10000,
    random_seed: int = 410506,
) -> List[ConfirmatoryTest]:
    """Run five RQ1 and singleton RQ2 and RQ3 primary directional tests."""
    from srcv2.analysis.resampling import stratified_cluster_bootstrap

    contrasts = commercial_directional_contrasts(commercial_contrasts)
    contrasts["anxious_vs_neutral_D"] = anxious_neutral_contrasts(user_state_scores)
    contrasts["ordered_k6_k4_k2_selection_D"] = ordered_budget_contrasts(budget_scores)
    if set(contrasts) != set(TEST_FAMILY_BY_NAME):
        raise ValueError("the primary tests must contain five RQ1 and one test for each of RQ2 and RQ3")
    raw = {name: sign_flip_p_value([item.value for item in values], random_seed=random_seed) for name, values in contrasts.items()}
    adjusted = adjust_within_research_questions(raw)
    analysis_models = {
        **{
            name: sorted({contrast.model_slug for contrast in commercial_contrasts if _commercial_test_name(contrast) == name})
            for name in COMMERCIAL_TEST_NAMES
        },
        "anxious_vs_neutral_D": sorted({score.model_slug for score in user_state_scores}),
        "ordered_k6_k4_k2_selection_D": complete_budget_models(budget_scores),
    }
    return [
        ConfirmatoryTest(
            test_name=name,
            estimate=mean(item.value for item in values),
            raw_p_value=raw[name],
            within_family_p_value=adjusted[name],
            multiplicity_family=TEST_FAMILY_BY_NAME[name],
            multiplicity_family_size=len(TEST_NAMES_BY_FAMILY[TEST_FAMILY_BY_NAME[name]]),
            interval=stratified_cluster_bootstrap(values, iterations=bootstrap_iterations, random_seed=random_seed),
            scenario_count=len(values),
            analysis_model_slugs=analysis_models[name],
        )
        for name, values in contrasts.items()
    ]
