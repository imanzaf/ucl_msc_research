"""Render one source packet and derive an information-equivalent order variant."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from src.data_models.common import sha256_bytes
from src.data_models.scenarios import EvidenceSpan, SourceItem, SourcePacket
from src.data_models.study import SourceOrderVariant


def render_source_text(fixed_title: str, items: Sequence[SourceItem]) -> str:
    """Render fixed Markdown headers and source-item bodies deterministically."""
    sections = [f"# {fixed_title}"] + [f"## {item.header}\n{item.body}" for item in items]
    return "\n\n".join(sections)


def build_source_packet(
    scenario_id: str,
    source_order: SourceOrderVariant,
    fixed_title: str,
    items: List[SourceItem],
) -> SourcePacket:
    """Build a typed source packet with a byte-level rendering hash."""
    rendered_text = render_source_text(fixed_title=fixed_title, items=items)
    return SourcePacket(
        schema_version="1.0.0",
        scenario_id=scenario_id,
        source_order=source_order,
        fixed_title=fixed_title,
        items=items,
        rendered_text=rendered_text,
        rendered_sha256=sha256_bytes(rendered_text.encode("utf-8")),
    )


def derive_source_orders(
    scenario_id: str,
    fixed_title: str,
    canonical_items: List[SourceItem],
    paired_material_item_ids: List[Tuple[str, str]],
    neutral_item_ids: List[str],
) -> Tuple[SourcePacket, SourcePacket]:
    """Swap material-pair positions and neutral order while preserving item/value multisets."""
    item_ids = [item.source_item_id for item in canonical_items]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("canonical source item ids must be unique")
    material_ids = [item_id for pair in paired_material_item_ids for item_id in pair]
    if len(paired_material_item_ids) != 2 or len(material_ids) != 4 or len(material_ids) != len(set(material_ids)):
        raise ValueError("source-order control requires two disjoint material-item pairs")
    if len(neutral_item_ids) != 2 or len(neutral_item_ids) != len(set(neutral_item_ids)):
        raise ValueError("source-order control requires exactly two distinct neutral items")
    if set(material_ids) & set(neutral_item_ids):
        raise ValueError("material and neutral source-order controls must be disjoint")
    controlled_ids = set(material_ids) | set(neutral_item_ids)
    if not controlled_ids.issubset(item_ids):
        raise ValueError("source-order control references an unknown source item")
    replacement: Dict[str, str] = {}
    for first_id, second_id in paired_material_item_ids:
        replacement[first_id] = second_id
        replacement[second_id] = first_id
    for original_id, reversed_id in zip(neutral_item_ids, reversed(neutral_item_ids)):
        replacement[original_id] = reversed_id
    item_by_id = {item.source_item_id: item for item in canonical_items}
    reordered_items = [item_by_id[replacement.get(item_id, item_id)] for item_id in item_ids]
    if [item.source_item_id for item in reordered_items] == item_ids:
        raise ValueError("source order B must differ from source order A")
    return (
        build_source_packet(scenario_id, SourceOrderVariant.A, fixed_title, canonical_items),
        build_source_packet(scenario_id, SourceOrderVariant.B, fixed_title, reordered_items),
    )


def validate_evidence_span(span: EvidenceSpan, item_by_id: Dict[str, SourceItem]) -> None:
    """Require an evidence locator to reproduce the exact item-body substring."""
    if span.source_item_id not in item_by_id:
        raise ValueError(f"unknown evidence source item: {span.source_item_id}")
    body = item_by_id[span.source_item_id].body
    if span.end_char > len(body) or body[span.start_char : span.end_char] != span.exact_text:
        raise ValueError(f"invalid exact evidence span for {span.source_item_id}")
