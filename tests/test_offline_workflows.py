"""Exercise offline run-plan, six-call scoring, and analysis boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from src.analysis.estimands import rows_to_frame
from src.cli.commands.analysis.build_inputs import build_analysis_rows
from src.data_models.experiments import RetryPolicy
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    AnalysisInputRow,
    ContentAssessmentResult,
    EvaluationCheckpoint,
    PresentationAssessmentResult,
)
from src.data_models.study import ExperimentName
from src.experiments.scenario_runner import build_brevity_locus_run_plan, build_material_priority_run_plan, build_run_plan, execute_run_unit
from src.experiments.scoring_pipeline import score_conversation
from src.llm.openrouter import ProviderTextResponse
from tests.factories import make_accepted_scenario, make_models, make_scoring_results, make_transcript


def test_all_offline_workflows_reach_analysis_without_provider_calls() -> None:
    """Build every matrix and score one conversation with six local fixture calls."""
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 3)]
    created_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    models = make_models()
    assert len(build_run_plan(scenarios, models, 7, created_at)) == 240
    material_plan = build_material_priority_run_plan(
        scenarios,
        models,
        7,
        created_at,
    )
    assert len(material_plan) == 120
    assert len(build_brevity_locus_run_plan(scenarios, models, 7, created_at)) == 60

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
            """Fail every request to exercise typed missingness."""
            raise TimeoutError("offline simulated provider failure")

    failed_material = [
        execute_run_unit(
            unit,
            OfflineFailureProvider(),
            RetryPolicy(max_retries=0, backoff_seconds=[]),
        )
        for unit in material_plan
    ]
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
    content, presentation, accuracy = make_scoring_results(scenario, transcript)

    class OfflineScoringBackend:
        """Return deterministic fixture judgments without external calls."""

        def assess_content(self, scoring_input: object) -> ContentAssessmentResult:
            """Return content bound to the isolated blind identifier."""
            return content[scoring_input.scored_response].model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

        def assess_presentation(
            self,
            scoring_input: object,
        ) -> PresentationAssessmentResult:
            """Return presentation findings for the selected response."""
            return presentation[scoring_input.scored_response].model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

        def assess_accuracy(self, scoring_input: object) -> AccuracyAssessmentResult:
            """Return accuracy findings for the selected response."""
            return accuracy[scoring_input.scored_response].model_copy(update={"blind_conversation_id": scoring_input.blind_conversation_id})

    _inputs, _content, _presentation, _accuracy, metrics = score_conversation(
        transcript,
        scenario,
        OfflineScoringBackend(),
        fact_order_seed=7,
    )
    rows = [
        AnalysisInputRow(
            schema_version="4.0.0",
            run_unit_id=transcript.run_unit.run_unit_id,
            scenario_id=scenario.scenario_id,
            use_case_id=scenario.use_case_id,
            model_id=transcript.run_unit.model_id,
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
    assert 0 <= initial.iloc[0]["selective_communication_score"] <= 1
    assert len(rows_to_frame(rows, EvaluationCheckpoint.FOLLOW_UP)) == 1
    assert len(rows_to_frame(rows, EvaluationCheckpoint.CUMULATIVE)) == 1
