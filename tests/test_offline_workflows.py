"""Exercise the complete offline plan, transcript, scoring, and analysis boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from src.analysis.estimands import rows_to_frame
from src.cli.commands.analysis.build_inputs import build_analysis_rows
from src.data_models.experiments import RetryPolicy
from src.data_models.scoring import (
    AnalysisInputRow,
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    EvaluationCheckpoint,
    FactAssessmentResult,
    ResponseCommunicationResult,
)
from src.data_models.study import ExperimentName, cue_template_id
from src.experiments.scenario_runner import build_brevity_locus_run_plan, build_material_priority_run_plan, build_run_plan, execute_run_unit
from src.experiments.scoring_pipeline import score_conversation
from src.llm.openrouter import ProviderTextResponse
from tests.factories import make_accepted_scenario, make_models, make_scoring_results, make_transcript


def test_all_offline_workflows_reach_analysis_without_provider_calls() -> None:
    """Build every run matrix and simulate one natural-follow-up conversation through scoring."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 3)]
    created_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    models = make_models()
    primary_plan = build_run_plan(scenarios, models, 7, created_at)
    material_plan = build_material_priority_run_plan(scenarios, models, 7, created_at)
    brevity_plan = build_brevity_locus_run_plan(scenarios, models, 7, created_at)
    assert len(primary_plan) == 240
    assert len(material_plan) == 120
    assert len(brevity_plan) == 60

    class OfflineFailureProvider:
        """Simulate terminal provider failures without network access."""

        def complete_text(
            self,
            model_id: str,
            messages: List[Dict[str, str]],
            temperature: float,
            max_tokens: int,
            seed: int,
        ) -> ProviderTextResponse:
            """Fail every request to exercise a complete typed missingness ledger."""
            raise TimeoutError("offline simulated provider failure")

    failed_material = [execute_run_unit(unit, OfflineFailureProvider(), RetryPolicy(max_retries=0, backoff_seconds=[])) for unit in material_plan]
    analysis_rows, missing = build_analysis_rows(
        failed_material,
        [],
        [],
        "0" * 64,
        "0" * 64,
        ExperimentName.MATERIAL_PRIORITY_V1,
        120,
    )
    assert not analysis_rows
    assert len(missing) == 120

    scenario = scenarios[0]
    transcript = make_transcript(scenario)
    fact_result, response_result, claim_result = make_scoring_results(scenario, transcript)

    class OfflineScoringBackend:
        """Return deterministic fixture judgments without external calls."""

        def assess_facts(self, scoring_input: ConditionBlindScoringInput) -> FactAssessmentResult:
            """Return fact judgments bound to the generated blind identifier."""
            return fact_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

        def assess_response(self, scoring_input: ConditionBlindScoringInput) -> ResponseCommunicationResult:
            """Return response judgments bound to the generated blind identifier."""
            return response_result.model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

        def assess_claims(self, scoring_input: ConditionBlindScoringInput) -> ClaimAssessmentResult:
            """Return claim judgments bound to the generated blind identifier and source."""
            return claim_result.model_copy(
                update={
                    "blind_conversation_id": scoring_input.blind_conversation_id,
                    "visible_facts_sha256": scoring_input.visible_facts_sha256,
                }
            )

    _scoring_input, _facts, _response, _claims, metrics = score_conversation(
        transcript,
        scenario,
        OfflineScoringBackend(),
        fact_order_seed=7,
        prompt_factor_isolation_valid=True,
    )
    rows = [
        AnalysisInputRow(
            schema_version="2.0.0",
            run_unit_id=transcript.run_unit.run_unit_id,
            scenario_id=scenario.scenario_id,
            use_case_id=scenario.use_case_id,
            model_id=transcript.run_unit.model_id,
            cue_template_id=cue_template_id(scenario.scenario_id),
            word_budget=transcript.run_unit.cell.concision,
            expressed_concern=transcript.run_unit.cell.expressed_concern,
            metrics=metric,
            transcript_sha256=transcript.transcript_sha256,
            scoring_result_sha256="0" * 64,
        )
        for metric in metrics
    ]
    initial = rows_to_frame(rows)
    assert len(initial) == 1
    assert 0 <= initial.iloc[0]["selective_risk_communication_score"] <= 1
    assert len(rows_to_frame(rows, EvaluationCheckpoint.CUMULATIVE)) == 1
