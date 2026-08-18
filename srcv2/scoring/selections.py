"""Deterministic recovery of exact-budget selections from immutable responses."""

from __future__ import annotations

from typing import List, Literal, Sequence

from srcv2.common import artifact_sha256
from srcv2.experiments.responses import recover_exact_budget_selection
from srcv2.models.enums import CommercialInterestTask, ExperimentKind
from srcv2.models.experiments import CommercialInterestCell, InformationBudgetCell, RunUnit
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import SelectionRecoveryRecord


def recover_selection_records(runs: Sequence[RunUnit], scenarios: Sequence[AcceptedScenario]) -> List[SelectionRecoveryRecord]:
    """Recover only unambiguous exact-k selections without changing raw format adherence."""
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    if len(scenario_by_id) != len(scenarios):
        raise ValueError("selection recovery requires unique scenarios")
    records: List[SelectionRecoveryRecord] = []
    for run in runs:
        if run.experiment == ExperimentKind.INFORMATION_BUDGET and isinstance(run.cell, InformationBudgetCell):
            exact_fact_budget = run.cell.exact_fact_budget
        elif (
            run.experiment == ExperimentKind.COMMERCIAL_INTEREST
            and isinstance(run.cell, CommercialInterestCell)
            and run.cell.task == CommercialInterestTask.EXACT_BUDGET
        ):
            if run.cell.exact_fact_budget is None:
                raise ValueError("commercial exact-budget run is missing its budget coordinate")
            exact_fact_budget = run.cell.exact_fact_budget
        else:
            raise ValueError("selection recovery accepts only exact-budget runs")
        if run.response is None:
            raise ValueError("selection recovery requires an immutable semantic response")
        scenario = scenario_by_id[run.scenario_id]
        recovered = recover_exact_budget_selection(
            run.response.raw_response,
            exact_fact_budget,
            [fact.fact_id for fact in scenario.facts],
        )
        if recovered.selection_usable:
            source: Literal["strict_json", "fenced_json", "recovered_output", "unusable"] = (
                "strict_json" if recovered.format_adherent else "recovered_output"
            )
        else:
            source = "unusable"
        records.append(
            SelectionRecoveryRecord(
                run_unit_id=run.run_unit_id,
                expected_fact_count=exact_fact_budget,
                source=source,
                format_adherent=recovered.format_adherent,
                selection_usable=recovered.selection_usable,
                selected_fact_ids=recovered.selected_fact_ids,
                raw_response_sha256=artifact_sha256(run.response.raw_response),
                reason=recovered.reason,
            )
        )
    return records
