"""Paired descriptive contrasts for the commercial-interest instruction experiment."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple, cast

from pydantic import Field, model_validator

from src.common import ImmutableModel
from src.models.enums import Affect, CommercialInterestInstruction, CommercialInterestTask, ExactFactBudget, OwnershipRole
from src.models.experiments import CommercialInterestCell
from src.models.scoring import ResponseOutcomesRecord, SelectionOutcomes

CommercialSummaryKey = Tuple[CommercialInterestTask, str, Optional[ExactFactBudget], Optional[OwnershipRole], Optional[Affect]]


class CommercialInterestObservation(ImmutableModel):
    """Store one scored outcome at a complete commercial-interest coordinate."""

    scenario_id: str
    use_case_id: str
    model_slug: str
    affect: Affect
    instruction: CommercialInterestInstruction
    task: CommercialInterestTask
    outcome_name: str = Field(min_length=1)
    value: float
    exact_fact_budget: Optional[ExactFactBudget] = None
    ownership_role: Optional[OwnershipRole] = None
    rendering: Optional[int] = Field(default=None, ge=1, le=2)

    @model_validator(mode="after")
    def validate_task_coordinates(self) -> "CommercialInterestObservation":
        """Keep budget and ownership coordinates attached only to their tasks."""
        if self.task == CommercialInterestTask.EXACT_BUDGET:
            if self.exact_fact_budget not in {ExactFactBudget.FACTS_2, ExactFactBudget.FACTS_4}:
                raise ValueError("commercial exact-budget observations require k=2 or k=4")
            if self.ownership_role is not None or self.rendering is not None:
                raise ValueError("commercial exact-budget observations cannot carry ownership coordinates")
            return self
        if self.task == CommercialInterestTask.OWNERSHIP_FLIP:
            if self.ownership_role not in {OwnershipRole.EMPLOYER_OWNS_A, OwnershipRole.EMPLOYER_OWNS_B} or self.rendering is None:
                raise ValueError("commercial ownership observations require employer A/B and a rendering")
            if self.exact_fact_budget is not None:
                raise ValueError("commercial ownership observations cannot carry an exact budget")
            return self
        if self.exact_fact_budget is not None or self.ownership_role is not None or self.rendering is not None:
            raise ValueError("commercial standard and single-fact observations have no extra coordinates")
        return self


class CommercialInterestContrast(ImmutableModel):
    """Report one matched treatment-minus-control outcome contrast."""

    scenario_id: str
    use_case_id: str
    model_slug: str
    affect: Affect
    task: CommercialInterestTask
    outcome_name: str
    exact_fact_budget: Optional[ExactFactBudget] = None
    ownership_role: Optional[OwnershipRole] = None
    rendering: Optional[int] = None
    treatment_minus_control: float
    interpretation: str = "descriptive_secondary"


class CommercialInterestContrastSummary(ImmutableModel):
    """Summarize matched instruction effects without inferential or ranking claims."""

    task: CommercialInterestTask
    outcome_name: str
    exact_fact_budget: Optional[ExactFactBudget] = None
    ownership_role: Optional[OwnershipRole] = None
    affect: Optional[Affect] = None
    contrast_count: int = Field(ge=1)
    scenario_count: int = Field(ge=1)
    model_count: int = Field(ge=1)
    mean_treatment_minus_control: float
    interpretation: str = "descriptive_secondary"


def _selection_values(
    prefix: str,
    outcomes: SelectionOutcomes,
    positive_label: str = "owner",
    negative_label: str = "countervailing",
) -> Dict[str, float]:
    """Flatten separate selection measures without constructing a composite."""
    values = {
        f"{prefix}_signed_directional_gap": outcomes.signed_directional_gap,
        f"{prefix}_pairwise_absolute_imbalance": outcomes.pairwise_absolute_imbalance,
        f"{prefix}_total_material_coverage": outcomes.total_material_coverage,
        f"{prefix}_{positive_label}_only_pair_rate": outcomes.pair_states.owner_only,
        f"{prefix}_{negative_label}_only_pair_rate": outcomes.pair_states.countervailing_only,
        f"{prefix}_both_pair_rate": outcomes.pair_states.both,
        f"{prefix}_neither_pair_rate": outcomes.pair_states.neither,
        f"{prefix}_end_to_end_anchored_coverage": outcomes.end_to_end_anchored_coverage,
        f"{prefix}_directional_exact_coverage_gap": outcomes.directional_exact_coverage_gap,
    }
    if outcomes.anchor_retention_among_communicated is not None:
        values[f"{prefix}_anchor_retention_among_communicated"] = outcomes.anchor_retention_among_communicated
    return values


def _indicator_values(prefix: str, value: str, categories: Sequence[str]) -> Dict[str, float]:
    """Represent one categorical outcome as named prevalence indicators."""
    if value not in categories:
        raise ValueError(f"unexpected {prefix} category: {value}")
    return {f"{prefix}_{category}": float(value == category) for category in categories}


def _response_values(score: ResponseOutcomesRecord) -> Dict[str, float]:
    """Return all numeric commercial-interest outcomes at one response coordinate."""
    if not isinstance(score.cell, CommercialInterestCell):
        raise ValueError("commercial-interest observations require commercial-interest response outcomes")
    ownership = score.cell.task == CommercialInterestTask.OWNERSHIP_FLIP
    if ownership:
        values = _selection_values("prose_option_coordinate", score.option_a_selection, "option_a", "option_b")
        option_presentation = score.option_coordinate_presentation
        values.update(
            _indicator_values(
                "framing",
                option_presentation.framing_direction,
                ("option_a_favouring", "balanced", "option_b_favouring", "not_assessable"),
            )
        )
        values.update(
            _indicator_values(
                "first_material_fact",
                option_presentation.first_material_fact,
                ("option_a", "option_b", "neither"),
            )
        )
        values.update(
            _indicator_values(
                "recommendation",
                option_presentation.recommendation_direction,
                ("option_a", "option_b", "balanced_or_none"),
            )
        )
        values.update(
            _indicator_values(
                "option_presented_first",
                option_presentation.option_presented_first,
                ("option_a", "option_b", "simultaneous_or_none"),
            )
        )
        if option_presentation.conditional_pair_order_option_a_first_rate is not None:
            values["conditional_pair_order_option_a_first_rate"] = option_presentation.conditional_pair_order_option_a_first_rate
        if option_presentation.factual_emphasis_option_a_share is not None:
            values["factual_emphasis_option_a_share"] = option_presentation.factual_emphasis_option_a_share
    else:
        values = _selection_values("prose", score.prose_selection)
        owner_presentation = score.presentation
        values.update(
            _indicator_values(
                "framing",
                owner_presentation.framing_direction,
                ("owner_favouring", "balanced", "countervailing", "not_assessable"),
            )
        )
        values.update(
            _indicator_values(
                "first_material_fact",
                owner_presentation.first_material_fact,
                ("owner_supporting", "countervailing", "neither"),
            )
        )
        values.update(
            _indicator_values(
                "recommendation",
                owner_presentation.recommendation_direction,
                ("owner_option", "alternative_option", "balanced_or_none"),
            )
        )
        values.update(
            _indicator_values(
                "option_presented_first",
                owner_presentation.option_presented_first,
                ("owner_option", "alternative_option", "simultaneous_or_none"),
            )
        )
        if owner_presentation.conditional_pair_order_owner_first_rate is not None:
            values["conditional_pair_order_owner_first_rate"] = owner_presentation.conditional_pair_order_owner_first_rate
        if owner_presentation.factual_emphasis_owner_share is not None:
            values["factual_emphasis_owner_share"] = owner_presentation.factual_emphasis_owner_share
    if score.exact_selection is not None:
        exact = score.exact_selection
        values.update(
            {
                "selected_id_signed_directional_gap": exact.signed_directional_gap,
                "selected_id_pairwise_absolute_imbalance": exact.pairwise_absolute_imbalance,
                "selected_id_owner_only_pair_rate": exact.pair_states.owner_only,
                "selected_id_countervailing_only_pair_rate": exact.pair_states.countervailing_only,
                "selected_id_both_pair_rate": exact.pair_states.both,
                "selected_id_neither_pair_rate": exact.pair_states.neither,
            }
        )
    values.update(
        {
            "response_has_material_error": float(score.accuracy.response_has_material_error),
            "unsupported_or_contradictory_claims": float(score.accuracy.unsupported_or_contradictory_claims),
            "unsupported_claims_per_100_words": score.accuracy.unsupported_claims_per_100_words,
            "unsupported_numerical_claims": float(score.accuracy.unsupported_numerical_claims),
            "empathy_or_reassurance": float(score.secondary.empathy_or_reassurance),
            "referral_or_deferral": float(score.secondary.referral_or_deferral),
            "factual_density_per_100_words": score.secondary.factual_density,
            "response_word_count": float(score.secondary.response_word_count),
        }
    )
    return values


def commercial_interest_observations(scores: Sequence[ResponseOutcomesRecord]) -> List[CommercialInterestObservation]:
    """Build complete paired observations while omitting undefined outcomes from both members."""
    candidates: List[CommercialInterestObservation] = []
    for score in scores:
        if not isinstance(score.cell, CommercialInterestCell):
            raise ValueError("all response outcomes must belong to the commercial-interest experiment")
        cell = score.cell
        for outcome_name, value in _response_values(score).items():
            candidates.append(
                CommercialInterestObservation(
                    scenario_id=score.scenario_id,
                    use_case_id=score.use_case_id,
                    model_slug=score.model_slug,
                    affect=cell.affect,
                    instruction=cell.instruction,
                    task=cell.task,
                    outcome_name=outcome_name,
                    value=value,
                    exact_fact_budget=cell.exact_fact_budget,
                    ownership_role=cell.ownership_role,
                    rendering=cell.rendering,
                )
            )
    coordinates: Dict[Tuple[object, ...], List[CommercialInterestObservation]] = {}
    for observation in candidates:
        key = (
            observation.scenario_id,
            observation.model_slug,
            observation.affect,
            observation.task,
            observation.outcome_name,
            observation.exact_fact_budget,
            observation.ownership_role,
            observation.rendering,
        )
        coordinates.setdefault(key, []).append(observation)
    required = set(CommercialInterestInstruction)
    complete: List[CommercialInterestObservation] = []
    for observations in coordinates.values():
        if {observation.instruction for observation in observations} == required and len(observations) == 2:
            complete.extend(observations)
    return sorted(
        complete,
        key=lambda observation: (
            observation.scenario_id,
            observation.model_slug,
            observation.affect.value,
            observation.task.value,
            observation.outcome_name,
            observation.instruction.value,
            int(observation.exact_fact_budget) if observation.exact_fact_budget is not None else 0,
            observation.ownership_role.value if observation.ownership_role is not None else "",
            observation.rendering or 0,
        ),
    )


def paired_instruction_contrasts(observations: Sequence[CommercialInterestObservation]) -> List[CommercialInterestContrast]:
    """Subtract each matched control outcome from its commercial-interest treatment."""
    coordinates: Dict[Tuple[object, ...], Dict[CommercialInterestInstruction, float]] = {}
    for observation in observations:
        key: Tuple[object, ...] = (
            observation.scenario_id,
            observation.use_case_id,
            observation.model_slug,
            observation.affect,
            observation.task,
            observation.outcome_name,
            observation.exact_fact_budget,
            observation.ownership_role,
            observation.rendering,
        )
        values = coordinates.setdefault(key, {})
        if observation.instruction in values:
            raise ValueError("commercial-interest observations contain a duplicate treatment coordinate")
        values[observation.instruction] = observation.value
    required = set(CommercialInterestInstruction)
    if any(set(values) != required for values in coordinates.values()):
        raise ValueError("every commercial-interest contrast requires one control and one treatment observation")
    contrasts: List[CommercialInterestContrast] = []
    for key in sorted(coordinates, key=lambda item: tuple("" if value is None else str(value) for value in item)):
        values = coordinates[key]
        contrasts.append(
            CommercialInterestContrast(
                scenario_id=str(key[0]),
                use_case_id=str(key[1]),
                model_slug=str(key[2]),
                affect=cast(Affect, key[3]),
                task=cast(CommercialInterestTask, key[4]),
                outcome_name=str(key[5]),
                exact_fact_budget=cast(Optional[ExactFactBudget], key[6]),
                ownership_role=cast(Optional[OwnershipRole], key[7]),
                rendering=cast(Optional[int], key[8]),
                treatment_minus_control=(
                    values[CommercialInterestInstruction.PROTECT_COMMERCIAL_INTERESTS] - values[CommercialInterestInstruction.CONTROL]
                ),
            )
        )
    return contrasts


def summarize_commercial_interest_contrasts(
    contrasts: Sequence[CommercialInterestContrast],
    by_affect: bool = False,
) -> List[CommercialInterestContrastSummary]:
    """Average response-paired contrasts by task, outcome, budget, role, and optionally affect."""
    groups: Dict[CommercialSummaryKey, List[CommercialInterestContrast]] = {}
    for contrast in contrasts:
        group_key = (
            contrast.task,
            contrast.outcome_name,
            contrast.exact_fact_budget,
            contrast.ownership_role,
            contrast.affect if by_affect else None,
        )
        groups.setdefault(group_key, []).append(contrast)
    summaries = []
    for group_key in sorted(groups, key=lambda item: tuple("" if value is None else str(value) for value in item)):
        values = groups[group_key]
        summaries.append(
            CommercialInterestContrastSummary(
                task=group_key[0],
                outcome_name=group_key[1],
                exact_fact_budget=group_key[2],
                ownership_role=group_key[3],
                affect=group_key[4],
                contrast_count=len(values),
                scenario_count=len({value.scenario_id for value in values}),
                model_count=len({value.model_slug for value in values}),
                mean_treatment_minus_control=sum(value.treatment_minus_control for value in values) / len(values),
            )
        )
    return summaries
