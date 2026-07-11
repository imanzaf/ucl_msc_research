"""Tests for the end-to-end scoring orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List
from uuid import uuid4

from src.data_models.experiments import (
    ExperimentConfig,
    GenerationConfig,
    LLMCallRecord,
    LLMCallUsage,
    RunUnitIdentity,
    ScenarioRunRecord,
)
from src.data_models.scenarios import InteractionMode, PromptCondition
from src.data_models.scoring import (
    DisclaimerWashingCheck,
    FactContradictionCheck,
    FactUnitMatching,
    ResponseFactExtraction,
)
from src.data_models.user_personas import UserPersonaId
from src.data_models.user_simulator import (
    ConversationSpeaker,
    ConversationTurn,
    UserSimulatorOutcome,
)
from src.experiments.io import append_jsonl
from src.experiments.scoring_pipeline import score_scenario_runs
from src.llm.openrouter import LLMCallResult

SCENARIO_RUN_DIR = Path("data/inputs/scenarios/v0.1.0/runs/20260705T204014").resolve()


class FakeScoringClient:
    """Fake scoring client returning queued structured outputs."""

    def __init__(self, structured_outputs: List[Any]) -> None:
        """Store structured scoring outputs."""
        self.structured_outputs = list(structured_outputs)

    def complete_structured(self, **kwargs: Any) -> LLMCallResult:
        """Return the next fake structured output."""
        parsed = self.structured_outputs.pop(0)
        assert isinstance(parsed, kwargs["output_model"])
        record = LLMCallRecord(
            call_id=str(uuid4()),
            stage=kwargs["stage"],
            model_id="fake/scorer",
            resolved_model_id="fake/scorer",
            generation_id=str(uuid4()),
            cache_key=str(uuid4()),
            cache_hit=False,
            created_at="2026-07-11T00:00:00+00:00",
            prompt_version="test_scoring_v1",
            request_payload={},
            response_payload={},
            parsed_output=parsed.model_dump(),
            usage=LLMCallUsage(
                prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_credits=0.1
            ),
        )
        return LLMCallResult(parsed=parsed, record=record)


def make_config() -> ExperimentConfig:
    """Create a minimal experiment config for scoring tests."""
    return ExperimentConfig(
        experiment_name="pipeline_scoring_v1",
        scenario_run_dir=str(SCENARIO_RUN_DIR),
        agent_model_ids=["fake/agent"],
        user_simulator_model="fake/simulator",
        scoring_model="fake/scorer",
        generation_config=GenerationConfig(),
        cache_enabled=True,
    )


def make_scenario_run_record() -> ScenarioRunRecord:
    """Create a completed scenario run aligned with the RW001_U01 fixture."""
    return ScenarioRunRecord(
        experiment_name="pipeline_scoring_v1",
        run_id="20260711T030303",
        run_unit=RunUnitIdentity(
            scenario_family_id="RW001",
            scenario_id="RW001_U01",
            interaction_mode=InteractionMode.MULTI_TURN,
            prompt_condition=PromptCondition.NEUTRAL,
            persona_id=UserPersonaId.NEUTRAL_BASELINE,
            agent_model_id="fake/agent",
        ),
        system_prompt="You are a portfolio assistant.",
        initial_user_prompt="Can you review my portfolio?",
        transcript=[
            ConversationTurn(
                speaker=ConversationSpeaker.USER,
                turn_index=1,
                content="Can you review my portfolio?",
            ),
            ConversationTurn(
                speaker=ConversationSpeaker.AGENT,
                turn_index=2,
                content="The portfolio has some positives.",
            ),
        ],
        user_simulator_outcome=UserSimulatorOutcome(
            selected_action_id="A1",
            selected_belief_ids=[],
            rationale="The user asks for advice.",
        ),
    )


def test_scoring_pipeline_writes_metrics_and_usage(tmp_path) -> None:
    """Verify scoring orchestration produces typed scoring records."""
    experiment_dir = tmp_path / "pipeline_scoring_v1"
    result_path = experiment_dir / "results" / "20260711T030303_results.jsonl"
    append_jsonl(path=result_path, records=[make_scenario_run_record()])
    client = FakeScoringClient(
        [
            ResponseFactExtraction(extracted_facts=[]),
            FactUnitMatching(matches=[]),
            FactContradictionCheck(
                has_fact_contradiction=False,
                fact_contradiction_rationale="No contradiction.",
            ),
            DisclaimerWashingCheck(
                has_disclaimer_washing=False,
                disclaimer_washing_rationale="No disclaimer washing.",
            ),
        ]
    )

    records = score_scenario_runs(
        client=client,
        experiment_root=tmp_path,
        experiment_config=make_config(),
        scoring_run_id="20260711T040404",
    )

    assert len(records) == 1
    assert records[0].response_metrics.adverse_omission_score == 1.0
    assert records[0].user_harm_metrics is not None
    assert records[0].usage_summary.api_call_count == 4
    assert (experiment_dir / "results" / "20260711T040404_scoring_results.jsonl").exists()
