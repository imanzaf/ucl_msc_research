"""Tests for current scenario execution orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel

from src.data_models.experiments import (
    ConversationProtocol,
    ExperimentConfig,
    ExperimentStage,
    GenerationConfig,
    LLMCallRecord,
)
from src.data_models.scenario_review import (
    FindingType,
    HumanReviewStatus,
    RequirementAssessment,
    RequirementStatus,
    ScenarioGenerationManifest,
    ScenarioHumanReview,
    ScenarioSemanticReview,
    artifact_sha256,
    expected_semantic_review_keys,
)
from src.data_models.user_simulator import UserSimulatorOutcome
from src.experiments.scenario_runner import run_scenarios
from src.llm.openrouter import LLMCallResult
from tests.scenario_fixtures import make_family


class FakePipelineClient:
    """Fake text and structured client for scenario-runner tests."""

    def __init__(
        self, text_outputs: Sequence[str], structured_outputs: Sequence[BaseModel]
    ) -> None:
        """Store deterministic outputs and call metadata."""
        self.text_outputs = list(text_outputs)
        self.structured_outputs = list(structured_outputs)
        self.text_calls: List[Dict[str, Any]] = []
        self.structured_calls: List[Dict[str, Any]] = []

    def _record(self, stage: ExperimentStage, prompt_version: str) -> LLMCallRecord:
        """Create a minimal call record."""
        return LLMCallRecord(
            call_id=f"call-{len(self.text_calls) + len(self.structured_calls)}",
            stage=stage,
            model_id="fake/model",
            cache_key=f"cache-{len(self.text_calls) + len(self.structured_calls)}",
            created_at="2026-07-17T00:00:00+00:00",
            prompt_version=prompt_version,
            request_payload={},
        )

    def complete_text(
        self,
        stage: ExperimentStage,
        model_id: str,
        messages: List[Dict[str, str]],
        generation_config: GenerationConfig,
        prompt_version: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> LLMCallResult[str]:
        """Return the next text output."""
        _ = (model_id, generation_config, metadata)
        self.text_calls.append({"stage": stage, "messages": messages})
        return LLMCallResult(
            parsed=self.text_outputs.pop(0), record=self._record(stage, prompt_version)
        )

    def complete_structured(
        self,
        stage: ExperimentStage,
        model_id: str,
        messages: List[Dict[str, str]],
        output_model: Type[BaseModel],
        generation_config: GenerationConfig,
        prompt_version: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> LLMCallResult[BaseModel]:
        """Return the next structured output."""
        _ = (model_id, messages, output_model, generation_config, metadata)
        self.structured_calls.append({"stage": stage, "output_model": output_model})
        return LLMCallResult(
            parsed=self.structured_outputs.pop(0), record=self._record(stage, prompt_version)
        )


def make_semantic_review() -> ScenarioSemanticReview:
    """Create a passing semantic review for the fixture family."""
    family = make_family()
    assessments: List[RequirementAssessment] = []
    for requirement_id, scope, subject_id in sorted(expected_semantic_review_keys(family), key=str):
        assessments.append(
            RequirementAssessment(
                requirement_id=requirement_id,
                subject_scope=scope,
                subject_id=subject_id,
                status=RequirementStatus.PASS,
                finding_id="",
                finding_type=FindingType.NONE,
                affected_scenario_ids=[],
                evidence="Fixture evidence inspected.",
                problem="",
                required_correction="",
                affected_field_paths=[],
                rationale="Fixture passes the requirement.",
            )
        )
    return ScenarioSemanticReview(
        scenario_family_id=family.scenario_family_id,
        assessments=assessments,
        review_summary="Fixture review passes.",
    )


def write_accepted_scenario_run_dir(root: Path) -> Path:
    """Write a family and matching accepted review manifests."""
    family = make_family()
    review = make_semantic_review()
    manifest = ScenarioGenerationManifest(
        scenario_family_id=family.scenario_family_id,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        initial_call_ids={
            instance.scenario_id: f"initial-{instance.scenario_id}"
            for instance in family.scenario_instances
        },
        semantic_review_call_ids=["semantic-review-call"],
        reviewed_scenario_ids=[instance.scenario_id for instance in family.scenario_instances],
        finding_ids_by_scenario={},
        revision_attempts=[],
    )
    human_review = ScenarioHumanReview(
        scenario_family_id=family.scenario_family_id,
        status=HumanReviewStatus.ACCEPTED,
        reviewer="Reviewer One",
        reviewed_at="2026-07-17T00:00:00+00:00",
        finding_resolutions=[],
        notes="Accepted fixture family.",
        final_family_sha256=artifact_sha256(family),
        semantic_review_sha256=artifact_sha256(review),
        generation_manifest_sha256=artifact_sha256(manifest),
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "semantic_reviews").mkdir()
    (root / "manifests").mkdir()
    (root / "human_reviews").mkdir()
    (root / f"{family.scenario_family_id}.json").write_text(
        family.model_dump_json(indent=2), encoding="utf-8"
    )
    (root / "semantic_reviews" / f"{family.scenario_family_id}.json").write_text(
        review.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "manifests" / f"{family.scenario_family_id}.json").write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "human_reviews" / f"{family.scenario_family_id}.json").write_text(
        human_review.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return root


def make_config(scenario_run_dir: Path, family_scenario_concurrency: int = 1) -> ExperimentConfig:
    """Create a scenario-runner experiment config."""
    return ExperimentConfig(
        experiment_name="scenario_runner_v1",
        scenario_run_dir=str(scenario_run_dir),
        agent_model_ids=["meta-llama/llama-3.3-70b-instruct"],
        user_simulator_model="google/gemma-4-26b-a4b-it",
        scoring_model="google/gemini-3.1-flash-lite",
        family_scenario_concurrency=family_scenario_concurrency,
    )


def test_selected_unit_uses_scripted_risk_followup(tmp_path: Path) -> None:
    """Verify a selected run unit writes a scripted four-turn transcript and outcome."""
    agent_client = FakePipelineClient(
        text_outputs=["Initial answer.", "Follow-up answer."],
        structured_outputs=[],
    )
    user_simulator_client = FakePipelineClient(
        text_outputs=[],
        structured_outputs=[
            UserSimulatorOutcome(
                selected_action_id="review_plan",
                selected_belief_ids=["supported"],
                rationale="The user would review safely.",
            )
        ],
    )

    records = run_scenarios(
        agent_client=agent_client,  # type: ignore[arg-type]
        user_simulator_client=user_simulator_client,  # type: ignore[arg-type]
        experiment_root=tmp_path,
        experiment_config=make_config(write_accepted_scenario_run_dir(tmp_path / "scenario-run")),
        scenario_family_ids=["PFM001"],
        scenario_ids=["PFM001_T1_R1"],
        prompt_conditions=["neutral"],
        persona_ids=["neutral_baseline"],
        run_id="20260717T010101",
        limit=1,
    )

    assert len(records) == 1
    assert records[0].conversation_protocol == ConversationProtocol.SCRIPTED_RISK_FOLLOWUP
    assert records[0].scripted_user_followup_count == 1
    assert records[0].agent_turn_count == 2
    assert len(records[0].transcript) == 4
    assert len(agent_client.text_calls) == 2
    assert len(user_simulator_client.structured_calls) == 1


def test_resume_rebuilds_scenario_usage_from_existing_records(tmp_path: Path) -> None:
    """Verify resume preserves usage for already-written scenario records."""
    scenario_run_dir = write_accepted_scenario_run_dir(tmp_path / "scenario-run")
    config = make_config(scenario_run_dir)
    agent_client = FakePipelineClient(["Initial answer.", "Follow-up answer."], [])
    user_client = FakePipelineClient(
        [],
        [
            UserSimulatorOutcome(
                selected_action_id="review_plan",
                selected_belief_ids=["supported"],
                rationale="The user would review safely.",
            )
        ],
    )

    first_records = run_scenarios(
        agent_client=agent_client,  # type: ignore[arg-type]
        user_simulator_client=user_client,  # type: ignore[arg-type]
        experiment_root=tmp_path,
        experiment_config=config,
        scenario_family_ids=["PFM001"],
        scenario_ids=["PFM001_T1_R1"],
        prompt_conditions=["neutral"],
        persona_ids=["neutral_baseline"],
        run_id="20260717T020202",
        limit=1,
    )
    resume_config = config.model_copy(update={"resume": True})
    second_records = run_scenarios(
        agent_client=FakePipelineClient([], []),  # type: ignore[arg-type]
        user_simulator_client=FakePipelineClient([], []),  # type: ignore[arg-type]
        experiment_root=tmp_path,
        experiment_config=resume_config,
        scenario_family_ids=["PFM001"],
        scenario_ids=["PFM001_T1_R1"],
        prompt_conditions=["neutral"],
        persona_ids=["neutral_baseline"],
        run_id="20260717T020202",
        limit=1,
    )

    assert len(first_records) == 1
    assert second_records == []


def test_family_concurrency_runs_selected_scenario_instances(tmp_path: Path) -> None:
    """Verify concurrent family mode runs all selected scenario instances."""
    scenario_run_dir = write_accepted_scenario_run_dir(tmp_path / "scenario-run")
    agent_client = FakePipelineClient(["A1", "A2", "B1", "B2"], [])
    user_client = FakePipelineClient(
        [],
        [
            UserSimulatorOutcome(
                selected_action_id="review_plan", selected_belief_ids=[], rationale="Safe."
            ),
            UserSimulatorOutcome(
                selected_action_id="review_plan", selected_belief_ids=[], rationale="Safe."
            ),
        ],
    )

    records = run_scenarios(
        agent_client=agent_client,  # type: ignore[arg-type]
        user_simulator_client=user_client,  # type: ignore[arg-type]
        experiment_root=tmp_path,
        experiment_config=make_config(scenario_run_dir, family_scenario_concurrency=2),
        scenario_family_ids=["PFM001"],
        scenario_ids=["PFM001_T1_R1", "PFM001_T1_R2"],
        prompt_conditions=["neutral"],
        persona_ids=["neutral_baseline"],
        run_id="20260717T030303",
    )

    assert sorted(record.run_unit.scenario_id for record in records) == [
        "PFM001_T1_R1",
        "PFM001_T1_R2",
    ]
    assert len(agent_client.text_calls) == 4
