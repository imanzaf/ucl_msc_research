"""Test hash-linked researcher acceptance and atomic accepted-bundle publication."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.data_models.common import sha256_bytes
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ResearcherScenarioReview,
    ReviewDecision,
    ScenarioReviewHistory,
    ScenarioReviewLabels,
)
from src.data_models.scenarios import MinimalCompleteResponse
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario, validate_accepted_bundle
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.word_count import count_words
from src.storage import read_model_json
from tests.factories import ZERO_HASH, make_candidate_scenario


def _passing_labels() -> ScenarioReviewLabels:
    """Return the complete passing researcher checklist."""
    return ScenarioReviewLabels(**{name: True for name in ScenarioReviewLabels.model_fields})


def test_acceptance_requires_one_researcher_review_and_publishes_complete_atomic_bundle(tmp_path: Path) -> None:
    """Build and reload the acyclic three-file bundle after one researcher review passes."""
    candidate = make_candidate_scenario()
    automated = [
        AutomatedScenarioReview(
            schema_version="2.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=kind,
            decision=ReviewDecision.ACCEPT,
            findings=[],
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id=f"reviewer/{kind.value}",
            reviewer_prompt_sha256=ZERO_HASH,
            reviewed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        for kind in AutomatedReviewKind
    ]
    initial_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    initial = ResearcherScenarioReview(
        schema_version="2.0.0",
        review_id="SCENARIO_INITIAL_ACCEPT",
        anonymised_item_id="S-001",
        scenario_id=candidate.scenario_id,
        decision=ReviewDecision.ACCEPT,
        labels=_passing_labels(),
        pair_diagnostics=build_pair_diagnostics(candidate),
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=initial_at,
        researcher_id="researcher",
        notes="Initial acceptance.",
    )
    history = ScenarioReviewHistory(
        schema_version="2.0.0",
        scenario_id=candidate.scenario_id,
        automated_reviews=automated,
        revisions=[],
        researcher_reviews=[initial],
    )
    minimal_payload = candidate.minimal_complete_response.model_dump(mode="json")
    minimal_payload.update(
        {
            "approved": True,
            "approved_at": initial_at,
            "approved_by": "researcher",
        }
    )
    approved_minimal = MinimalCompleteResponse.model_validate(minimal_payload)
    changed_text = approved_minimal.text + " Changed after review."
    changed_minimal = approved_minimal.model_copy(
        update={
            "text": changed_text,
            "word_count": count_words(changed_text),
            "text_sha256": sha256_bytes(changed_text.encode("utf-8")),
        }
    )
    with pytest.raises(ValueError, match="changed after review"):
        build_accepted_scenario(
            candidate,
            history,
            changed_minimal,
            accepted_at=initial_at,
            accepted_by="researcher",
        )
    acceptance_record, accepted = build_accepted_scenario(
        candidate,
        history,
        approved_minimal,
        accepted_at=initial_at,
        accepted_by="researcher",
    )
    publish_accepted_scenario(accepted, history, acceptance_record, tmp_path)
    scenario_root = tmp_path / candidate.scenario_id
    assert sorted(path.name for path in scenario_root.iterdir()) == [
        "acceptance_record.json",
        "accepted_scenario.json",
        "review_history.json",
    ]
    reloaded_history = read_model_json(scenario_root / "review_history.json", ScenarioReviewHistory)
    validate_accepted_bundle(accepted, reloaded_history, acceptance_record)
