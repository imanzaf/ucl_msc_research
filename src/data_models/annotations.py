"""Blinded one-pass conversation annotation records."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from pydantic import Field, field_validator, model_validator

from src.data_models.common import VersionedImmutableModel, validate_sha256
from src.data_models.scenario_review import ReviewPass
from src.data_models.scoring import FactContentJudgment, FalseClaim, PresentationFinding, ScoredResponse


class ConversationAnnotation(VersionedImmutableModel):
    """Store exactly one blinded annotation for a sampled conversation."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    annotation_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    anonymised_item_id: str = Field(min_length=1)
    blind_conversation_id: str = Field(min_length=1)
    annotation_pass: ReviewPass
    content_judgments: Dict[ScoredResponse, List[FactContentJudgment]]
    presentation_findings: Dict[ScoredResponse, List[PresentationFinding]]
    false_claims: Dict[ScoredResponse, List[FalseClaim]]
    scoring_input_sha256: str
    rubric_sha256: str
    researcher_id: str = Field(min_length=1)
    submitted_at: datetime

    @field_validator("scoring_input_sha256", "rubric_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate source-input and frozen-rubric hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_pass_linkage(self) -> "ConversationAnnotation":
        """Require one complete blinded annotation for both isolated responses."""
        if self.annotation_pass != ReviewPass.INITIAL:
            raise ValueError("the active protocol permits exactly one annotation per conversation")
        if (
            set(self.content_judgments) != set(ScoredResponse)
            or set(self.presentation_findings) != set(ScoredResponse)
            or set(self.false_claims) != set(ScoredResponse)
        ):
            raise ValueError("conversation annotation requires all three contracts for both responses")
        if any(len(judgments) != 4 for judgments in self.content_judgments.values()):
            raise ValueError("each response annotation requires four content judgments")
        return self
