"""Tests for scenario-run orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List
from uuid import uuid4

from src.data_models.experiments import (
    ExperimentConfig,
    ExperimentStage,
    GenerationConfig,
    LLMCallRecord,
    LLMCallUsage,
)
from src.data_models.user_simulator import UserSimulatorOutcome, UserSimulatorTurnOutput
from src.experiments.scenario_runner import run_scenarios
from src.llm.openrouter import LLMCallResult
from tests.canonical_scenario_fixtures import write_scenario_run_dir


class FakePipelineClient:
    """Fake pipeline client with text and structured output queues."""

    def __init__(self, text_outputs: List[str], structured_outputs: List[Any]) -> None:
        """Store outputs returned by fake LLM calls."""
        self.text_outputs = list(text_outputs)
        self.structured_outputs = list(structured_outputs)

    def make_result(self, parsed: Any, stage: ExperimentStage) -> LLMCallResult:
        """Create one typed call result with deterministic usage."""
        record = LLMCallRecord(
            call_id=str(uuid4()),
            stage=stage,
            model_id="fake/model",
            resolved_model_id="fake/model",
            generation_id=str(uuid4()),
            cache_key=str(uuid4()),
            cache_hit=False,
            created_at="2026-07-11T00:00:00+00:00",
            prompt_version="test_prompt_v1",
            request_payload={},
            response_payload={},
            parsed_output=parsed.model_dump() if hasattr(parsed, "model_dump") else None,
            text_output=parsed if isinstance(parsed, str) else None,
            usage=LLMCallUsage(
                prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_credits=0.1
            ),
        )
        return LLMCallResult(parsed=parsed, record=record)

    def complete_text(self, **kwargs: Any) -> LLMCallResult:
        """Return the next fake text completion."""
        return self.make_result(self.text_outputs.pop(0), kwargs["stage"])

    def complete_structured(self, **kwargs: Any) -> LLMCallResult:
        """Return the next fake structured completion."""
        parsed = self.structured_outputs.pop(0)
        assert isinstance(parsed, kwargs["output_model"])
        return self.make_result(parsed, kwargs["stage"])


def make_config(scenario_run_dir: Path, max_followup_turns: int = 3) -> ExperimentConfig:
    """Create a minimal experiment config for scenario-run tests."""
    return ExperimentConfig(
        experiment_name="pipeline_smoke_v1",
        scenario_run_dir=str(scenario_run_dir),
        agent_model_ids=["fake/agent"],
        user_simulator_model="fake/simulator",
        scoring_model="fake/scorer",
        generation_config=GenerationConfig(),
        max_followup_turns=max_followup_turns,
        cache_enabled=True,
    )


def test_single_selected_unit_stops_after_first_agent_response(tmp_path: Path) -> None:
    """Verify a selected run unit writes one transcript and user outcome."""
    agent_client = FakePipelineClient(
        text_outputs=["The portfolio has benefits and material risks."],
        structured_outputs=[],
    )
    user_simulator_client = FakePipelineClient(
        text_outputs=[],
        structured_outputs=[
            UserSimulatorTurnOutput(should_continue=False, rationale="Enough information."),
            UserSimulatorOutcome(
                selected_action_id="A1",
                selected_belief_ids=[],
                rationale="The user would ask for a review.",
            ),
        ],
    )

    records = run_scenarios(
        agent_client=agent_client,
        user_simulator_client=user_simulator_client,
        experiment_root=tmp_path,
        experiment_config=make_config(write_scenario_run_dir(tmp_path)),
        scenario_family_ids=["RW001"],
        scenario_ids=["RW001_U01"],
        prompt_conditions=["neutral"],
        persona_ids=["neutral_baseline"],
        run_id="20260711T010101",
        limit=1,
    )

    assert len(records) == 1
    assert records[0].transcript[-1].content == "The portfolio has benefits and material risks."
    assert records[0].user_simulator_outcome.selected_action_id == "A1"
    assert "high_adverse" not in records[0].system_prompt
    assert (tmp_path / "pipeline_smoke_v1" / "results" / "20260711T010101_results.jsonl").exists()


def test_multi_turn_loop_honors_followup_cap(tmp_path: Path) -> None:
    """Verify multi-turn execution stops at the configured follow-up cap."""
    agent_client = FakePipelineClient(
        text_outputs=["Agent one.", "Agent two.", "Agent three."],
        structured_outputs=[],
    )
    user_simulator_client = FakePipelineClient(
        text_outputs=[],
        structured_outputs=[
            UserSimulatorTurnOutput(
                should_continue=True,
                utterance="Can you say more about the risk?",
                rationale="The user wants detail.",
            ),
            UserSimulatorTurnOutput(
                should_continue=True,
                utterance="What should I do next?",
                rationale="The user wants next steps.",
            ),
            UserSimulatorOutcome(
                selected_action_id="A1",
                selected_belief_ids=[],
                rationale="The user remains cautious.",
            ),
        ],
    )

    records = run_scenarios(
        agent_client=agent_client,
        user_simulator_client=user_simulator_client,
        experiment_root=tmp_path,
        experiment_config=make_config(
            write_scenario_run_dir(tmp_path),
            max_followup_turns=2,
        ),
        scenario_family_ids=["RW001"],
        scenario_ids=["RW001_U01"],
        prompt_conditions=["neutral"],
        persona_ids=["neutral_baseline"],
        run_id="20260711T020202",
        limit=1,
    )

    assert len(records[0].user_simulator_turns) == 2
    assert len(records[0].transcript) == 6
    assert records[0].transcript[-1].content == "Agent three."
