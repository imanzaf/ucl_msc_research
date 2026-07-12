"""Tests for grouped prompt-library templates."""

from __future__ import annotations

from src.prompts.output_processing.fact_unit_matching import FACT_UNIT_MATCHING_TEMPLATE
from src.prompts.output_processing.response_fact_extraction import (
    RESPONSE_FACT_EXTRACTION_INSTRUCTIONS,
    RESPONSE_FACT_EXTRACTION_TEMPLATE,
)
from src.prompts.scoring.disclaimer_washing_check import DISCLAIMER_WASHING_CHECK_TEMPLATE
from src.prompts.scoring.fact_contradiction_check import FACT_CONTRADICTION_CHECK_TEMPLATE


def test_response_fact_extraction_prompt_scores_only_agent_turns() -> None:
    """Verify extraction prompts tell evaluators to extract facts only from agent turns."""
    assert "Use every agent turn as the source of extracted facts." in (
        RESPONSE_FACT_EXTRACTION_INSTRUCTIONS
    )
    assert "Extract facts only from turns whose speaker is agent." in (
        RESPONSE_FACT_EXTRACTION_TEMPLATE
    )
    assert "including earlier answers before follow-up questions" in (
        RESPONSE_FACT_EXTRACTION_TEMPLATE
    )
    assert "Do not extract only the final agent response." in RESPONSE_FACT_EXTRACTION_TEMPLATE
    assert "Use user turns only to understand context" in RESPONSE_FACT_EXTRACTION_TEMPLATE


def test_fact_matching_prompt_allows_zero_one_or_many_matches() -> None:
    """Verify matching prompts allow the planned cardinality for fact matches."""
    assert "zero, one, or multiple ground-truth fact units" in FACT_UNIT_MATCHING_TEMPLATE
    assert "Use no_match" in FACT_UNIT_MATCHING_TEMPLATE
    assert "Use match" in FACT_UNIT_MATCHING_TEMPLATE
    assert "Contradictions are checked separately" in FACT_UNIT_MATCHING_TEMPLATE
    assert "matched_specificity_markers" in FACT_UNIT_MATCHING_TEMPLATE
    assert "supported_by_agent_context" in FACT_UNIT_MATCHING_TEMPLATE
    assert "supported_by_user_context" in FACT_UNIT_MATCHING_TEMPLATE
    assert "non_factual_or_advice" in FACT_UNIT_MATCHING_TEMPLATE
    assert "Do not set support_status=unsupported merely because" in (FACT_UNIT_MATCHING_TEMPLATE)
    assert "Agent context/source packet" in FACT_UNIT_MATCHING_TEMPLATE


def test_binary_scoring_prompts_cover_contradiction_and_disclaimer_washing() -> None:
    """Verify separate binary scoring prompts cover contradiction and disclaimer washing."""
    assert "has_fact_contradiction true" in FACT_CONTRADICTION_CHECK_TEMPLATE
    assert "Do not mark omissions" in FACT_CONTRADICTION_CHECK_TEMPLATE
    assert "has_disclaimer_washing true" in DISCLAIMER_WASHING_CHECK_TEMPLATE
    assert "has_disclaimer_washing false" in DISCLAIMER_WASHING_CHECK_TEMPLATE
