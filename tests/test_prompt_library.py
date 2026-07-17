"""Tests for grouped prompt-library templates."""

from __future__ import annotations

from src.prompts.scoring.direct_fact_disclosure_assessment import (
    DIRECT_FACT_DISCLOSURE_ASSESSMENT_PROMPT_VERSION,
    DIRECT_FACT_DISCLOSURE_ASSESSMENT_TEMPLATE,
)
from src.prompts.scoring.false_claim_assessment import (
    FALSE_CLAIM_ASSESSMENT_PROMPT_VERSION,
    FALSE_CLAIM_ASSESSMENT_TEMPLATE,
)


def test_direct_fact_disclosure_prompt_assesses_declared_pairs() -> None:
    """Verify direct disclosure prompts assess every declared fact/checkpoint pair."""
    assert (
        DIRECT_FACT_DISCLOSURE_ASSESSMENT_PROMPT_VERSION == "direct_fact_disclosure_assessment_v1"
    )
    assert "Return exactly one judgment for every fact/checkpoint pair" in (
        DIRECT_FACT_DISCLOSURE_ASSESSMENT_TEMPLATE
    )
    assert "Do not add unknown facts or checkpoints" in DIRECT_FACT_DISCLOSURE_ASSESSMENT_TEMPLATE


def test_false_claim_prompt_uses_single_contextual_judge() -> None:
    """Verify false-claim prompts use the full context without extraction or matching."""
    assert FALSE_CLAIM_ASSESSMENT_PROMPT_VERSION == "false_claim_assessment_v1"
    assert "Reference text shown to the agent" in FALSE_CLAIM_ASSESSMENT_TEMPLATE
    assert "Hidden fact units" in FALSE_CLAIM_ASSESSMENT_TEMPLATE
    assert "User-facing outcome context" in FALSE_CLAIM_ASSESSMENT_TEMPLATE
    assert "Conversation transcript" in FALSE_CLAIM_ASSESSMENT_TEMPLATE
