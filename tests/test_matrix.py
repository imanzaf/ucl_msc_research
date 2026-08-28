"""Dissertation experiment matrix tests."""

from __future__ import annotations

from collections import Counter

from src.experiments.matrix import ACTIVE_RESPONSE_COUNTS, TOTAL_ACTIVE_RESPONSES, build_matrix
from src.models.catalog import load_model_catalog
from src.models.enums import CommercialInterestInstruction, CommercialInterestTask, ExecutionStatus, ExperimentKind, NaturalWordBudget
from src.models.experiments import CommercialInterestCell
from src.models.seeds import ScenarioSeedSet


def test_active_matrix_counts_exactly_10710(seed_set: ScenarioSeedSet) -> None:
    """Assert all seven active experiment counts and unique run identifiers."""
    models = [entry.model_slug for entry in load_model_catalog().evaluated_models]
    assignments = build_matrix(seed_set, models)
    counts = Counter(assignment.cell.kind for assignment in assignments)
    assert counts == Counter(ACTIVE_RESPONSE_COUNTS)
    assert len(assignments) == TOTAL_ACTIVE_RESPONSES == 10710
    assert len({assignment.assignment_id for assignment in assignments}) == 10710
    assert all(assignment.execution_status == ExecutionStatus.ACTIVE for assignment in assignments)


def test_commercial_interest_matrix_crosses_every_approved_coordinate(seed_set: ScenarioSeedSet) -> None:
    """Cross both instructions with all affects and tasks without inflating ownership cells."""
    models = [entry.model_slug for entry in load_model_catalog().evaluated_models]
    cells = [assignment.cell for assignment in build_matrix(seed_set, models) if isinstance(assignment.cell, CommercialInterestCell)]
    assert len(cells) == 6888
    assert Counter(cell.instruction for cell in cells) == {
        CommercialInterestInstruction.CONTROL: 3444,
        CommercialInterestInstruction.PROTECT_COMMERCIAL_INTERESTS: 3444,
    }
    assert Counter(cell.task for cell in cells) == {
        CommercialInterestTask.STANDARD: 1260,
        CommercialInterestTask.SINGLE_FACT: 1260,
        CommercialInterestTask.EXACT_BUDGET: 2520,
        CommercialInterestTask.OWNERSHIP_FLIP: 1848,
    }
    assert all(cell.word_budget == NaturalWordBudget.WORDS_160 for cell in cells)


def test_commercial_interest_run_ids_are_stable_across_plan_rebuilds(seed_set: ScenarioSeedSet) -> None:
    """Rebuild the core experiment without changing any resumable run identifier."""
    models = [entry.model_slug for entry in load_model_catalog().evaluated_models]
    first = [assignment.assignment_id for assignment in build_matrix(seed_set, models) if assignment.cell.kind == ExperimentKind.COMMERCIAL_INTEREST]
    second = [assignment.assignment_id for assignment in build_matrix(seed_set, models) if assignment.cell.kind == ExperimentKind.COMMERCIAL_INTEREST]
    assert first == second
    assert len(set(first)) == 6888
