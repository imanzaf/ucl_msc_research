"""Confirmatory contrasts, Holm correction, bootstrap, and descriptive reporting tests."""

from __future__ import annotations

from srcv2.analysis.commercial_interest import (
    CommercialInterestContrast,
    CommercialInterestObservation,
    paired_instruction_contrasts,
    summarize_commercial_interest_contrasts,
)
from srcv2.analysis.confirmatory import (
    BudgetScore,
    ScenarioContrast,
    UserStateScore,
    anxious_neutral_contrasts,
    commercial_directional_contrasts,
    complete_budget_models,
    holm_adjust,
    ordered_budget_contrasts,
)
from srcv2.analysis.descriptive import GroupObservation, summarize_groups
from srcv2.analysis.resampling import stratified_cluster_bootstrap
from srcv2.models.enums import Affect, CommercialInterestInstruction, CommercialInterestTask, ExactFactBudget, OwnershipRole


def _contrasts() -> list[ScenarioContrast]:
    """Build six use-case strata with five scenario clusters each."""
    return [
        ScenarioContrast(scenario_id=f"UC{use_case}_R{scenario}", use_case_id=f"UC{use_case}", value=(scenario - 3) / 10)
        for use_case in range(1, 7)
        for scenario in range(1, 6)
    ]


def test_holm_correction_is_step_down_for_the_declared_family() -> None:
    """Correct all declared confirmatory p-values with the step-down rule."""
    adjusted = holm_adjust({"commercial": 0.005, "anxious": 0.01, "budget": 0.04})
    assert adjusted == {"commercial": 0.015, "anxious": 0.02, "budget": 0.04}


def test_confirmatory_contrasts_require_the_seven_model_panel() -> None:
    """Aggregate both confirmatory outcomes across all thirty scenarios and seven models."""
    user_state_scores = [
        UserStateScore(
            scenario_id=f"UC{use_case}_R{scenario}",
            use_case_id=f"UC{use_case}",
            model_slug=f"model-{model}",
            affect=affect,
            query_length=length,
            signed_directional_gap=0.2 if affect == Affect.ANXIOUS else 0.1,
        )
        for use_case in range(1, 7)
        for scenario in range(1, 6)
        for model in range(1, 8)
        for affect in (Affect.NEUTRAL, Affect.ANXIOUS)
        for length in ("short", "long")
    ]
    budget_scores = [
        BudgetScore(
            scenario_id=f"UC{use_case}_R{scenario}",
            use_case_id=f"UC{use_case}",
            model_slug=f"model-{model}",
            exact_fact_budget=budget,
            signed_directional_gap=float(budget) / 10,
        )
        for use_case in range(1, 7)
        for scenario in range(1, 6)
        for model in range(1, 8)
        for budget in (ExactFactBudget.FACTS_2, ExactFactBudget.FACTS_4, ExactFactBudget.FACTS_6)
    ]
    assert len(anxious_neutral_contrasts(user_state_scores)) == 30
    assert len(ordered_budget_contrasts(budget_scores)) == 30
    assert len(complete_budget_models(budget_scores)) == 7

    incomplete = [
        score
        for score in budget_scores
        if not (score.model_slug == "model-7" and score.scenario_id == "UC1_R1" and score.exact_fact_budget == ExactFactBudget.FACTS_2)
    ]
    assert complete_budget_models(incomplete) == [f"model-{model}" for model in range(1, 7)]
    assert len(ordered_budget_contrasts(incomplete)) == 30


def test_stratified_scenario_bootstrap_is_reproducible() -> None:
    """Resample five scenario clusters within each of six use cases reproducibly."""
    first = stratified_cluster_bootstrap(_contrasts(), iterations=500, random_seed=7)
    second = stratified_cluster_bootstrap(_contrasts(), iterations=500, random_seed=7)
    assert first == second


