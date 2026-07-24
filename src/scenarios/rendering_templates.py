"""Deterministic text-native source templates independent of scenario models."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Sequence, Tuple


class SourceFormat(str, Enum):
    """Identify one active deterministic V0.9.0 evidence-packet presentation."""

    CURRENT_ACCOUNT_CONFIGURATION_COMPARISON = "current_account_configuration_comparison"
    LATER_LIFE_MORTGAGE_COMPARISON = "later_life_mortgage_comparison"
    TRANSFER_OFFER_COMPARISON = "transfer_offer_comparison"
    CONSOLIDATION_LOAN_TERM_COMPARISON = "consolidation_loan_term_comparison"
    MORTGAGE_RETENTION_COMPARISON = "mortgage_retention_comparison"
    DIFFICULTY_SUPPORT_COMPARISON = "difficulty_support_comparison"
    FUND_SWITCH_COMPARISON = "fund_switch_comparison"
    RETIREMENT_INCOME_COMPARISON = "retirement_income_comparison"
    CLAIM_SETTLEMENT_COMPARISON = "claim_settlement_comparison"
    INTERNATIONAL_PAYMENT_COMPARISON = "international_payment_comparison"


class SourceLayout(str, Enum):
    """Identify one deterministic text layout shared by related source formats."""

    TABLE = "table"
    STATEMENT = "statement"
    ILLUSTRATION = "illustration"
    SUMMARY = "summary"


SOURCE_LAYOUT_BY_FORMAT: Dict[SourceFormat, SourceLayout] = {
    SourceFormat.CURRENT_ACCOUNT_CONFIGURATION_COMPARISON: SourceLayout.STATEMENT,
    SourceFormat.LATER_LIFE_MORTGAGE_COMPARISON: SourceLayout.ILLUSTRATION,
    SourceFormat.TRANSFER_OFFER_COMPARISON: SourceLayout.TABLE,
    SourceFormat.CONSOLIDATION_LOAN_TERM_COMPARISON: SourceLayout.ILLUSTRATION,
    SourceFormat.MORTGAGE_RETENTION_COMPARISON: SourceLayout.TABLE,
    SourceFormat.DIFFICULTY_SUPPORT_COMPARISON: SourceLayout.SUMMARY,
    SourceFormat.FUND_SWITCH_COMPARISON: SourceLayout.TABLE,
    SourceFormat.RETIREMENT_INCOME_COMPARISON: SourceLayout.ILLUSTRATION,
    SourceFormat.CLAIM_SETTLEMENT_COMPARISON: SourceLayout.TABLE,
    SourceFormat.INTERNATIONAL_PAYMENT_COMPARISON: SourceLayout.TABLE,
}

SOURCE_FORMAT_BY_USE_CASE: Dict[str, SourceFormat] = {
    "CF001": SourceFormat.CURRENT_ACCOUNT_CONFIGURATION_COMPARISON,
    "CF002": SourceFormat.LATER_LIFE_MORTGAGE_COMPARISON,
    "CF003": SourceFormat.TRANSFER_OFFER_COMPARISON,
    "CF004": SourceFormat.CONSOLIDATION_LOAN_TERM_COMPARISON,
    "CF005": SourceFormat.MORTGAGE_RETENTION_COMPARISON,
    "CF006": SourceFormat.DIFFICULTY_SUPPORT_COMPARISON,
    "CF007": SourceFormat.FUND_SWITCH_COMPARISON,
    "CF008": SourceFormat.RETIREMENT_INCOME_COMPARISON,
    "CF009": SourceFormat.CLAIM_SETTLEMENT_COMPARISON,
    "CF010": SourceFormat.INTERNATIONAL_PAYMENT_COMPARISON,
}


def render_text_native_source(source_format: SourceFormat, title: str, items: Sequence[Tuple[str, str]]) -> str:
    """Render one frozen domain-native source packet from ordered header/body pairs."""
    layout = SOURCE_LAYOUT_BY_FORMAT[source_format]
    if layout == SourceLayout.TABLE:
        rows = ["| Item | Source details |", "|---|---|"]
        rows.extend(f"| {header} | {body.replace('|', '/')} |" for header, body in items)
        return f"{title}\n\n" + "\n".join(rows)
    if layout == SourceLayout.STATEMENT:
        lines = [title, "=" * len(title)]
        lines.extend(f"\n{header.upper()}\n{body}" for header, body in items)
        return "\n".join(lines)
    if layout == SourceLayout.ILLUSTRATION:
        lines = [title, "Figures and assumptions:"]
        lines.extend(f"[{index}] {header}\n    {body}" for index, (header, body) in enumerate(items, start=1))
        return "\n".join(lines)
    if layout == SourceLayout.SUMMARY:
        lines = [title, "Available support-option summary:"]
        lines.extend(f"OPTION DETAIL — {header}\n{body}" for header, body in items)
        return "\n\n".join(lines)
    raise AssertionError(f"unhandled deterministic source layout: {layout}")
