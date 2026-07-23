"""Deterministic text-native source templates independent of scenario models."""

from __future__ import annotations

from typing import Sequence, Tuple


def render_text_native_source(source_format: str, title: str, items: Sequence[Tuple[str, str]]) -> str:
    """Render one frozen domain-native source packet from ordered header/body pairs."""
    if source_format in {"savings_comparison_table", "insurance_comparison_table"}:
        rows = ["| Item | Source details |", "|---|---|"]
        rows.extend(f"| {header} | {body.replace('|', '/')} |" for header, body in items)
        return f"{title}\n\n" + "\n".join(rows)
    if source_format in {"cash_flow_statement", "portfolio_statement"}:
        lines = [title, "=" * len(title)]
        lines.extend(f"\n{header.upper()}\n{body}" for header, body in items)
        return "\n".join(lines)
    if source_format in {"card_statement_and_offer", "security_timeline"}:
        lines = [title, "Timeline / statement entries:"]
        lines.extend(f"{index:02d}. {header}: {body}" for index, (header, body) in enumerate(items, start=1))
        return "\n".join(lines)
    if source_format in {"loan_illustration", "mortgage_illustration", "pension_illustration"}:
        lines = [title, "Illustration (figures are scenario-specific):"]
        lines.extend(f"[{index}] {header}\n    {body}" for index, (header, body) in enumerate(items, start=1))
        return "\n".join(lines)
    if source_format == "support_option_summary":
        lines = [title, "Available support-option summary:"]
        lines.extend(f"OPTION DETAIL — {header}\n{body}" for header, body in items)
        return "\n\n".join(lines)
    if source_format == "legacy_markdown":
        return "\n\n".join([f"# {title}", *[f"## {header}\n{body}" for header, body in items]])
    raise ValueError(f"unknown deterministic source format: {source_format}")
