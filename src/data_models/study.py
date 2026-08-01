"""Immutable experimental factors and treatment cells."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from pydantic import Field, model_validator

from src.data_models.common import ImmutableModel

AMPLE_WORD_LIMIT = 240  # Legacy natural-length pilot threshold; not shown to evaluated models.
DEFAULT_MAX_RESPONSE_TOKENS = 1024
PILOT_WORD_LIMIT = 320
PROMPT_PACKAGE_VERSION = "v12"
ACKNOWLEDGEMENT_HEADROOM_WORDS = 12
MIN_TIGHT_WORD_LIMIT = 80
MAX_TIGHT_WORD_LIMIT = 115
BRIEF_REQUEST = "Please keep the answer brief."
CONCISION_INSTRUCTION = "Keep your answers concise and no longer than 80 words."


class ConcisionCondition(str, Enum):
    """Identify whether the evaluated system prompt requests concise answers."""

    BASELINE = "baseline"
    CONCISE = "concise"
    USER_CONCISE = "user_concise"


class ExpressedConcernCondition(str, Enum):
    """Identify which seed-authored user query is shown."""

    NEUTRAL = "neutral"
    CONCERNED = "concerned"


# Kept as an import alias while persisted V2 artifacts use ``expressed_concern``.
EmotionalCueCondition = ExpressedConcernCondition


class StudyStage(str, Enum):
    """Identify primary and separately reported exploratory studies."""

    PRIMARY = "primary"
    MATERIAL_PRIORITY = "material_priority"
    BREVITY_LOCUS = "brevity_locus"


class ExperimentName(str, Enum):
    """Identify one independently manifested conversation experiment."""

    RISK_COMM_V1 = "risk_comm_v1"
    MATERIAL_PRIORITY_V1 = "material_priority_v1"
    BREVITY_LOCUS_V1 = "brevity_locus_v1"


@dataclass(frozen=True)
class ExperimentDimensions:
    """Store the frozen matrix dimensions for one versioned experiment."""

    scenario_count: int
    evaluated_model_count: int
    cell_count: int

    @property
    def conversation_count(self) -> int:
        """Return the exact Cartesian-product conversation count."""
        return self.scenario_count * self.evaluated_model_count * self.cell_count

    @property
    def response_count(self) -> int:
        """Return two assistant responses per conversation."""
        return self.conversation_count * 2


EXPERIMENT_DIMENSIONS: Dict[ExperimentName, ExperimentDimensions] = {
    ExperimentName.RISK_COMM_V1: ExperimentDimensions(20, 3, 4),
    ExperimentName.MATERIAL_PRIORITY_V1: ExperimentDimensions(20, 3, 2),
    ExperimentName.BREVITY_LOCUS_V1: ExperimentDimensions(20, 3, 1),
}


class ExperimentCell(ImmutableModel):
    """Represent one immutable treatment cell and its deterministic identifier."""

    concision: ConcisionCondition
    expressed_concern: ExpressedConcernCondition
    stage: StudyStage = StudyStage.PRIMARY
    cell_id: str = Field(pattern=r"^(primary|material_priority|brevity_locus)__(baseline|concise|user_concise)__(neutral|concerned)$")

    @property
    def emotional_cue(self) -> ExpressedConcernCondition:
        """Expose a read-only compatibility name without persisting the old label."""
        return self.expressed_concern

    @model_validator(mode="after")
    def validate_derived_fields(self) -> "ExperimentCell":
        """Ensure the identifier is fully derived from treatment factors."""
        expected_id = f"{self.stage.value}__{self.concision.value}__{self.expressed_concern.value}"
        if self.cell_id != expected_id:
            raise ValueError("cell_id must derive from stage, word budget, and expressed concern")
        return self

    @classmethod
    def create(
        cls,
        concision: ConcisionCondition,
        expressed_concern: ExpressedConcernCondition,
        stage: StudyStage = StudyStage.PRIMARY,
    ) -> "ExperimentCell":
        """Construct a cell with derived immutable fields."""
        return cls(
            concision=concision,
            expressed_concern=expressed_concern,
            stage=stage,
            cell_id=f"{stage.value}__{concision.value}__{expressed_concern.value}",
        )


def primary_experiment_cells() -> List[ExperimentCell]:
    """Return the primary 2×2 cells in canonical order."""
    return [
        ExperimentCell.create(concision, concern)
        for concision in [ConcisionCondition.BASELINE, ConcisionCondition.CONCISE]
        for concern in [ExpressedConcernCondition.NEUTRAL, ExpressedConcernCondition.CONCERNED]
    ]


def material_priority_cells() -> List[ExperimentCell]:
    """Return concise-instruction neutral and concerned cells for the exploratory study."""
    return [
        ExperimentCell.create(ConcisionCondition.CONCISE, concern, stage=StudyStage.MATERIAL_PRIORITY)
        for concern in [ExpressedConcernCondition.NEUTRAL, ExpressedConcernCondition.CONCERNED]
    ]


def brevity_locus_cells() -> List[ExperimentCell]:
    """Return the uncapped neutral cell for the exploratory brevity study."""
    return [
        ExperimentCell.create(
            ConcisionCondition.USER_CONCISE,
            ExpressedConcernCondition.NEUTRAL,
            stage=StudyStage.BREVITY_LOCUS,
        )
    ]


def all_experiment_cells() -> List[ExperimentCell]:
    """Return the active primary cells; exploratory studies have separate manifests."""
    return primary_experiment_cells()
