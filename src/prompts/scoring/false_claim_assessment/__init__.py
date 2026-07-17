"""Expose the false-claim assessment prompt."""

from src.prompts.scoring.false_claim_assessment.template import (
    FALSE_CLAIM_ASSESSMENT_INSTRUCTIONS,
    FALSE_CLAIM_ASSESSMENT_PROMPT_VERSION,
    FALSE_CLAIM_ASSESSMENT_TEMPLATE,
)

__all__ = [
    "FALSE_CLAIM_ASSESSMENT_INSTRUCTIONS",
    "FALSE_CLAIM_ASSESSMENT_PROMPT_VERSION",
    "FALSE_CLAIM_ASSESSMENT_TEMPLATE",
]
