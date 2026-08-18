"""Auditable single-turn execution with approval, cache, and immutable output records."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from srcv2.common import artifact_sha256, utc_now
from srcv2.experiments.matrix import MatrixAssignment
from srcv2.experiments.responses import check_word_budget, parse_exact_budget_output
from srcv2.llm.openrouter import OpenRouterClient, ProviderReply
from srcv2.models.enums import CommercialInterestTask, ExecutionStatus
from srcv2.models.experiments import (
    AttemptMetadata,
    CommercialInterestCell,
    GenerationControls,
    InformationBudgetCell,
    ProviderSnapshot,
    ResponseMetadata,
    RunUnit,
    WordBudgetCell,
)
from srcv2.prompts.rendering import RenderedPrompt
from srcv2.storage import read_json, write_json


def _response_metadata(reply: ProviderReply, assignment: MatrixAssignment, valid_fact_ids: List[str]) -> ResponseMetadata:
    """Score adherence while retaining every semantic provider response exactly once."""
    selected_ids: Optional[List[str]] = None
    answer_text: Optional[str] = reply.text
    structurally_valid = True
    adherent = True
    truncated = reply.finish_reason in {"length", "max_tokens"}
    if isinstance(assignment.cell, InformationBudgetCell):
        adherence = parse_exact_budget_output(reply.text, assignment.cell.exact_fact_budget, valid_fact_ids)
        selected_ids = adherence.selected_fact_ids
        answer_text = adherence.answer_text
        structurally_valid = adherence.structurally_valid
        adherent = adherence.adherent
    elif isinstance(assignment.cell, WordBudgetCell):
        adherence = check_word_budget(reply.text, assignment.cell.word_budget, reply.finish_reason)
        adherent = adherence.adherent
        truncated = adherence.truncated
    elif isinstance(assignment.cell, CommercialInterestCell):
        if assignment.cell.task == CommercialInterestTask.EXACT_BUDGET:
            if assignment.cell.exact_fact_budget is None:
                raise ValueError("commercial exact-budget assignment is missing its budget coordinate")
            exact_adherence = parse_exact_budget_output(reply.text, assignment.cell.exact_fact_budget, valid_fact_ids)
            selected_ids = exact_adherence.selected_fact_ids
            answer_text = exact_adherence.answer_text
            structurally_valid = exact_adherence.structurally_valid
            word_adherence = check_word_budget(answer_text or "", assignment.cell.word_budget, reply.finish_reason)
            adherent = exact_adherence.adherent and word_adherence.adherent
            truncated = word_adherence.truncated
        else:
            word_adherence = check_word_budget(reply.text, assignment.cell.word_budget, reply.finish_reason)
            adherent = word_adherence.adherent
            truncated = word_adherence.truncated
    return ResponseMetadata(
        raw_response=reply.text,
        returned_model_version=reply.returned_model_version,
        provider_name=reply.provider_name,
        selected_fact_ids=selected_ids,
        answer_text=answer_text,
        structurally_valid=structurally_valid,
        adherent=adherent,
        finish_reason=reply.finish_reason,
        truncated=truncated,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        billed_cost=reply.billed_cost,
        received_at=reply.received_at,
    )


def execute_assignment(
    assignment: MatrixAssignment,
    prompt: RenderedPrompt,
    model: ProviderSnapshot,
    controls: GenerationControls,
    valid_fact_ids: List[str],
    client: OpenRouterClient,
) -> RunUnit:
    """Execute one frozen assignment or reuse its exact immutable cache record."""
    if assignment.execution_status != ExecutionStatus.ACTIVE:
        raise PermissionError("deferred assignments cannot be executed")
    if assignment.cell.kind != prompt.experiment or assignment.scenario_id != prompt.scenario_id:
        raise ValueError("assignment and rendered prompt do not match")
    started = utc_now()
    reply = client.complete(model, controls, prompt.messages)
    attempts = [
        AttemptMetadata(
            attempt_number=attempt,
            started_at=started,
            completed_at=reply.received_at if attempt == reply.attempts else started,
            provider_request_id=reply.provider_request_id if attempt == reply.attempts else None,
            transport_failure=attempt != reply.attempts,
            semantic_response_received=attempt == reply.attempts,
            error_type="transport_or_provider_failure" if attempt != reply.attempts else None,
            error_message="retryable failure produced no semantic response" if attempt != reply.attempts else None,
        )
        for attempt in range(1, reply.attempts + 1)
    ]
    return RunUnit(
        run_unit_id=assignment.assignment_id,
        experiment=assignment.cell.kind,
        cell=assignment.cell,
        scenario_id=assignment.scenario_id,
        query_variant_id=prompt.query_variant_id,
        prompt_sha256=prompt.prompt_sha256,
        response_contract_sha256=prompt.response_contract_sha256,
        model=model,
        generation_controls=controls,
        response=_response_metadata(reply, assignment, valid_fact_ids),
        attempts=attempts,
    )


def cached_run(path: Path, expected_assignment_id: str) -> Optional[RunUnit]:
    """Load a matching immutable run record without making another provider call."""
    if not path.exists():
        return None
    run = RunUnit.model_validate(read_json(path))
    if run.run_unit_id != expected_assignment_id:
        raise ValueError("cached run-unit identifier does not match assignment")
    return run


def write_run_cache(path: Path, run: RunUnit) -> None:
    """Write one semantic response record under its stable assignment identifier."""
    if path.exists():
        existing = RunUnit.model_validate(read_json(path))
        if artifact_sha256(existing) != artifact_sha256(run):
            raise FileExistsError("refusing to overwrite a different semantic response")
        return
    write_json(path, run)
