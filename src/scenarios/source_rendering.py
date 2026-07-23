"""Render canonical sources in deterministic domain-native text formats."""

from __future__ import annotations

from typing import Dict, List, Sequence

from src.data_models.common import sha256_bytes
from src.data_models.scenarios import EvidenceSpan, SourceItem, SourcePacket
from src.scenarios.rendering_templates import SOURCE_FORMAT_BY_USE_CASE, SourceFormat, render_text_native_source


def render_source_text(source_format: SourceFormat, fixed_title: str, items: Sequence[SourceItem]) -> str:
    """Render exact ordered facts through the frozen domain-native template."""
    return render_text_native_source(source_format, fixed_title, [(item.header, item.body) for item in items])


def build_source_packet(
    scenario_id: str,
    fixed_title: str,
    items: List[SourceItem],
    source_format: SourceFormat | None = None,
) -> SourcePacket:
    """Build a typed source packet with a byte-level rendering hash."""
    selected_format = source_format or SOURCE_FORMAT_BY_USE_CASE[scenario_id.split("_")[0]]
    rendered_text = render_source_text(selected_format, fixed_title=fixed_title, items=items)
    return SourcePacket(
        schema_version="3.0.0",
        scenario_id=scenario_id,
        fixed_title=fixed_title,
        source_format=selected_format,
        items=items,
        rendered_text=rendered_text,
        rendered_sha256=sha256_bytes(rendered_text.encode("utf-8")),
    )


def validate_evidence_span(span: EvidenceSpan, item_by_id: Dict[str, SourceItem]) -> None:
    """Require an evidence locator to reproduce the exact item-body substring."""
    if span.source_item_id not in item_by_id:
        raise ValueError(f"unknown evidence source item: {span.source_item_id}")
    body = item_by_id[span.source_item_id].body
    if span.end_char > len(body) or body[span.start_char : span.end_char] != span.exact_text:
        raise ValueError(f"invalid exact evidence span for {span.source_item_id}")
