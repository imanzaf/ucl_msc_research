"""Deterministic recovery of exact-budget selections from immutable responses."""

from __future__ import annotations

from typing import List, Literal, Sequence

from srcv2.common import artifact_sha256
from srcv2.experiments.responses import recover_exact_budget_selection
from srcv2.models.enums import ExperimentKind
from srcv2.models.experiments import InformationBudgetCell, RunUnit
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import SelectionRecoveryRecord


def recover_selection_records(runs: Sequence[RunUnit], scenarios: Sequence[AcceptedScenario]) -> List[SelectionRecoveryRecord]:
    """Recover only strict or wholly fenced exact-k selections for scoring."""
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    if len(scenario_by_id) != len(scenarios):
        raise ValueError("selection recovery requires unique scenarios")
    records: List[SelectionRecoveryRecord] = []
    for run in runs:
        if run.experiment != ExperimentKind.INFORMATION_BUDGET or not isinstance(run.cell, InformationBudgetCell):
            raise ValueError("selection recovery accepts only information-budget runs")
        if run.response is None:
            raise ValueError("selection recovery requires an immutable semantic response")
        scenario = scenario_by_id[run.scenario_id]
        recovered = recover_exact_budget_selection(
            run.response.raw_response,
            run.cell.exact_fact_budget,
            [fact.fact_id for fact in scenario.facts],
        )
        if recovered.selection_usable:
            source: Literal["strict_json", "fenced_json", "unusable"] = "strict_json" if recovered.format_adherent else "fenced_json"
        else:
            source = "unusable"
        records.append(
            SelectionRecoveryRecord(
                run_unit_id=run.run_unit_id,
                expected_fact_count=run.cell.exact_fact_budget,
                source=source,
                format_adherent=recovered.format_adherent,
                selection_usable=recovered.selection_usable,
                selected_fact_ids=recovered.selected_fact_ids,
                raw_response_sha256=artifact_sha256(run.response.raw_response),
                reason=recovered.reason,
            )
        )
    return records
