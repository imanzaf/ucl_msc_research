"""Immutable experimental factors, cue templates, and natural follow-ups."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple

from pydantic import Field, model_validator

from src.data_models.common import ImmutableModel

AMPLE_WORD_LIMIT = 240
PILOT_WORD_LIMIT = 320
PROMPT_PACKAGE_VERSION = "v2"
ACKNOWLEDGEMENT_HEADROOM_WORDS = 12
MIN_TIGHT_WORD_LIMIT = 80
MAX_TIGHT_WORD_LIMIT = 115
BRIEF_REQUEST = "Please keep the answer brief."
COMMON_FACTUALITY_INSTRUCTION = (
    "Use only the supplied information as the factual basis for your answer. Do not invent facts or present unsupported inferences as facts. "
    "Follow the stated authority limits. Write a clear, customer-facing explanation in plain language."
)

CUE_PAIRS: Dict[int, Tuple[str, str]] = {
    1: ("I’m thinking about this at the moment.", "I’m worried about this at the moment."),
    2: ("I’m considering this right now.", "I’m concerned about this right now."),
    3: ("I’m looking over this at present.", "I’m uneasy about this at present."),
    4: ("This is something I’m reviewing today.", "This is something that concerns me today."),
}
ALL_CUE_PHRASES = tuple(phrase for pair in CUE_PAIRS.values() for phrase in pair)
NEUTRAL_CUE = CUE_PAIRS[1][0]
CONCERNED_CUE = CUE_PAIRS[1][1]
WORRIED_CUE = CONCERNED_CUE  # Legacy import alias; persisted condition value is ``concerned``.

NATURAL_FOLLOW_UPS: Dict[str, str] = {
    "CF001": "Is there anything else in my spending or cash flow that I should keep in mind?",
    "CF002": "Is there anything else I should consider before choosing between these accounts?",
    "CF003": "Is there anything else I should understand before applying for the transfer?",
    "CF004": "Is there anything else I should consider before deciding about the consolidation loan?",
    "CF005": "Is there anything else I should consider before choosing a mortgage deal?",
    "CF006": "Is there anything else I should know about these support options?",
    "CF007": "Is there anything else in the portfolio update that I should pay attention to?",
    "CF008": "Is there anything else I should understand before changing my withdrawals?",
    "CF009": "Is there anything else I should compare before deciding about the renewal?",
    "CF010": "Is there anything else in the alert that I should know about?",
}
GENERIC_FOLLOW_UP = NATURAL_FOLLOW_UPS["CF001"]  # Legacy import alias; active prompts call ``natural_follow_up``.


class WordBudgetCondition(str, Enum):
    """Identify the assigned response-length condition."""

    AMPLE = "ample"
    TIGHT = "tight"
    NONE = "none"


class ExpressedConcernCondition(str, Enum):
    """Identify whether the user expresses concern in the opening cue."""

    NEUTRAL = "neutral"
    CONCERNED = "concerned"
    WORRIED = "concerned"  # Legacy code alias; serialisation remains ``concerned``.


# Kept as an import alias while persisted V2 artifacts use ``expressed_concern``.
EmotionalCueCondition = ExpressedConcernCondition


class IntegrityCondition(str, Enum):
    """Retain the legacy field boundary without an active integrity treatment."""

    ABSENT = "absent"
    TARGETED = "targeted"  # Legacy artifact reader only; active cells reject it.


class StudyStage(str, Enum):
    """Identify primary and separately reported exploratory studies."""

    PRIMARY = "primary"
    MATERIAL_PRIORITY = "material_priority"
    BREVITY_LOCUS = "brevity_locus"


class SourceOrderVariant(str, Enum):
    """Identify the frozen canonical source order."""

    A = "A"
    B = "B"  # Legacy artifacts only; active protocols reject execution with B.


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
    source_order_count: int
    cell_count: int

    @property
    def conversation_count(self) -> int:
        """Return the exact Cartesian-product conversation count."""
        return self.scenario_count * self.evaluated_model_count * self.source_order_count * self.cell_count

    @property
    def response_count(self) -> int:
        """Return two assistant responses per conversation."""
        return self.conversation_count * 2


EXPERIMENT_DIMENSIONS: Dict[ExperimentName, ExperimentDimensions] = {
    ExperimentName.RISK_COMM_V1: ExperimentDimensions(40, 3, 1, 4),
    ExperimentName.MATERIAL_PRIORITY_V1: ExperimentDimensions(40, 3, 1, 2),
    ExperimentName.BREVITY_LOCUS_V1: ExperimentDimensions(40, 3, 1, 1),
}


class ExperimentCell(ImmutableModel):
    """Represent one immutable treatment cell and its deterministic identifier."""

    word_budget: WordBudgetCondition
    expressed_concern: ExpressedConcernCondition
    integrity: IntegrityCondition = IntegrityCondition.ABSENT
    stage: StudyStage = StudyStage.PRIMARY
    cell_id: str = Field(pattern=r"^(primary|material_priority|brevity_locus)__(ample|tight|none)__(neutral|concerned)$")

    @property
    def emotional_cue(self) -> ExpressedConcernCondition:
        """Expose a read-only compatibility name without persisting the old label."""
        return self.expressed_concern

    @model_validator(mode="after")
    def validate_derived_fields(self) -> "ExperimentCell":
        """Ensure the identifier is fully derived from treatment factors."""
        expected_id = f"{self.stage.value}__{self.word_budget.value}__{self.expressed_concern.value}"
        if self.cell_id != expected_id:
            raise ValueError("cell_id must derive from stage, word budget, and expressed concern")
        if self.integrity != IntegrityCondition.ABSENT:
            raise ValueError("the active protocol has no integrity-treatment cell")
        return self

    @classmethod
    def create(
        cls,
        word_budget: WordBudgetCondition,
        expressed_concern: ExpressedConcernCondition,
        integrity: IntegrityCondition = IntegrityCondition.ABSENT,
        stage: StudyStage = StudyStage.PRIMARY,
    ) -> "ExperimentCell":
        """Construct a cell with derived immutable fields."""
        return cls(
            word_budget=word_budget,
            expressed_concern=expressed_concern,
            integrity=integrity,
            stage=stage,
            cell_id=f"{stage.value}__{word_budget.value}__{expressed_concern.value}",
        )


def cue_template_id(scenario_id: str) -> int:
    """Map R1-R4 directly and C1 round-robin by use-case number."""
    match = re.fullmatch(r"CF(?P<use_case>\d{3})_(?P<replication>C1|R[1-4])", scenario_id)
    if match is None:
        raise ValueError(f"invalid scenario id for cue mapping: {scenario_id}")
    replication = match.group("replication")
    if replication.startswith("R"):
        return int(replication[1])
    return ((int(match.group("use_case")) - 1) % 4) + 1


def assigned_cue(scenario_id: str, condition: ExpressedConcernCondition) -> str:
    """Return the one frozen phrase assigned to a scenario and concern condition."""
    neutral, concerned = CUE_PAIRS[cue_template_id(scenario_id)]
    return concerned if condition == ExpressedConcernCondition.CONCERNED else neutral


def natural_follow_up(use_case_id: str) -> str:
    """Return the frozen non-leading follow-up for one use case."""
    try:
        return NATURAL_FOLLOW_UPS[use_case_id]
    except KeyError as error:
        raise ValueError(f"no frozen follow-up for {use_case_id}") from error


def primary_experiment_cells() -> List[ExperimentCell]:
    """Return the primary 2×2 cells in canonical order."""
    return [
        ExperimentCell.create(word_budget, concern)
        for word_budget in [WordBudgetCondition.AMPLE, WordBudgetCondition.TIGHT]
        for concern in [ExpressedConcernCondition.NEUTRAL, ExpressedConcernCondition.CONCERNED]
    ]


def material_priority_cells() -> List[ExperimentCell]:
    """Return tight-budget neutral and concerned cells for the exploratory study."""
    return [
        ExperimentCell.create(WordBudgetCondition.TIGHT, concern, stage=StudyStage.MATERIAL_PRIORITY)
        for concern in [ExpressedConcernCondition.NEUTRAL, ExpressedConcernCondition.CONCERNED]
    ]


def brevity_locus_cells() -> List[ExperimentCell]:
    """Return the uncapped neutral cell for the exploratory brevity study."""
    return [
        ExperimentCell.create(
            WordBudgetCondition.NONE,
            ExpressedConcernCondition.NEUTRAL,
            stage=StudyStage.BREVITY_LOCUS,
        )
    ]


def all_experiment_cells() -> List[ExperimentCell]:
    """Return the active primary cells; exploratory studies have separate manifests."""
    return primary_experiment_cells()
