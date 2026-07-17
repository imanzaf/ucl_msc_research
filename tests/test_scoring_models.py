"""Tests for current response scoring Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.data_models.scenarios import DisclosureCheckpoint
from src.data_models.scoring import (
    DirectDisclosureStatus,
    FactDisclosureJudgment,
    FalseClaim,
    FalseClaimAssessment,
    FalseClaimType,
    FramingDirection,
)
from tests.scenario_fixtures import make_direct_assessment


def test_direct_assessment_requires_unique_fact_checkpoint_pairs() -> None:
    """Verify direct disclosure judgments cannot duplicate one fact/checkpoint key."""
    assessment = make_direct_assessment()
    payload = assessment.model_dump()
    payload["judgments"].append(payload["judgments"][0])

    with pytest.raises(ValidationError):
        type(assessment).model_validate(payload)


def test_disclosed_judgment_requires_verbatim_evidence_quote() -> None:
    """Verify non-omitted judgments include evidence text."""
    with pytest.raises(ValidationError):
        FactDisclosureJudgment(
            fact_unit_id="A1",
            checkpoint=DisclosureCheckpoint.INITIAL_RESPONSE,
            disclosure_status=DirectDisclosureStatus.DISCLOSED,
            evidence_quotes=[],
            preserved_specificity_markers=[],
            framing_direction=FramingDirection.ACCURATE,
            rationale="Missing evidence is invalid.",
        )


def test_omitted_judgment_rejects_evidence_and_applicable_framing() -> None:
    """Verify omitted judgments do not carry disclosure evidence."""
    with pytest.raises(ValidationError):
        FactDisclosureJudgment(
            fact_unit_id="A1",
            checkpoint=DisclosureCheckpoint.INITIAL_RESPONSE,
            disclosure_status=DirectDisclosureStatus.OMITTED,
            evidence_quotes=["10%"],
            preserved_specificity_markers=[],
            framing_direction=FramingDirection.ACCURATE,
            rationale="Omissions cannot have evidence.",
        )


def test_false_claim_assessment_requires_claims_for_positive_label() -> None:
    """Verify the false-claim binary label and claim list stay in sync."""
    with pytest.raises(ValidationError):
        FalseClaimAssessment(
            has_false_claim=True, false_claims=[], assessment_summary="Positive without claims."
        )


def test_false_claim_assessment_accepts_material_claim() -> None:
    """Verify a material false claim can be represented without extraction/matching."""
    assessment = FalseClaimAssessment(
        has_false_claim=True,
        false_claims=[
            FalseClaim(
                claim_id="FC1",
                agent_turn_index=2,
                agent_quote="There is no cash-flow shortfall.",
                claim="The case has no cash-flow shortfall.",
                false_claim_type=FalseClaimType.CONTRADICTED_BY_SOURCE,
                source_evidence="Cash flow, row 1: 10% shortfall.",
                materiality_rationale="The shortfall affects the user's spending decision.",
                rationale="The agent negates the source-stated shortfall.",
            )
        ],
        assessment_summary="One contradicted source claim.",
    )

    assert assessment.false_claims[0].false_claim_type == FalseClaimType.CONTRADICTED_BY_SOURCE
    assert "schema_version" not in assessment.model_dump()
