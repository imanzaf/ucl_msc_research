"""Deterministic construction of the six active experiment matrices."""

from __future__ import annotations

from collections import Counter
from typing import List

from pydantic import Field

from srcv2.common import ImmutableModel, artifact_sha256
from srcv2.models.enums import Affect, ExactFactBudget, ExecutionStatus, ExperimentKind, NaturalWordBudget, OwnershipRole, QueryLength
from srcv2.models.experiments import (
    BalancedProminenceCell,
    ExperimentCell,
    InformationBudgetCell,
    OptionFirstCell,
    OwnershipCell,
    SingleFactCell,
    UserStateCell,
    WordBudgetCell,
)
from srcv2.models.seeds import ScenarioSeedSet

ACTIVE_RESPONSE_COUNTS = {
    ExperimentKind.USER_STATE: 1260,
    ExperimentKind.INFORMATION_BUDGET: 1050,
    ExperimentKind.WORD_BUDGET: 630,
    ExperimentKind.SINGLE_FACT: 210,
    ExperimentKind.OWNERSHIP: 462,
    ExperimentKind.OPTION_FIRST: 210,
}
TOTAL_ACTIVE_RESPONSES = 3822
DEFERRED_RESPONSE_COUNT = 210


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
    execution_status: ExecutionStatus = ExecutionStatus.ACTIVE,
) -> MatrixAssignment:
    """Construct a stable unique matrix assignment identifier."""
    hash_payload = {
        "scenario_id": scenario_id,
        "model_slug": model_slug,
        "cell": cell.model_dump(mode="json"),
        "fact_order": fact_order,
        "execution_status": execution_status,
    }
    return MatrixAssignment(
        assignment_id=f"run_{artifact_sha256(hash_payload)[:24]}",
        scenario_id=scenario_id,
        model_slug=model_slug,
        cell=cell,
        fact_order=fact_order,
        execution_status=execution_status,
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


def build_matrix(seed_set: ScenarioSeedSet, model_slugs: List[str], include_deferred: bool = False) -> List[MatrixAssignment]:
    """Build all unique active run assignments and optionally the deferred mitigation."""
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
            if scenario.comparison_scope == "provider_vs_external":
                assignments.extend(
                    _assignment(scenario.scenario_id, model_slug, OwnershipCell(ownership_role=role, rendering=rendering), fact_order)
                    for role in OwnershipRole
                    for rendering in (1, 2)
                )
            if include_deferred:
                assignments.append(
                    _assignment(
                        scenario.scenario_id,
                        model_slug,
                        BalancedProminenceCell(),
                        fact_order,
                        execution_status=ExecutionStatus.DEFERRED,
                    )
                )
    if len({assignment.assignment_id for assignment in assignments}) != len(assignments):
        raise ValueError("matrix contains duplicate run assignments")
    active_counts = Counter(assignment.cell.kind for assignment in assignments if assignment.execution_status == ExecutionStatus.ACTIVE)
    if dict(active_counts) != ACTIVE_RESPONSE_COUNTS or sum(active_counts.values()) != TOTAL_ACTIVE_RESPONSES:
        raise ValueError(f"active matrix counts do not match protocol: {dict(active_counts)}")
    if include_deferred and sum(assignment.execution_status == ExecutionStatus.DEFERRED for assignment in assignments) != DEFERRED_RESPONSE_COUNT:
        raise ValueError("deferred balanced-prominence matrix must contain 210 assignments")
    return assignments


def response_counts(assignments: List[MatrixAssignment]) -> dict[str, int]:
    """Summarize active and deferred assignments by experiment name."""
    counts = Counter(assignment.cell.kind.value for assignment in assignments)
    return dict(sorted(counts.items()))
