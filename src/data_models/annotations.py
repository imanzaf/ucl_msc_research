"""Blinded one-pass conversation annotation records."""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import Field, field_validator, model_validator

from src.data_models.common import VersionedImmutableModel, validate_sha256
from src.data_models.scenario_review import ReviewPass
from src.data_models.scoring import ClaimAssessmentJudgment, FactAssessmentJudgment, ResponseCommunicationJudgment


class ConversationAnnotation(VersionedImmutableModel):
    """Store exactly one blinded annotation for a sampled conversation."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    annotation_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    anonymised_item_id: str = Field(min_length=1)
    blind_conversation_id: str = Field(min_length=1)
    annotation_pass: ReviewPass
    fact_judgments: List[FactAssessmentJudgment] = Field(min_length=8, max_length=8)
    response_judgments: List[ResponseCommunicationJudgment] = Field(min_length=2, max_length=2)
    claim_judgments: List[ClaimAssessmentJudgment]
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
        """Reject repeats, resolutions, and outcome-enriched linkage fields."""
        if self.annotation_pass != ReviewPass.INITIAL:
            raise ValueError("the active protocol permits exactly one annotation per conversation")
        return self
