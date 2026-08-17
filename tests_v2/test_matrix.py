"""Active and deferred experiment matrix tests."""

from __future__ import annotations

from collections import Counter

from srcv2.experiments.matrix import ACTIVE_RESPONSE_COUNTS, TOTAL_ACTIVE_RESPONSES, build_matrix
from srcv2.models.catalog import load_model_catalog
from srcv2.models.enums import ExecutionStatus, ExperimentKind
from srcv2.models.seeds import ScenarioSeedSet


def test_active_matrix_counts_exactly_3822(seed_set: ScenarioSeedSet) -> None:
    """Assert all six active experiment counts and unique run identifiers."""
    models = [entry.model_slug for entry in load_model_catalog().evaluated_models]
    assignments = build_matrix(seed_set, models)
    counts = Counter(assignment.cell.kind for assignment in assignments)
    assert counts == Counter(ACTIVE_RESPONSE_COUNTS)
    assert len(assignments) == TOTAL_ACTIVE_RESPONSES == 3822
    assert len({assignment.assignment_id for assignment in assignments}) == 3822
    assert all(assignment.execution_status == ExecutionStatus.ACTIVE for assignment in assignments)


def test_deferred_balanced_prominence_is_implemented_but_excluded(seed_set: ScenarioSeedSet) -> None:
    """Add exactly 210 deferred units without changing the active total."""
    models = [entry.model_slug for entry in load_model_catalog().evaluated_models]
    assignments = build_matrix(seed_set, models, include_deferred=True)
    deferred = [assignment for assignment in assignments if assignment.execution_status == ExecutionStatus.DEFERRED]
    assert len(deferred) == 210
    assert {assignment.cell.kind for assignment in deferred} == {ExperimentKind.BALANCED_PROMINENCE}
    assert sum(assignment.execution_status == ExecutionStatus.ACTIVE for assignment in assignments) == 3822
