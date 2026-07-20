"""Blinded conversation-annotation and delayed-repeat records."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field, field_validator, model_validator

from src.data_models.common import VersionedImmutableModel, validate_sha256
from src.data_models.scenario_review import REPEAT_WASHOUT_DAYS, ReviewPass
from src.data_models.scoring import ClaimAssessmentJudgment, FactAssessmentJudgment, ResponseCommunicationJudgment


class ConversationAnnotation(VersionedImmutableModel):
    """Store one blinded initial, delayed-repeat, or resolution annotation."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    annotation_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    anonymised_item_id: str = Field(min_length=1)
    blind_conversation_id: str = Field(min_length=1)
    annotation_pass: ReviewPass
    fact_judgments: List[FactAssessmentJudgment] = Field(min_length=12, max_length=12)
    response_judgments: List[ResponseCommunicationJudgment] = Field(min_length=2, max_length=2)
    claim_judgments: List[ClaimAssessmentJudgment]
    scoring_input_sha256: str
    rubric_sha256: str
    researcher_id: str = Field(min_length=1)
    submitted_at: datetime
    initial_annotation_id: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]+$")
    repeat_annotation_id: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]+$")
    resolution_reason: Optional[str] = Field(default=None, min_length=1)

    @field_validator("scoring_input_sha256", "rubric_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate source-input and frozen-rubric hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_pass_linkage(self) -> "ConversationAnnotation":
        """Require prior-record links for repeat and resolution annotations."""
        if self.annotation_pass == ReviewPass.INITIAL and (self.initial_annotation_id is not None or self.repeat_annotation_id is not None):
            raise ValueError("initial annotations cannot link to another annotation")
        if self.annotation_pass == ReviewPass.REPEAT and (self.initial_annotation_id is None or self.repeat_annotation_id is not None):
            raise ValueError("repeat annotations require only the linked initial annotation id")
        if self.annotation_pass == ReviewPass.RESOLUTION and (
            self.initial_annotation_id is None or self.repeat_annotation_id is None or self.resolution_reason is None
        ):
            raise ValueError("resolution annotations require linked initial/repeat ids and a reason")
        if self.annotation_pass != ReviewPass.RESOLUTION and self.resolution_reason is not None:
            raise ValueError("only resolution annotations may include a resolution reason")
        return self


def repeat_washout_elapsed(initial_timestamp: datetime, current_timestamp: datetime) -> bool:
    """Return whether the minimum fourteen-day repeat washout has elapsed."""
    if initial_timestamp.tzinfo is None or current_timestamp.tzinfo is None:
        raise ValueError("washout timestamps must be timezone-aware")
    elapsed_seconds = (current_timestamp - initial_timestamp).total_seconds()
    return elapsed_seconds >= REPEAT_WASHOUT_DAYS * 24 * 60 * 60
