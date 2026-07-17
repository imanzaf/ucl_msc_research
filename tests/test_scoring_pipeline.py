"""Tests for the end-to-end scoring orchestration."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, List
from uuid import uuid4

import pytest

from src.data_models.experiments import (
    ConversationProtocol,
    ExperimentConfig,
    ExperimentStage,
    ExperimentUsageSummary,
    GenerationConfig,
    LLMCallRecord,
    LLMCallUsage,
    RunUnitIdentity,
    ScenarioRunRecord,
)
from src.data_models.scenario_review import artifact_sha256
from src.data_models.scenarios import InteractionMode, PromptCondition
from src.data_models.scoring import (
    DirectDisclosureStatus,
    DirectFactDisclosureAssessment,
    DisclaimerWashingCheck,
    FactContradictionCheck,
    FactDisclosureJudgment,
    FactUnitMatching,
    FramingDirection,
    ResponseFactExtraction,
    ResponseMetricBreakdownV6,
)
from src.data_models.user_personas import UserPersonaId
from src.data_models.user_simulator import (
    ConversationSpeaker,
    ConversationTurn,
    UserSimulatorOutcome,
)
from src.experiments.io import append_jsonl
from src.experiments.scoring_pipeline import (
    build_scoring_specs,
    filter_scenario_run_records,
    index_scenario_instances,
    score_one_run,
    score_scenario_runs,
)
from src.llm.openrouter import LLMCallResult
from tests.canonical_scenario_fixtures import write_scenario_run_dir
from tests.v6_scenario_fixtures import make_v6_family


class FakeScoringClient:
    """Fake scoring client returning queued structured outputs."""

    def __init__(self, structured_outputs: List[Any]) -> None:
        """Store structured scoring outputs."""
        self.structured_outputs = list(structured_outputs)
        self.calls: List[Any] = []
        self.lock = Lock()

    def complete_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        """Return the next fake structured output."""
        with self.lock:
            self.calls.append(kwargs)
            parsed = self.structured_outputs.pop(0)
        assert isinstance(parsed, kwargs["output_model"])
        return make_scoring_result(parsed=parsed, stage=kwargs["stage"])


class StageAwareFakeScoringClient:
    """Fake scoring client returning outputs based on requested model type."""

    def complete_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        """Return a structured output matching the requested model."""
        output_model = kwargs["output_model"]
        if output_model is ResponseFactExtraction:
            parsed = ResponseFactExtraction(extracted_facts=[])
        elif output_model is FactUnitMatching:
            parsed = FactUnitMatching(matches=[])
        elif output_model is FactContradictionCheck:
            parsed = FactContradictionCheck(
                has_fact_contradiction=False,
                fact_contradiction_rationale="No contradiction.",
            )
        elif output_model is DisclaimerWashingCheck:
            parsed = DisclaimerWashingCheck(
                has_disclaimer_washing=False,
                disclaimer_washing_rationale="No disclaimer washing.",
            )
        else:
            raise AssertionError(f"unexpected output model: {output_model!r}")
        return make_scoring_result(parsed=parsed, stage=kwargs["stage"])


class StageAwareV6ScoringClient:
    """Return complete stage-specific outputs for one V6 scoring run."""

    max_retries = 0

    def __init__(self, assessment: DirectFactDisclosureAssessment) -> None:
        """Store the complete direct assessment and requested stages."""
        self.assessment = assessment
        self.stages: List[ExperimentStage] = []

    def complete_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        """Return a valid output for each V6 scoring stage."""
        self.stages.append(kwargs["stage"])
        output_model = kwargs["output_model"]
        if output_model is ResponseFactExtraction:
            parsed = ResponseFactExtraction(extracted_facts=[])
        elif output_model is FactUnitMatching:
            parsed = FactUnitMatching(matches=[])
        elif output_model is FactContradictionCheck:
            parsed = FactContradictionCheck(
                has_fact_contradiction=False,
                fact_contradiction_rationale="No contradiction.",
            )
        elif output_model is DirectFactDisclosureAssessment:
            parsed = self.assessment
        else:
            raise AssertionError(f"unexpected V6 output model: {output_model!r}")
        return make_scoring_result(parsed=parsed, stage=kwargs["stage"])


def make_scoring_result(parsed: Any, stage: ExperimentStage) -> LLMCallResult[Any]:
    """Create a fake scoring call result with deterministic usage."""
    record = LLMCallRecord(
        call_id=str(uuid4()),
        stage=stage,
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
        usage=LLMCallUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_credits=0.1),
    )
    return LLMCallResult(parsed=parsed, record=record)


def make_config(scenario_run_dir: Path) -> ExperimentConfig:
    """Create a minimal experiment config for scoring tests."""
    return ExperimentConfig(
        experiment_name="pipeline_scoring_v1",
        scenario_run_dir=str(scenario_run_dir),
        agent_model_ids=["fake/agent"],
        user_simulator_model="fake/simulator",
        scoring_model="fake/scorer",
        generation_config=GenerationConfig(),
        cache_enabled=True,
    )


def make_scenario_run_record(scenario_id: str = "RW001_U01") -> ScenarioRunRecord:
    """Create a completed scenario run aligned with the RW001_U01 fixture."""
    return ScenarioRunRecord(
        experiment_name="pipeline_scoring_v1",
        run_id="20260711T030303",
        run_unit=RunUnitIdentity(
            scenario_family_id="RW001",
            scenario_id=scenario_id,
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


def test_scoring_pipeline_writes_metrics_and_usage(tmp_path: Path) -> None:
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
        experiment_config=make_config(write_scenario_run_dir(tmp_path)),
        scoring_run_id="20260711T040404",
    )

    assert len(records) == 1
    assert records[0].response_metrics.adverse_omission_score == 1.0
    assert records[0].user_harm_metrics is not None
    assert records[0].usage_summary.api_call_count == 4
    matching_prompt = client.calls[1]["messages"][1]["content"]
    assert "Agent context/source packet" in matching_prompt
    assert '"cash_buffer_days":3' in matching_prompt
    assert (experiment_dir / "results" / "20260711T040404_scoring_results.jsonl").exists()

    resumed_records = score_scenario_runs(
        client=FakeScoringClient([]),
        experiment_root=tmp_path,
        experiment_config=make_config(write_scenario_run_dir(tmp_path)).model_copy(
            update={"resume": True}
        ),
        scoring_run_id="20260711T040404",
    )
    usage_path = experiment_dir / "results" / "20260711T040404_scoring_usage.json"
    usage = ExperimentUsageSummary.model_validate_json(usage_path.read_text(encoding="utf-8"))

    assert resumed_records == []
    assert usage.api_call_count == 4
    assert usage.total_tokens == 8


def test_scoring_pipeline_can_score_records_concurrently(tmp_path: Path) -> None:
    """Verify scoring can process multiple run records with bounded concurrency."""
    experiment_dir = tmp_path / "pipeline_scoring_v1"
    result_path = experiment_dir / "results" / "20260711T050505_results.jsonl"
    append_jsonl(
        path=result_path,
        records=[make_scenario_run_record("RW001_U01"), make_scenario_run_record("RW001_U02")],
    )

    records = score_scenario_runs(
        client=StageAwareFakeScoringClient(),
        experiment_root=tmp_path,
        experiment_config=make_config(write_scenario_run_dir(tmp_path)).model_copy(
            update={"scoring_concurrency": 2}
        ),
        scoring_run_id="20260711T060606",
    )

    assert len(records) == 2
    assert {record.run_unit.scenario_id for record in records} == {"RW001_U01", "RW001_U02"}
    assert (experiment_dir / "results" / "20260711T060606_scoring_results.jsonl").exists()


def test_v6_scoring_uses_direct_assessment_without_disclaimer_call() -> None:
    """Verify the V6 branch persists direct metrics and skips legacy disclaimer judging."""
    family = make_v6_family()
    instance = family.scenario_instances[0]
    assessment = DirectFactDisclosureAssessment(
        judgments=[
            FactDisclosureJudgment(
                fact_unit_id=fact_unit.fact_unit_id,
                checkpoint=checkpoint,
                disclosure_status=DirectDisclosureStatus.OMITTED,
                evidence_quotes=[],
                preserved_specificity_markers=[],
                framing_direction=FramingDirection.NOT_APPLICABLE,
                rationale="The fact is absent from this response.",
            )
            for fact_unit in instance.fact_units
            for checkpoint in fact_unit.expected_checkpoints
        ],
        assessment_summary="No controlled facts were disclosed.",
    )
    record = ScenarioRunRecord(
        experiment_name="pipeline_scoring_v1",
        run_id="20260715T030303",
        run_unit=RunUnitIdentity(
            scenario_family_id=family.scenario_family_id,
            scenario_id=instance.scenario_id,
            interaction_mode=InteractionMode.MULTI_TURN,
            prompt_condition=PromptCondition.NEUTRAL,
            persona_id=UserPersonaId.NEUTRAL_BASELINE,
            agent_model_id="fake/agent",
            scenario_family_sha256=artifact_sha256(family),
        ),
        scenario_schema_version=family.schema_version,
        conversation_protocol=ConversationProtocol.SCRIPTED_RISK_FOLLOWUP_V1,
        system_prompt="You are a financial assistant.",
        initial_user_prompt=instance.core_initial_request,
        transcript=[
            ConversationTurn(
                speaker=ConversationSpeaker.USER,
                turn_index=1,
                content=instance.core_initial_request,
            ),
            ConversationTurn(
                speaker=ConversationSpeaker.AGENT,
                turn_index=2,
                content="I cannot provide an assessment.",
            ),
            ConversationTurn(
                speaker=ConversationSpeaker.USER,
                turn_index=3,
                content=instance.core_risk_followup,
            ),
            ConversationTurn(
                speaker=ConversationSpeaker.AGENT,
                turn_index=4,
                content="I have nothing further to add.",
            ),
        ],
        user_simulator_outcome=UserSimulatorOutcome(
            selected_action_id="review_plan",
            selected_belief_ids=["supported"],
            rationale="The user reviews the plan.",
        ),
    )
    client = StageAwareV6ScoringClient(assessment)

    scored = score_one_run(
        client=client,
        experiment_name="pipeline_scoring_v1",
        scoring_run_id="20260715T040404",
        scenario_record=record,
        instance=instance,
        scoring_model="fake/scorer",
        generation_config=GenerationConfig(),
    )

    assert isinstance(scored.response_metrics, ResponseMetricBreakdownV6)
    assert scored.direct_disclosure_assessment is not None
    assert scored.disclaimer_washing_check is None
    assert ExperimentStage.DISCLAIMER_WASHING_CHECK not in client.stages
    assert client.stages.count(ExperimentStage.DIRECT_FACT_DISCLOSURE_ASSESSMENT) == 1


def test_v6_scoring_rejects_transcript_from_different_family_artifact() -> None:
    """Verify scoring cannot join a V6 transcript to a same-ID replacement family."""
    family = make_v6_family()
    instance = family.scenario_instances[0]
    wrong_hash = "0" * 64
    assert wrong_hash != artifact_sha256(family)
    record = ScenarioRunRecord.model_construct(
        run_unit=RunUnitIdentity(
            scenario_family_id=family.scenario_family_id,
            scenario_id=instance.scenario_id,
            interaction_mode=InteractionMode.MULTI_TURN,
            prompt_condition=PromptCondition.NEUTRAL,
            persona_id=UserPersonaId.NEUTRAL_BASELINE,
            agent_model_id="fake/agent",
            scenario_family_sha256=wrong_hash,
        )
    )

    with pytest.raises(ValueError, match="scenario artifact hash mismatch"):
        build_scoring_specs(
            scenario_records=[record],
            scenario_index=index_scenario_instances([family]),
            skip_ids=[],
        )


def test_scoring_filters_run_units_before_loading_family_gates() -> None:
    """Verify targeted scoring derives artifact families only from selected records."""
    records = [
        ScenarioRunRecord.model_construct(
            run_unit=RunUnitIdentity(
                scenario_family_id=family_id,
                scenario_id=f"{family_id}_T1_R1",
                interaction_mode=InteractionMode.MULTI_TURN,
                prompt_condition=PromptCondition.NEUTRAL,
                persona_id=UserPersonaId.NEUTRAL_BASELINE,
                agent_model_id="fake/agent",
            )
        )
        for family_id in ["PFM001", "RW001"]
    ]

    filtered = filter_scenario_run_records(
        scenario_records=records,
        skip_ids=[],
        run_unit_ids=[records[0].run_unit.run_unit_id],
    )

    assert [record.run_unit.scenario_family_id for record in filtered] == ["PFM001"]
