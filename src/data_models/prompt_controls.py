"""Byte-level factor-isolation checks for compiled experiment prompts."""

from __future__ import annotations

from typing import Dict, Iterable, List

from src.data_models.experiments import RunUnit
from src.data_models.study import ALL_CUE_PHRASES, CONCISION_INSTRUCTION, assigned_cue


def _canonical_initial_messages(run_unit: RunUnit) -> str:
    """Replace only the assigned cue and optional concision instruction with placeholders."""
    rendered = "\n\n".join(f"{message.role.value}:{message.content}" for message in run_unit.initial_request_messages)
    for phrase in ALL_CUE_PHRASES:
        rendered = rendered.replace(phrase, "<CUE>")
    rendered = rendered.replace(f"\n\n{CONCISION_INSTRUCTION}", "")
    return rendered


def validate_assigned_cue(run_unit: RunUnit) -> None:
    """Require exactly the assigned phrase and reject all seven alternatives."""
    initial_text = "\n".join(message.content for message in run_unit.initial_request_messages)
    expected = assigned_cue(run_unit.scenario_id, run_unit.cell.expressed_concern)
    observed = [phrase for phrase in ALL_CUE_PHRASES if phrase in initial_text]
    if observed != [expected] or initial_text.count(expected) != 1:
        raise ValueError("initial request must contain exactly the assigned cue phrase and no alternative")
    if any(phrase in run_unit.follow_up_message.content for phrase in ALL_CUE_PHRASES):
        raise ValueError("natural follow-up must be cue-free")


def validate_prompt_factor_isolation(run_units: Iterable[RunUnit]) -> None:
    """Require a complete primary 2×2 block to vary only concision guidance and concern cue."""
    units = list(run_units)
    if len(units) != 4:
        raise ValueError("prompt-isolation validation requires exactly four run units")
    expected_pairs = {(condition, cue) for condition in {"baseline", "concise"} for cue in {"neutral", "concerned"}}
    observed_pairs = {(unit.cell.concision.value, unit.cell.expressed_concern.value) for unit in units}
    if observed_pairs != expected_pairs:
        raise ValueError("block must contain every concision-instruction and expressed-concern combination")
    canonical_messages = {_canonical_initial_messages(unit) for unit in units}
    if len(canonical_messages) != 1:
        raise ValueError("compiled prompts differ outside the declared primary treatment factors")
    follow_up_texts = {unit.follow_up_message.content for unit in units}
    if len(follow_up_texts) != 1 or not next(iter(follow_up_texts)).strip():
        raise ValueError("follow-up must be one non-empty seed-owned question shared across all cells")
    if len({unit.follow_up_sha256 for unit in units}) != 1:
        raise ValueError("follow-up must be byte-identical across all cells")
    for unit in units:
        validate_assigned_cue(unit)


def group_run_units_by_block(run_units: Iterable[RunUnit]) -> Dict[str, List[RunUnit]]:
    """Group run units by immutable scenario–model block id."""
    grouped: Dict[str, List[RunUnit]] = {}
    for run_unit in run_units:
        grouped.setdefault(run_unit.block_id, []).append(run_unit)
    return grouped
