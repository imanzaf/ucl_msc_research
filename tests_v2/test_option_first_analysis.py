"""Test forced-choice-specific labels derived from frozen presentation outcomes."""

from __future__ import annotations

from pathlib import Path

from srcv2.analysis.option_first import ChoiceLabelBasis, OwnerRelativeChoice, label_forced_choice_scores, summarize_forced_choices
from srcv2.models.scoring import ResponseOutcomesRecord
from srcv2.storage import read_jsonl


def _option_first_scores() -> list[ResponseOutcomesRecord]:
    """Load the frozen option-first response scores used by the final protocol."""
    path = Path("data/outputs/experiments/option_first_v1/scoring/response_scores.jsonl")
    return [ResponseOutcomesRecord.model_validate(record) for record in read_jsonl(path)]


def test_option_first_labels_cover_every_response_once() -> None:
    """Require one stable forced-choice label for each of the 210 responses."""
    scores = _option_first_scores()
    labels = label_forced_choice_scores(scores)

    assert len(labels) == 210
    assert len({label.run_unit_id for label in labels}) == 210
    assert sum(label.choice_label == OwnerRelativeChoice.OWNER_OPTION for label in labels) == 63
    assert sum(label.choice_label == OwnerRelativeChoice.ALTERNATIVE_OPTION for label in labels) == 82
    assert sum(label.choice_label == OwnerRelativeChoice.NO_DISCERNIBLE_CHOICE for label in labels) == 65


def test_option_first_summary_preserves_label_basis_counts() -> None:
    """Retain explicit, framing-derived, and no-choice bases as separate audit counts."""
    scores = _option_first_scores()
    labels = label_forced_choice_scores(scores)
    summary = summarize_forced_choices(labels, scores)

    assert summary.explicit_recommendation_basis_count == 58
    assert summary.directional_framing_basis_count == 87
    assert summary.no_directional_choice_basis_count == 65
    assert sum(label.label_basis == ChoiceLabelBasis.DIRECTIONAL_FRAMING for label in labels) == 87
