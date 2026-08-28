"""Deterministic construction of the seven dissertation experiment matrices."""

from __future__ import annotations

from collections import Counter
from typing import List

from pydantic import Field

from src.common import ImmutableModel, artifact_sha256
from src.models.enums import (
    Affect,
    CommercialInterestInstruction,
    CommercialInterestTask,
    ExactFactBudget,
    ExecutionStatus,
    ExperimentKind,
    NaturalWordBudget,
    OwnershipRole,
    QueryLength,
)
from src.models.experiments import (
    CommercialInterestCell,
    ExperimentCell,
    InformationBudgetCell,
    OptionFirstCell,
    OwnershipCell,
    SingleFactCell,
    UserStateCell,
    WordBudgetCell,
)
from src.models.seeds import ScenarioSeedSet

ACTIVE_RESPONSE_COUNTS = {
    ExperimentKind.USER_STATE: 1260,
    ExperimentKind.INFORMATION_BUDGET: 1050,
    ExperimentKind.WORD_BUDGET: 630,
    ExperimentKind.SINGLE_FACT: 210,
    ExperimentKind.OWNERSHIP: 462,
    ExperimentKind.OPTION_FIRST: 210,
    ExperimentKind.COMMERCIAL_INTEREST: 6888,
}
TOTAL_ACTIVE_RESPONSES = 10710


class MatrixAssignment(ImmutableModel):
    """Bind a scenario, model, treatment cell, and fixed fact order."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    assignment_id: str
    scenario_id: str
    model_slug: str
    cell: ExperimentCell
    fact_order: int = Field(ge=1, le=2)
    execution_status: ExecutionStatus


def _assignment(
    scenario_id: str,
    model_slug: str,
    cell: ExperimentCell,
    fact_order: int,
) -> MatrixAssignment:
    """Construct a stable unique matrix assignment identifier."""
    hash_payload = {
        "scenario_id": scenario_id,
        "model_slug": model_slug,
        "cell": cell.model_dump(mode="json"),
        "fact_order": fact_order,
        "execution_status": ExecutionStatus.ACTIVE,
    }
    return MatrixAssignment(
        assignment_id=f"run_{artifact_sha256(hash_payload)[:24]}",
        scenario_id=scenario_id,
        model_slug=model_slug,
        cell=cell,
        fact_order=fact_order,
        execution_status=ExecutionStatus.ACTIVE,
    )


def _user_state_cells() -> List[ExperimentCell]:
    """Return all six user-state cells."""
    return [UserStateCell(affect=affect, query_length=length) for affect in Affect for length in QueryLength]


def _information_budget_cells() -> List[ExperimentCell]:
    """Return the five active affect-by-exact-budget cells."""
    return [
        InformationBudgetCell(affect=Affect.NEUTRAL, exact_fact_budget=ExactFactBudget.FACTS_2),
        InformationBudgetCell(affect=Affect.NEUTRAL, exact_fact_budget=ExactFactBudget.FACTS_4),
        InformationBudgetCell(affect=Affect.NEUTRAL, exact_fact_budget=ExactFactBudget.FACTS_6),
        InformationBudgetCell(affect=Affect.ANXIOUS, exact_fact_budget=ExactFactBudget.FACTS_2),
        InformationBudgetCell(affect=Affect.ANXIOUS, exact_fact_budget=ExactFactBudget.FACTS_4),
    ]


def _commercial_interest_cells(ownership_eligible: bool) -> List[ExperimentCell]:
    """Return all approved short-query, 160-word commercial-interest cells."""
    cells: List[ExperimentCell] = []
    for affect in Affect:
        for instruction in CommercialInterestInstruction:
            cells.extend(
                (
                    CommercialInterestCell(affect=affect, instruction=instruction, task=CommercialInterestTask.STANDARD),
                    CommercialInterestCell(affect=affect, instruction=instruction, task=CommercialInterestTask.SINGLE_FACT),
                    CommercialInterestCell(
                        affect=affect,
                        instruction=instruction,
                        task=CommercialInterestTask.EXACT_BUDGET,
                        exact_fact_budget=ExactFactBudget.FACTS_2,
                    ),
                    CommercialInterestCell(
                        affect=affect,
                        instruction=instruction,
                        task=CommercialInterestTask.EXACT_BUDGET,
                        exact_fact_budget=ExactFactBudget.FACTS_4,
                    ),
                )
            )
            if ownership_eligible:
                cells.extend(
                    CommercialInterestCell(
                        affect=affect,
                        instruction=instruction,
                        task=CommercialInterestTask.OWNERSHIP_FLIP,
                        ownership_role=role,
                        rendering=rendering,
                    )
                    for role in (OwnershipRole.EMPLOYER_OWNS_A, OwnershipRole.EMPLOYER_OWNS_B)
                    for rendering in (1, 2)
                )
    return cells


def build_matrix(seed_set: ScenarioSeedSet, model_slugs: List[str]) -> List[MatrixAssignment]:
    """Build all unique assignments for the seven dissertation experiments."""
    if len(model_slugs) != 7 or len(set(model_slugs)) != 7:
        raise ValueError("matrix requires seven unique evaluated model slugs")
    scenarios = [scenario for use_case in seed_set.use_cases for scenario in use_case.replications]
    assignments: List[MatrixAssignment] = []
    for scenario_index, scenario in enumerate(scenarios):
        fact_order = 1 if scenario_index < 15 else 2
        for model_slug in model_slugs:
            assignments.extend(_assignment(scenario.scenario_id, model_slug, cell, fact_order) for cell in _user_state_cells())
            assignments.extend(_assignment(scenario.scenario_id, model_slug, cell, fact_order) for cell in _information_budget_cells())
            assignments.extend(
                _assignment(scenario.scenario_id, model_slug, WordBudgetCell(word_budget=budget), fact_order) for budget in NaturalWordBudget
            )
            assignments.append(_assignment(scenario.scenario_id, model_slug, SingleFactCell(), fact_order))
            assignments.append(_assignment(scenario.scenario_id, model_slug, OptionFirstCell(), fact_order))
            ownership_eligible = scenario.comparison_scope == "provider_vs_external"
            assignments.extend(
                _assignment(scenario.scenario_id, model_slug, cell, fact_order) for cell in _commercial_interest_cells(ownership_eligible)
            )
            if ownership_eligible:
                assignments.extend(
                    _assignment(scenario.scenario_id, model_slug, OwnershipCell(ownership_role=role, rendering=rendering), fact_order)
                    for role in OwnershipRole
                    for rendering in (1, 2)
                )
    if len({assignment.assignment_id for assignment in assignments}) != len(assignments):
        raise ValueError("matrix contains duplicate run assignments")
    active_counts = Counter(assignment.cell.kind for assignment in assignments if assignment.execution_status == ExecutionStatus.ACTIVE)
    if dict(active_counts) != ACTIVE_RESPONSE_COUNTS or sum(active_counts.values()) != TOTAL_ACTIVE_RESPONSES:
        raise ValueError(f"active matrix counts do not match protocol: {dict(active_counts)}")
    return assignments


def response_counts(assignments: List[MatrixAssignment]) -> dict[str, int]:
    """Summarize assignments by experiment name."""
    counts = Counter(assignment.cell.kind.value for assignment in assignments)
    return dict(sorted(counts.items()))
