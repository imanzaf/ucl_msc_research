"""Minimal three-judge prompt, parsing, and adjudication tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from srcv2.common import artifact_sha256
from srcv2.models.enums import Affect, JudgeContract, JudgeStage, QueryLength
from srcv2.models.experiments import GenerationControls, ResponseMetadata, RunUnit
from srcv2.models.queries import QueryVariant
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import AccuracyJudgeOutput, ContentJudgeOutput, JudgeCallRecord, JudgeOverride
from srcv2.prompts.rendering import displayed_option_names
from srcv2.scoring.execution import (
    adjudicate_judgments,
    build_execution_approval,
    build_execution_estimate,
    merge_judge_records,
    validate_pilot_adjudication,
)
from srcv2.scoring.judges import (
    ACCURACY_PROMPT,
    CONTENT_PROMPT,
    PRESENTATION_PROMPT,
    build_judge_tasks,
    content_extraction,
    judge_controls,
    judge_output_schema,
    parse_judge_output,
)


def _query(scenario: AcceptedScenario) -> QueryVariant:
    """Build the visible neutral query used by synthetic judge tasks."""
    return QueryVariant(
        query_variant_id="query_123",
        scenario_id=scenario.scenario_id,
        affect=Affect.NEUTRAL,
        query_length=QueryLength.SHORT,
        text="What are my options for this financial decision?",
    )


def _run(scenario: AcceptedScenario, response_text: str) -> RunUnit:
    """Build one completed synthetic evaluated run."""
    timestamp = datetime.now(UTC)
    return RunUnit.model_validate(
        {
            "run_unit_id": "run_1234567890123456",
            "experiment": "single_fact_priority_v1",
            "cell": {"kind": "single_fact_priority_v1"},
            "scenario_id": scenario.scenario_id,
            "query_variant_id": "query_123",
            "prompt_sha256": "0" * 64,
            "response_contract_sha256": "1" * 64,
            "model": {
                "model_slug": "test/model",
                "model_access": "closed",
                "licence_category": "proprietary",
                "provider_name": "test",
                "provider_endpoint": "test",
                "routing_policy": "openrouter_default_require_parameters",
                "metadata_snapshot_sha256": "2" * 64,
                "preflight_passed": True,
            },
            "generation_controls": {"max_output_tokens": 100},
            "response": ResponseMetadata(
                raw_response=response_text,
                structurally_valid=True,
                adherent=True,
                received_at=timestamp,
            ),
        }
    )


def test_one_model_uses_three_minimal_judge_contracts(accepted_scenario: AcceptedScenario) -> None:
    """Build six content calls plus one presentation and one accuracy call without hidden labels."""
    response = f"The first option has {accepted_scenario.facts[0].anchor}."
    query = _query(accepted_scenario)
    run = _run(accepted_scenario, response)
    tasks = build_judge_tasks(run, accepted_scenario, query, JudgeStage.PILOT)
    assert len(tasks) == 8
    assert [task.contract for task in tasks].count(JudgeContract.CONTENT) == 6
    assert [task.contract for task in tasks].count(JudgeContract.PRESENTATION) == 1
    assert [task.contract for task in tasks].count(JudgeContract.ACCURACY) == 1
    content_payload = json.loads(tasks[0].messages[1]["content"])
    assert set(content_payload) == {"response_text", "candidate_fact_text", "anchor"}
    assert "direction" not in tasks[0].messages[1]["content"]
    presentation_payload = json.loads(tasks[6].messages[1]["content"])
    assert set(presentation_payload) == {"response_text", "option_a_name", "option_b_name"}
    accuracy_payload = json.loads(tasks[7].messages[1]["content"])
    assert set(accuracy_payload) == {"response_text", "assistant_context", "customer_query", "option_names", "reference_facts"}
    assert accuracy_payload["customer_query"] == query.text
    assert accepted_scenario.deployment_context.authority_limits[0] in accuracy_payload["assistant_context"]
    names = displayed_option_names(accepted_scenario, run.cell)
    assert accuracy_payload["option_names"] == [names["OPTION_A"], names["OPTION_B"]]
    assert len(accuracy_payload["reference_facts"]) == 6
    assert "underlying proposition" in CONTENT_PROMPT
    assert "same product or topic is not enough" in CONTENT_PROMPT
    assert "Separately mark anchor_present" in CONTENT_PROMPT
    assert "'happy to help'" in PRESENTATION_PROMPT
    assert "assistant offering more help" in PRESENTATION_PROMPT
    assert "discussing only one option is balanced_or_none" in PRESENTATION_PROMPT
    assert "uncertain or conditional statements" in ACCURACY_PROMPT
    assert "supplied context or facts" in ACCURACY_PROMPT


def test_fenced_exact_budget_judges_receive_only_answer_text(accepted_scenario: AcceptedScenario) -> None:
    """Remove a complete JSON fence from judge input without changing the frozen response."""
    fact_ids = [fact.fact_id for fact in accepted_scenario.facts[:2]]
    raw_response = f'```json\n{{"selected_fact_ids":{json.dumps(fact_ids)},"answer_text":"Only this prose is judged."}}\n```'
    payload = _run(accepted_scenario, raw_response).model_dump(mode="json")
    payload["experiment"] = "information_budget_v1"
    payload["cell"] = {"kind": "information_budget_v1", "affect": "neutral", "exact_fact_budget": 2}
    tasks = build_judge_tasks(RunUnit.model_validate(payload), accepted_scenario, _query(accepted_scenario), JudgeStage.PILOT)
    for task in tasks:
        request = json.loads(task.messages[1]["content"])
        assert request["response_text"] == "Only this prose is judged."


def test_judge_outputs_are_small_and_offsets_are_derived() -> None:
    """Parse exact JSON and compute evidence position in code rather than asking the judge."""
    response = "Opening. The fee is £499. Closing."
    raw = json.dumps({"fact_present": True, "anchor_present": True, "supporting_excerpt": "The fee is £499."})
    output = parse_judge_output(JudgeContract.CONTENT, raw, response)
    assert isinstance(output, ContentJudgeOutput)
    extraction = content_extraction(response, output)
    assert extraction.first_character_offset == 9
    properties = judge_output_schema(JudgeContract.CONTENT)["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {
        "fact_present",
        "anchor_present",
        "supporting_excerpt",
    }


def test_superficial_evidence_differences_map_to_original_text() -> None:
    """Resolve quotation, case, and Markdown differences without semantic matching."""
    response = "Opening. **The fee is £499.** Closing."
    content_raw = json.dumps(
        {
            "fact_present": True,
            "anchor_present": True,
            "supporting_excerpt": '"the fee is £499."',
        }
    )
    content = parse_judge_output(JudgeContract.CONTENT, content_raw, response)
    assert isinstance(content, ContentJudgeOutput)
    assert content.supporting_excerpt == "The fee is £499."
    assert content_extraction(response, content).first_character_offset == 11

    accuracy_raw = json.dumps({"issues": [{"evidence": "opening. the fee is £499.", "kind": "unsupported", "numerical": True}]})
    accuracy = parse_judge_output(JudgeContract.ACCURACY, accuracy_raw, response)
    assert isinstance(accuracy, AccuracyJudgeOutput)
    assert accuracy.issues[0].evidence == "Opening. **The fee is £499."


def test_unlocatable_evidence_requires_manual_review() -> None:
    """Send paraphrased or unlocatable evidence to the manual-override workflow."""
    raw = json.dumps({"issues": [{"evidence": "invented quote", "kind": "unsupported", "numerical": False}]})
    with pytest.raises(ValueError, match="requires manual review"):
        parse_judge_output(JudgeContract.ACCURACY, raw, "Actual response text")


def test_contract_specific_controls_and_paid_approval(accepted_scenario: AcceptedScenario) -> None:
    """Bind strict schemas, small output ceilings, estimate, and approval to an exact plan."""
    tasks = build_judge_tasks(_run(accepted_scenario, "A response."), accepted_scenario, _query(accepted_scenario), JudgeStage.PILOT)
    base = GenerationControls(max_output_tokens=1024, seed=7, reasoning_effort="medium")
    assert judge_controls(base, JudgeContract.CONTENT).max_output_tokens == 1024
    assert judge_controls(base, JudgeContract.PRESENTATION).reasoning_effort == "medium"
    assert judge_controls(base, JudgeContract.PRESENTATION).max_output_tokens == 1024
    assert judge_controls(base, JudgeContract.ACCURACY).max_output_tokens == 2048
    estimate = build_execution_estimate(tasks, base, Decimal("0.10"), Decimal("0.40"))
    approval = build_execution_approval(estimate, estimate.estimated_max_cost, "researcher", "Approved test plan")
    assert approval.judge_plan_sha256 == estimate.judge_plan_sha256


def test_manual_override_preserves_raw_record(accepted_scenario: AcceptedScenario) -> None:
    """Apply a typed correction separately from the immutable raw judge response."""
    task = build_judge_tasks(_run(accepted_scenario, "A response."), accepted_scenario, _query(accepted_scenario), JudgeStage.FULL)[0]
    timestamp = datetime.now(UTC)
    original = ContentJudgeOutput(fact_present=False, anchor_present=False, supporting_excerpt=None)
    record = JudgeCallRecord(
        judge_call_id=task.judge_call_id,
        run_unit_id=task.run_unit_id,
        stage=task.stage,
        contract=task.contract,
        fact_id=task.fact_id,
        prompt_sha256=task.prompt_sha256,
        contract_sha256=task.contract_sha256,
        judge_model_slug="openai/gpt-5.4-mini",
        provider_request_id="request_1",
        returned_model_version="openai/gpt-5.4-mini",
        raw_response=original.model_dump_json(),
        output=original,
        structurally_valid=True,
        validation_error=None,
        input_tokens=10,
        output_tokens=5,
        billed_cost=Decimal("0.001"),
        received_at=timestamp,
        attempts=1,
    )
    replacement = ContentJudgeOutput(fact_present=True, anchor_present=False, supporting_excerpt="A response.")
    override = JudgeOverride(
        override_id="override_1234567890123456",
        judge_call_id=task.judge_call_id,
        contract=task.contract,
        original_output_sha256=artifact_sha256(original),
        replacement_output=replacement,
        reason="Manual review found a semantically equivalent statement.",
        researcher_id="researcher",
        corrected_at=timestamp,
    )
    adjudicated = adjudicate_judgments([task], [record], [override])
    validate_pilot_adjudication([task], [record], adjudicated, "openai/gpt-5.4-mini")
    assert adjudicated[0].source == "manual_override"
    assert adjudicated[0].output == replacement
    assert record.output == original


def test_merge_judge_records_reuses_only_exact_plan_matches(accepted_scenario: AcceptedScenario) -> None:
    """Order reusable raw records by the target plan and ignore superseded calls."""
    tasks = build_judge_tasks(_run(accepted_scenario, "A response."), accepted_scenario, _query(accepted_scenario), JudgeStage.PILOT)
    timestamp = datetime.now(UTC)
    records = [
        JudgeCallRecord(
            judge_call_id=task.judge_call_id,
            run_unit_id=task.run_unit_id,
            stage=task.stage,
            contract=task.contract,
            fact_id=task.fact_id,
            prompt_sha256=task.prompt_sha256,
            contract_sha256=task.contract_sha256,
            judge_model_slug="openai/gpt-5.4-mini",
            provider_request_id=f"request_{index}",
            returned_model_version="openai/gpt-5.4-mini",
            raw_response="{}",
            output=None,
            structurally_valid=False,
            validation_error="synthetic",
            input_tokens=10,
            output_tokens=5,
            billed_cost=Decimal("0.001"),
            received_at=timestamp,
            attempts=1,
        )
        for index, task in enumerate(tasks)
    ]
    assert merge_judge_records(tasks, [list(reversed(records[:6])), records[6:]]) == records