def test_commercial_confirmatory_contrasts_cover_each_task() -> None:
    """Aggregate four general tasks and one owner-recoded ownership task by scenario."""
    general: list[CommercialInterestContrast] = []
    task_values = (
        (CommercialInterestTask.STANDARD, None, 0.01),
        (CommercialInterestTask.SINGLE_FACT, None, 0.02),
        (CommercialInterestTask.EXACT_BUDGET, ExactFactBudget.FACTS_4, 0.03),
        (CommercialInterestTask.EXACT_BUDGET, ExactFactBudget.FACTS_2, 0.04),
    )
    for use_case in range(1, 7):
        for scenario in range(1, 6):
            for model in range(1, 8):
                for affect in Affect:
                    for task, budget, value in task_values:
                        general.append(
                            CommercialInterestContrast(
                                scenario_id=f"UC{use_case}_R{scenario}",
                                use_case_id=f"UC{use_case}",
                                model_slug=f"model-{model}",
                                affect=affect,
                                task=task,
                                outcome_name="prose_signed_directional_gap",
                                exact_fact_budget=budget,
                                treatment_minus_control=value,
                            )
                        )

    ownership: list[CommercialInterestContrast] = []
    ownership_scenarios = [(f"UC{index % 5 + 1}_R{index}", f"UC{index % 5 + 1}") for index in range(1, 12)]
    for scenario_id, use_case_id in ownership_scenarios:
        for model in range(1, 8):
            for affect in Affect:
                for role, fixed_option_value in (
                    (OwnershipRole.EMPLOYER_OWNS_A, 0.05),
                    (OwnershipRole.EMPLOYER_OWNS_B, -0.05),
                ):
                    for rendering in (1, 2):
                        ownership.append(
                            CommercialInterestContrast(
                                scenario_id=scenario_id,
                                use_case_id=use_case_id,
                                model_slug=f"model-{model}",
                                affect=affect,
                                task=CommercialInterestTask.OWNERSHIP_FLIP,
                                outcome_name="prose_option_coordinate_signed_directional_gap",
                                ownership_role=role,
                                rendering=rendering,
                                treatment_minus_control=fixed_option_value,
                            )
                        )

    contrasts = commercial_directional_contrasts([*general, *ownership])
    assert {name: len(values) for name, values in contrasts.items()} == {
        "commercial_standard_D": 30,
        "commercial_single_fact_D": 30,
        "commercial_exact_k4_D": 30,
        "commercial_exact_k2_D": 30,
        "commercial_ownership_flip_D": 11,
    }
    assert {name: values[0].value for name, values in contrasts.items()} == {
        "commercial_standard_D": 0.01,
        "commercial_single_fact_D": 0.02,
        "commercial_exact_k4_D": 0.03,
        "commercial_exact_k2_D": 0.04,
        "commercial_ownership_flip_D": 0.05,
    }


def test_grouped_reporting_is_descriptive_and_not_ranked() -> None:
    """Return groups alphabetically with explicit descriptive-only labeling."""
    summaries = summarize_groups([GroupObservation(group="closed", value=0.9), GroupObservation(group="open_weight", value=0.1)])
    assert [summary.group for summary in summaries] == ["closed", "open_weight"]
    assert all(summary.interpretation == "descriptive_only_no_ranking_or_causal_claim" for summary in summaries)


def test_commercial_interest_contrast_pairs_only_the_instruction() -> None:
    """Calculate treatment-minus-control while holding every other coordinate fixed."""
    observations = [
        CommercialInterestObservation(
            scenario_id="CF101_R1",
            use_case_id="CF101",
            model_slug="test/model",
            affect=Affect.ANXIOUS,
            instruction=instruction,
            task=CommercialInterestTask.EXACT_BUDGET,
            exact_fact_budget=ExactFactBudget.FACTS_2,
            outcome_name="signed_directional_gap",
            value=value,
        )
        for instruction, value in (
            (CommercialInterestInstruction.CONTROL, -0.1),
            (CommercialInterestInstruction.PROTECT_COMMERCIAL_INTERESTS, 0.2),
        )
    ]
    contrasts = paired_instruction_contrasts(observations)
    assert len(contrasts) == 1
    assert contrasts[0].treatment_minus_control == 0.30000000000000004
    assert contrasts[0].interpretation == "descriptive_secondary"
    summaries = summarize_commercial_interest_contrasts(contrasts)
    assert summaries[0].contrast_count == 1
    assert summaries[0].scenario_count == 1
    assert summaries[0].mean_treatment_minus_control == contrasts[0].treatment_minus_control
