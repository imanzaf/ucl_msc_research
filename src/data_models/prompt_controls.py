"""Byte-level factor-isolation checks for compiled experiment prompts."""

from __future__ import annotations

from typing import Dict, Iterable, List

from src.data_models.experiments import MessageRole, RunUnit
from src.data_models.study import BRIEF_REQUEST, CONCISION_INSTRUCTION, ExpressedConcernCondition, StudyStage


def _message_content(run_unit: RunUnit, role: MessageRole) -> str:
    """Return the one initial message having the requested role."""
    matching = [message.content for message in run_unit.initial_request_messages if message.role == role]
    if len(matching) != 1:
        raise ValueError(f"initial request must contain exactly one {role.value} message")
    return matching[0]


def _canonical_system_message(run_unit: RunUnit) -> str:
    """Remove only the optional concision instruction from the system message."""
    return _message_content(run_unit, MessageRole.SYSTEM).replace(f"\n- {CONCISION_INSTRUCTION}", "")


def validate_condition_query(run_unit: RunUnit) -> None:
    """Require one natural initial user query and one distinct shared follow-up."""
    query = _message_content(run_unit, MessageRole.USER).strip()
    follow_up = run_unit.follow_up_message.content.strip()
    condition_query = query.removesuffix(f" {BRIEF_REQUEST}") if run_unit.cell.stage == StudyStage.BREVITY_LOCUS else query
    if not condition_query.endswith("?") or not follow_up.endswith("?"):
        raise ValueError("initial and follow-up user turns must be natural questions")
    if condition_query.casefold() == follow_up.casefold():
        raise ValueError("initial and follow-up user queries must differ")


def validate_prompt_factor_isolation(run_units: Iterable[RunUnit]) -> None:
    """Require a complete 2×2 block to vary only concision guidance and the authored query."""
    units = list(run_units)
    if len(units) != 4:
        raise ValueError("prompt-isolation validation requires exactly four run units")
    expected_pairs = {(condition, cue) for condition in {"baseline", "concise"} for cue in {"neutral", "concerned"}}
    observed_pairs = {(unit.cell.concision.value, unit.cell.expressed_concern.value) for unit in units}
    if observed_pairs != expected_pairs:
        raise ValueError("block must contain every concision-instruction and expressed-concern combination")
    if len({_canonical_system_message(unit) for unit in units}) != 1:
        raise ValueError("compiled system prompts differ outside the concision treatment")
    query_by_concern = {
        concern: {_message_content(unit, MessageRole.USER) for unit in units if unit.cell.expressed_concern == concern}
        for concern in ExpressedConcernCondition
    }
    if any(len(queries) != 1 for queries in query_by_concern.values()):
        raise ValueError("each concern condition must use one byte-identical query across concision cells")
    if query_by_concern[ExpressedConcernCondition.NEUTRAL] == query_by_concern[ExpressedConcernCondition.CONCERNED]:
        raise ValueError("neutral and concerned conditions must use distinct seed-authored queries")
    follow_up_texts = {unit.follow_up_message.content for unit in units}
    if len(follow_up_texts) != 1 or not next(iter(follow_up_texts)).strip():
        raise ValueError("follow-up must be one non-empty seed-owned question shared across all cells")
    if len({unit.follow_up_sha256 for unit in units}) != 1:
        raise ValueError("follow-up must be byte-identical across all cells")
    for unit in units:
        validate_condition_query(unit)


def group_run_units_by_block(run_units: Iterable[RunUnit]) -> Dict[str, List[RunUnit]]:
    """Group run units by immutable scenario–model block id."""
    grouped: Dict[str, List[RunUnit]] = {}
    for run_unit in run_units:
        grouped.setdefault(run_unit.block_id, []).append(run_unit)
    return grouped
