"""Cost, execute, freeze, and manually adjudicate judge calls."""

from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence

from pydantic import ValidationError

from srcv2.common import artifact_sha256, utc_now
from srcv2.llm.openrouter import OpenRouterClient, ProviderReply
from srcv2.models.enums import JudgeContract, JudgeStage
from srcv2.models.experiments import GenerationControls, ProviderSnapshot
from srcv2.models.scoring import (
    AdjudicatedJudgment,
    FrozenJudgeContract,
    JudgeCallRecord,
    JudgeExecutionApproval,
    JudgeExecutionEstimate,
    JudgeOutput,
    JudgeOverride,
    JudgePilotSample,
    JudgeTask,
)
from srcv2.scoring.judges import judge_contract_sha256, judge_controls, parse_judge_output, validation_error_text
from srcv2.storage import read_json, write_json


def judge_plan_sha256(tasks: Sequence[JudgeTask]) -> str:
    """Hash one ordered judge plan after checking unique calls and one stage."""
    if not tasks or len({task.judge_call_id for task in tasks}) != len(tasks):
        raise ValueError("judge plan must contain unique calls")
    if len({task.stage for task in tasks}) != 1:
        raise ValueError("one judge plan cannot mix pilot and full calls")
    return artifact_sha256([task.model_dump(mode="json") for task in tasks])


