"""Response-outcome aggregation and commercial-interest pairing tests."""

from __future__ import annotations

from datetime import UTC, datetime

from src.analysis.commercial_interest import commercial_interest_observations, paired_instruction_contrasts
from src.models.enums import (
    CommercialInterestInstruction,
    CommercialInterestTask,
    ExactFactBudget,
    FramingDirection,
    JudgeContract,
    OptionPresentationOrder,
    RecommendationDirection,
)
from src.models.experiments import ResponseMetadata, RunUnit
from src.models.scenarios import AcceptedScenario
from src.models.scoring import AccuracyJudgeOutput, AdjudicatedJudgment, ContentJudgeOutput, PresentationJudgeOutput, SelectionRecoveryRecord
from src.scoring.aggregation import score_response


def _run(scenario: AcceptedScenario, instruction: CommercialInterestInstruction, exact: bool = False) -> RunUnit:
    """Build one completed commercial-interest run containing all six supplied facts."""
    task = CommercialInterestTask.EXACT_BUDGET if exact else CommercialInterestTask.STANDARD
    cell = {
        "kind": "commercial_interest_instruction_v1",
        "affect": "neutral",
        "instruction": instruction.value,
        "task": task.value,
        "word_budget": 160,
        "exact_fact_budget": 2 if exact else None,
    }
    response_text = " ".join(fact.text for fact in scenario.facts)
    return RunUnit.model_validate(
        {
            "run_unit_id": f"run_{instruction.value}_{'exact' if exact else 'standard'}_1234567890",
            "experiment": "commercial_interest_instruction_v1",
            "cell": cell,
            "scenario_id": scenario.scenario_id,
            "query_variant_id": f"{scenario.scenario_id}_neutral_short",
            "prompt_sha256": "0" * 64,
            "response_contract_sha256": "1" * 64,
            "model": {
                "model_slug": "test/model",
                "model_access": "closed",
                "licence_category": "proprietary",
                "provider_name": "test",
                "provider_endpoint": "test",
                "routing_policy": "default",
                "metadata_snapshot_sha256": "2" * 64,
                "preflight_passed": True,
            },
            "generation_controls": {"max_output_tokens": 100},
            "response": ResponseMetadata(
                raw_response=response_text,
                answer_text=response_text,
                structurally_valid=True,
                adherent=True,
                received_at=datetime.now(UTC),
            ),
        }
    )


def _judgments(run: RunUnit, scenario: AcceptedScenario) -> list[AdjudicatedJudgment]:
    """Return a complete adjudicated set with all facts present and no accuracy issues."""
    judgments = [
        AdjudicatedJudgment(
            judge_call_id=f"judge_{fact.fact_id}_1234567890",
            run_unit_id=run.run_unit_id,
            contract=JudgeContract.CONTENT,
            fact_id=fact.fact_id,
            output=ContentJudgeOutput(fact_present=True, anchor_present=True, supporting_excerpt=fact.text),
            source="judge",
        )
        for fact in scenario.facts
    ]
    judgments.extend(
        [
            AdjudicatedJudgment(
                judge_call_id="judge_presentation_1234567890",
                run_unit_id=run.run_unit_id,
                contract=JudgeContract.PRESENTATION,
                fact_id=None,
                output=PresentationJudgeOutput(
                    framing_direction=FramingDirection.OPTION_A,
                    recommendation_direction=RecommendationDirection.OPTION_A,
                    option_presented_first=OptionPresentationOrder.OPTION_A,
                    empathy_or_reassurance=False,
                    referral_or_deferral=False,
                ),
                source="judge",
            ),
            AdjudicatedJudgment(
                judge_call_id="judge_accuracy_1234567890",
                run_unit_id=run.run_unit_id,
                contract=JudgeContract.ACCURACY,
                fact_id=None,
                output=AccuracyJudgeOutput(issues=[]),
                source="judge",
            ),
        ]
    )
    return judgments


def test_response_aggregation_keeps_all_outcomes_separate(accepted_scenario: AcceptedScenario) -> None:
    """Join six content labels and two response labels without a composite score."""
    run = _run(accepted_scenario, CommercialInterestInstruction.CONTROL)
    score = score_response(run, accepted_scenario, _judgments(run, accepted_scenario))
    assert score.prose_selection.signed_directional_gap == 0
    assert score.prose_selection.total_material_coverage == 1
    assert score.prose_selection.anchor_retention_among_communicated == 1
    assert score.accuracy.response_has_material_error is False
    assert score.secondary.factual_density > 0
    assert score.exact_selection is None


def test_exact_selection_and_instruction_pairing(accepted_scenario: AcceptedScenario) -> None:
    """Score identifier choices separately and retain only complete instruction pairs."""
    selected_ids = [fact.fact_id for fact in accepted_scenario.facts[:2]]
    scores = []
    for instruction in CommercialInterestInstruction:
        run = _run(accepted_scenario, instruction, exact=True)
        recovery = SelectionRecoveryRecord(
            run_unit_id=run.run_unit_id,
            expected_fact_count=ExactFactBudget.FACTS_2,
            source="strict_json",
            format_adherent=True,
            selection_usable=True,
            selected_fact_ids=selected_ids,
            raw_response_sha256="3" * 64,
        )
        scores.append(score_response(run, accepted_scenario, _judgments(run, accepted_scenario), recovery))
    observations = commercial_interest_observations(scores)
    contrasts = paired_instruction_contrasts(observations)
    assert any(contrast.outcome_name == "selected_id_signed_directional_gap" for contrast in contrasts)
    assert all(contrast.treatment_minus_control == 0 for contrast in contrasts)
