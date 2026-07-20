"""Byte-level factor-isolation checks for compiled experiment prompts."""

from __future__ import annotations

from typing import Dict, Iterable, List

from src.data_models.experiments import RunUnit
from src.data_models.study import INTEGRITY_INSTRUCTION, NEUTRAL_CUE, WORRIED_CUE


def _canonical_initial_messages(run_unit: RunUnit) -> str:
    """Replace only declared treatment text with factor placeholders."""
    rendered = "\n\n".join(f"{message.role.value}:{message.content}" for message in run_unit.initial_request_messages)
    rendered = rendered.replace(NEUTRAL_CUE, "<CUE>").replace(WORRIED_CUE, "<CUE>")
    rendered = rendered.replace(f"\n\n{INTEGRITY_INSTRUCTION}", "")
    rendered = rendered.replace("Use no more than 240 words.", "Use no more than <WORD_LIMIT> words.")
    rendered = rendered.replace(f"Use no more than {run_unit.assigned_word_limit} words.", "Use no more than <WORD_LIMIT> words.")
    return rendered


def validate_prompt_factor_isolation(run_units: Iterable[RunUnit]) -> None:
    """Require one complete four-cell stage block to vary only declared factors."""
    units = list(run_units)
    if len(units) != 4:
        raise ValueError("prompt-isolation validation requires exactly four run units")
    if len({unit.cell.cell_id for unit in units}) != len(units):
        raise ValueError("block must contain unique experiment cells")
    expected_budget_cue_pairs = {(budget, cue) for budget in {"ample", "tight"} for cue in {"neutral", "worried"}}
    observed_budget_cue_pairs = {(unit.cell.word_budget.value, unit.cell.emotional_cue.value) for unit in units}
    if observed_budget_cue_pairs != expected_budget_cue_pairs:
        raise ValueError("block must contain every word-budget and emotional-cue combination")
    if len({unit.cell.integrity for unit in units}) != 1:
        raise ValueError("a four-cell block must use one integrity condition")
    canonical_messages = {_canonical_initial_messages(unit) for unit in units}
    if len(canonical_messages) != 1:
        raise ValueError("compiled prompts differ outside the three declared treatment factors")
    if len({unit.follow_up_message.content for unit in units}) != 1 or len({unit.follow_up_sha256 for unit in units}) != 1:
        raise ValueError("follow-up must be byte-identical across all cells")
    for unit in units:
        initial_text = "\n".join(message.content for message in unit.initial_request_messages)
        cue = WORRIED_CUE if unit.cell.emotional_cue.value == "worried" else NEUTRAL_CUE
        other_cue = NEUTRAL_CUE if cue == WORRIED_CUE else WORRIED_CUE
        if initial_text.count(cue) != 1 or other_cue in initial_text:
            raise ValueError("assigned cue must occur exactly once and the alternate cue must be absent")
        if NEUTRAL_CUE in unit.follow_up_message.content or WORRIED_CUE in unit.follow_up_message.content:
            raise ValueError("follow-up must be cue-free")


def group_run_units_by_block(run_units: Iterable[RunUnit]) -> Dict[str, List[RunUnit]]:
    """Group run units by immutable scenario–model–source-order block id."""
    grouped: Dict[str, List[RunUnit]] = {}
    for run_unit in run_units:
        grouped.setdefault(run_unit.block_id, []).append(run_unit)
    return grouped