def build_execution_estimate(
    tasks: Sequence[JudgeTask],
    base_controls: GenerationControls,
    input_price_per_million: Decimal,
    output_price_per_million: Decimal,
    estimated_at: Optional[datetime] = None,
) -> JudgeExecutionEstimate:
    """Calculate a conservative list-price ceiling for one exact judge plan."""
    if input_price_per_million < 0 or output_price_per_million < 0:
        raise ValueError("judge token prices cannot be negative")
    input_characters = sum(len(message["content"]) for task in tasks for message in task.messages)
    input_tokens = max((input_characters + 2) // 3, 1)
    output_tokens = sum(judge_controls(base_controls, task.contract).max_output_tokens for task in tasks)
    cost = Decimal(input_tokens) * input_price_per_million / Decimal(1_000_000)
    cost += Decimal(output_tokens) * output_price_per_million / Decimal(1_000_000)
    return JudgeExecutionEstimate(
        judge_plan_sha256=judge_plan_sha256(tasks),
        call_count=len(tasks),
        input_token_estimate=input_tokens,
        output_token_ceiling=output_tokens,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
        estimated_max_cost=cost.quantize(Decimal("0.01"), rounding=ROUND_CEILING),
        estimated_at=estimated_at or utc_now(),
    )


def build_execution_approval(
    estimate: JudgeExecutionEstimate,
    approved_max_cost: Decimal,
    approved_by: str,
    approval_note: str,
    approved_at: Optional[datetime] = None,
) -> JudgeExecutionApproval:
    """Build one canonical paid approval for an exact judge plan."""
    if approved_max_cost < estimate.estimated_max_cost:
        raise ValueError("approved maximum cost is below the judge estimate")
    base = {
        "schema_version": "4.0.0",
        "judge_plan_sha256": estimate.judge_plan_sha256,
        "estimate_sha256": artifact_sha256(estimate),
        "approved_max_cost": approved_max_cost,
        "approved_by": approved_by,
        "approved_at": approved_at or utc_now(),
        "approval_note": approval_note,
    }
    return JudgeExecutionApproval.model_validate({**base, "approval_sha256": artifact_sha256(base)})


def require_execution_approval(tasks: Sequence[JudgeTask], estimate: JudgeExecutionEstimate, approval: JudgeExecutionApproval) -> None:
    """Reject an approval that does not cover the exact plan and estimate."""
    plan_sha256 = judge_plan_sha256(tasks)
    if estimate.judge_plan_sha256 != plan_sha256 or approval.judge_plan_sha256 != plan_sha256:
        raise PermissionError("judge plan, estimate, and approval do not match")
    if approval.estimate_sha256 != artifact_sha256(estimate):
        raise PermissionError("judge approval belongs to a different estimate")
    if approval.approved_max_cost < estimate.estimated_max_cost:
        raise PermissionError("judge approval does not cover the estimated maximum cost")


def _response_text(task: JudgeTask) -> str:
    """Read the response text from the task's minimal JSON payload."""
    payload = json.loads(task.messages[1]["content"])
    response_text = payload.get("response_text")
    if not isinstance(response_text, str):
        raise ValueError("judge task payload does not contain response_text")
    return response_text


def _record(task: JudgeTask, model: ProviderSnapshot, reply: ProviderReply) -> JudgeCallRecord:
    """Parse one semantic response once and retain any structural failure."""
    output: Optional[JudgeOutput] = None
    validation_error: Optional[str] = None
    try:
        output = parse_judge_output(task.contract, reply.text, _response_text(task))
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        validation_error = validation_error_text(error)
    return JudgeCallRecord(
        judge_call_id=task.judge_call_id,
        run_unit_id=task.run_unit_id,
        stage=task.stage,
        contract=task.contract,
        fact_id=task.fact_id,
        prompt_sha256=task.prompt_sha256,
        contract_sha256=task.contract_sha256,
        judge_model_slug=model.model_slug,
        provider_request_id=reply.provider_request_id,
        provider_name=reply.provider_name,
        returned_model_version=reply.returned_model_version,
        raw_response=reply.text,
        output=output,
        structurally_valid=output is not None,
        validation_error=validation_error,
        finish_reason=reply.finish_reason,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        billed_cost=reply.billed_cost,
        received_at=reply.received_at,
        attempts=reply.attempts,
    )


def execute_judge_task(
    task: JudgeTask,
    model: ProviderSnapshot,
    base_controls: GenerationControls,
    client: OpenRouterClient,
) -> JudgeCallRecord:
    """Execute one call with transport-only retries and no semantic regeneration."""
    if task.contract_sha256 != judge_contract_sha256(task.contract):
        raise PermissionError("judge task does not match the source-owned prompt contract")
    reply = client.complete(model, judge_controls(base_controls, task.contract), task.messages)
    return _record(task, model, reply)


def _cached_record(path: Path, task: JudgeTask, model: ProviderSnapshot) -> Optional[JudgeCallRecord]:
    """Reuse only a cache record that matches the exact task and judge model."""
    if not path.exists():
        return None
    record = JudgeCallRecord.model_validate(read_json(path))
    expected = (task.judge_call_id, task.prompt_sha256, task.contract_sha256, model.model_slug)
    actual = (record.judge_call_id, record.prompt_sha256, record.contract_sha256, record.judge_model_slug)
    if actual != expected:
        raise FileExistsError("cached judge record belongs to another task or model")
    return record


def execute_judge_batch(
    tasks: Sequence[JudgeTask],
    model: ProviderSnapshot,
    base_controls: GenerationControls,
    client_factory: Callable[[], OpenRouterClient],
    estimate: JudgeExecutionEstimate,
    approval: JudgeExecutionApproval,
    cache_directory: Path,
    max_workers: int = 8,
    progress: Optional[Callable[[int, int, JudgeCallRecord], None]] = None,
) -> List[JudgeCallRecord]:
    """Execute or resume one approved judge plan while preserving malformed outputs."""
    require_execution_approval(tasks, estimate, approval)
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    cache_directory.mkdir(parents=True, exist_ok=True)
    completed: Dict[str, JudgeCallRecord] = {}
    pending: List[JudgeTask] = []
    for task in tasks:
        existing = _cached_record(cache_directory / f"{task.judge_call_id}.json", task, model)
        if existing is None:
            pending.append(task)
        else:
            if existing.billed_cost is None:
                raise RuntimeError("cached judge record has no billed cost")
            completed[task.judge_call_id] = existing
    billed = sum((record.billed_cost or Decimal(0) for record in completed.values()), Decimal(0))
    if billed > approval.approved_max_cost:
        raise PermissionError("cached judge cost exceeds the approved maximum")
    reserve = estimate.estimated_max_cost / estimate.call_count

    def execute(task: JudgeTask) -> JudgeCallRecord:
        """Execute one task with a worker-owned scoring client."""
        return execute_judge_task(task, model, base_controls, client_factory())

    iterator = iter(pending)
    futures: Dict[Future[JudgeCallRecord], JudgeTask] = {}
    first_error: Optional[Exception] = None
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            while first_error is None and len(futures) < max_workers and billed + reserve * (len(futures) + 1) <= approval.approved_max_cost:
                try:
                    task = next(iterator)
                except StopIteration:
                    break
                futures[executor.submit(execute, task)] = task
            if not futures:
                if first_error is not None:
                    raise first_error
                try:
                    next(iterator)
                except StopIteration:
                    break
                raise PermissionError("approved cost remaining is below the per-call reserve")
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                task = futures.pop(future)
                try:
                    record = future.result()
                except Exception as error:
                    first_error = first_error or error
                    continue
                write_json(cache_directory / f"{task.judge_call_id}.json", record)
                if record.billed_cost is None:
                    first_error = first_error or RuntimeError("provider omitted judge-call cost; response was preserved and execution stopped")
                    continue
                billed += record.billed_cost
                if billed > approval.approved_max_cost:
                    first_error = first_error or PermissionError("judge charges exceed the approved maximum; execution stopped")
                completed[task.judge_call_id] = record
                if progress is not None:
                    progress(len(completed), len(tasks), record)
    return [completed[task.judge_call_id] for task in tasks]


def merge_judge_records(tasks: Sequence[JudgeTask], record_sets: Sequence[Sequence[JudgeCallRecord]]) -> List[JudgeCallRecord]:
    """Assemble one ordered plan from reusable and replacement raw judge records."""
    task_by_id = {task.judge_call_id: task for task in tasks}
    if len(task_by_id) != len(tasks):
        raise ValueError("judge plan requires unique call identifiers")
    matching: Dict[str, JudgeCallRecord] = {}
    for records in record_sets:
        for record in records:
            if record.judge_call_id not in task_by_id:
                continue
            if record.judge_call_id in matching:
                raise ValueError("matching judge records must be unique across sources")
            matching[record.judge_call_id] = record
    if set(matching) != set(task_by_id):
        missing = sorted(set(task_by_id) - set(matching))
        raise ValueError("judge record sources do not cover the plan: " + ", ".join(missing[:5]))
    ordered: List[JudgeCallRecord] = []
    for task in tasks:
        record = matching[task.judge_call_id]
        expected = (task.run_unit_id, task.stage, task.contract, task.fact_id, task.prompt_sha256, task.contract_sha256)
        actual = (record.run_unit_id, record.stage, record.contract, record.fact_id, record.prompt_sha256, record.contract_sha256)
        if actual != expected:
            raise ValueError(f"judge record does not match plan task {task.judge_call_id}")
        ordered.append(record)
    return ordered


def freeze_judge_contract(
    sample: JudgePilotSample,
    tasks: Sequence[JudgeTask],
    records: Sequence[JudgeCallRecord],
    adjudicated: Sequence[AdjudicatedJudgment],
    model: ProviderSnapshot,
    base_controls: GenerationControls,
    frozen_at: Optional[datetime] = None,
) -> FrozenJudgeContract:
    """Freeze reviewed contracts after every raw pilot call has an adjudicated label."""
    if len(tasks) != 191 * 8 or any(task.stage != JudgeStage.PILOT for task in tasks):
        raise ValueError("contract freeze requires one complete 191-response pilot plan")
    validate_pilot_adjudication(tasks, records, adjudicated, model.model_slug)
    selected_response_ids = list(dict.fromkeys(task.run_unit_id for task in tasks))
    if selected_response_ids != sample.response_ids:
        raise ValueError("pilot plan does not match the frozen 191-response sample")
    controls = {contract: judge_controls(base_controls, contract) for contract in JudgeContract}
    contract_hashes = {contract: judge_contract_sha256(contract) for contract in JudgeContract}
    base = {
        "schema_version": "4.0.0",
        "state": "frozen",
        "judge_model": model,
        "generation_controls": controls,
        "contract_sha256_by_judge": contract_hashes,
        "pilot_sample_sha256": sample.sample_sha256,
        "pilot_results_sha256": artifact_sha256([record.model_dump(mode="json") for record in records]),
        "pilot_adjudicated_sha256": artifact_sha256([judgment.model_dump(mode="json") for judgment in adjudicated]),
        "frozen_at": frozen_at or utc_now(),
    }
    return FrozenJudgeContract.model_validate({**base, "frozen_contract_sha256": artifact_sha256(base)})


def validate_pilot_adjudication(
    tasks: Sequence[JudgeTask],
    records: Sequence[JudgeCallRecord],
    adjudicated: Sequence[AdjudicatedJudgment],
    model_slug: str,
) -> None:
    """Require raw and adjudicated pilot records to match the plan without rewriting failures."""
    expected_coordinates = [
        (task.judge_call_id, task.run_unit_id, task.stage, task.contract, task.fact_id, task.prompt_sha256, task.contract_sha256, model_slug)
        for task in tasks
    ]
    actual_coordinates = [
        (
            record.judge_call_id,
            record.run_unit_id,
            record.stage,
            record.contract,
            record.fact_id,
            record.prompt_sha256,
            record.contract_sha256,
            record.judge_model_slug,
        )
        for record in records
    ]
    if actual_coordinates != expected_coordinates:
        raise ValueError("pilot results must exactly match the ordered pilot plan and judge model")
    adjudicated_coordinates = [(judgment.judge_call_id, judgment.run_unit_id, judgment.contract, judgment.fact_id) for judgment in adjudicated]
    expected_adjudicated_coordinates = [(task.judge_call_id, task.run_unit_id, task.contract, task.fact_id) for task in tasks]
    if adjudicated_coordinates != expected_adjudicated_coordinates:
        raise ValueError("adjudicated pilot labels must exactly match the ordered pilot plan")
    for record, judgment in zip(records, adjudicated):
        if not record.structurally_valid and judgment.source != "manual_override":
            raise ValueError("every structurally invalid raw call requires a manual adjudication")
        if judgment.source == "judge" and (record.output is None or judgment.output != record.output):
            raise ValueError("unmodified adjudicated labels must equal their raw judge outputs")


def validate_full_plan(tasks: Sequence[JudgeTask], contract: FrozenJudgeContract) -> None:
    """Require all full-run tasks to use the reviewed frozen judge contracts."""
    if len(tasks) != 3822 * 8 or any(task.stage != JudgeStage.FULL for task in tasks):
        raise ValueError("full scoring requires 30,576 calls covering all 3,822 responses")
    for task in tasks:
        if task.contract_sha256 != contract.contract_sha256_by_judge[task.contract]:
            raise PermissionError("full judge task differs from the frozen contract")


def adjudicate_judgments(
    tasks: Sequence[JudgeTask], records: Sequence[JudgeCallRecord], overrides: Sequence[JudgeOverride]
) -> List[AdjudicatedJudgment]:
    """Apply reviewed replacements while leaving raw judge records immutable."""
    task_by_id = {task.judge_call_id: task for task in tasks}
    record_by_id = {record.judge_call_id: record for record in records}
    override_by_id = {override.judge_call_id: override for override in overrides}
    if len(task_by_id) != len(tasks) or len(record_by_id) != len(records) or len(override_by_id) != len(overrides):
        raise ValueError("judge tasks, records, and overrides require unique call identifiers")
    if set(record_by_id) != set(task_by_id) or set(override_by_id) - set(record_by_id):
        raise ValueError("records and overrides must reference the supplied judge plan")
    judgments: List[AdjudicatedJudgment] = []
    for task in tasks:
        record = record_by_id[task.judge_call_id]
        override = override_by_id.get(task.judge_call_id)
        if override is not None:
            if override.contract != record.contract or override.original_output_sha256 != artifact_sha256(record.output):
                raise PermissionError("manual override does not match the immutable judge output")
            output = override.replacement_output
            source: Literal["judge", "manual_override"] = "manual_override"
            override_id = override.override_id
        else:
            if record.output is None:
                raise ValueError("invalid judge output requires a manual override before scoring")
            output = record.output
            source = "judge"
            override_id = None
        parsed = parse_judge_output(task.contract, json.dumps(output.model_dump(mode="json")), _response_text(task))
        judgments.append(
            AdjudicatedJudgment(
                judge_call_id=record.judge_call_id,
                run_unit_id=record.run_unit_id,
                contract=record.contract,
                fact_id=record.fact_id,
                output=parsed,
                source=source,
                override_id=override_id,
            )
        )
    return judgments
