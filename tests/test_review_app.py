"""Tests for staged six-contract conversation annotation."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256
from src.data_models.scenario_review import ReviewPass
from src.data_models.scoring import AnnotationScoringPackage, ScoredResponse
from src.experiments.scoring_pipeline import build_condition_blind_inputs
from src.review_app import (
    ReviewStore,
    _empty_response_annotation_payload,
    _parse_response_annotation_payload,
    _render_conversation_annotation,
    _validate_annotation_content,
)
from src.storage import write_model_json_atomic
from tests.factories import NOW, ZERO_HASH, make_accepted_scenario, make_scoring_results, make_transcript


def _annotation_package() -> tuple[object, object, AnnotationScoringPackage]:
    """Return one transcript and its paired response-isolated annotation package."""
    scenario = make_accepted_scenario()
    transcript = make_transcript(scenario)
    scoring_inputs = build_condition_blind_inputs(transcript, scenario, 7)
    package = AnnotationScoringPackage(
        schema_version="3.0.0",
        blind_conversation_id=next(iter(scoring_inputs.values())).blind_conversation_id,
        scoring_inputs=scoring_inputs,
    )
    return scenario, transcript, package


def _annotation(
    scenario: object,
    transcript: object,
    package: AnnotationScoringPackage,
) -> ConversationAnnotation:
    """Build one complete valid human annotation from fixture scoring results."""
    content, presentation, accuracy = make_scoring_results(scenario, transcript)
    return ConversationAnnotation(
        schema_version="3.0.0",
        annotation_id="ANNOTATION_FIXTURE",
        anonymised_item_id="ITEM_FIXTURE",
        blind_conversation_id=package.blind_conversation_id,
        annotation_pass=ReviewPass.INITIAL,
        content_judgments={response: content[response].judgments for response in ScoredResponse},
        presentation_findings={response: presentation[response].findings for response in ScoredResponse},
        accuracy_findings={response: accuracy[response].findings for response in ScoredResponse},
        scoring_input_sha256=artifact_sha256(package.scoring_inputs),
        rubric_sha256=ZERO_HASH,
        researcher_id="researcher",
        submitted_at=NOW,
    )


def test_store_loads_paired_inputs_and_saves_one_complete_annotation(
    tmp_path: Path,
) -> None:
    """The store hashes both inputs and rejects a duplicate conversation annotation."""
    scenario, transcript, package = _annotation_package()
    scoring_root = tmp_path / "inputs"
    output_root = tmp_path / "outputs"
    write_model_json_atomic(
        scoring_root / f"{package.blind_conversation_id}.json",
        package,
    )
    store = ReviewStore(
        candidate_root=tmp_path / "candidates",
        scoring_input_root=scoring_root,
        output_root=output_root,
    )
    assert store.list_scoring_inputs() == [package]
    annotation = _annotation(scenario, transcript, package)
    store.save_conversation_annotation(annotation)
    assert store.conversation_annotations() == [annotation]
    with pytest.raises(ValueError, match="already exists"):
        store.save_conversation_annotation(annotation.model_copy(update={"annotation_id": "ANNOTATION_SECOND"}))


def test_annotation_validation_forbids_cross_response_evidence() -> None:
    """A follow-up judgment cannot cite the hidden initial assistant response."""
    scenario, transcript, package = _annotation_package()
    annotation = _annotation(scenario, transcript, package)
    follow_up = annotation.content_judgments[ScoredResponse.FOLLOW_UP][0]
    initial_fact = annotation.content_judgments[ScoredResponse.INITIAL][0]
    invalid_follow_up = follow_up.model_copy(
        update={
            "present": True,
            "evidence": initial_fact.evidence,
        }
    )
    invalid = annotation.model_copy(
        update={
            "content_judgments": {
                **annotation.content_judgments,
                ScoredResponse.FOLLOW_UP: [
                    invalid_follow_up,
                    *annotation.content_judgments[ScoredResponse.FOLLOW_UP][1:],
                ],
            }
        }
    )
    with pytest.raises(ValueError, match="other assistant response"):
        _validate_annotation_content(invalid, package)


def test_empty_response_template_has_binary_fact_and_marker_decisions() -> None:
    """The editor template includes all four facts and every registered marker."""
    _scenario, _transcript, package = _annotation_package()
    scoring_input = package.scoring_inputs[ScoredResponse.INITIAL]
    payload = _empty_response_annotation_payload(scoring_input)
    assert len(payload["content_judgments"]) == 4
    expected_markers = sum(len(fact.specificity_elements) for fact in scoring_input.facts)
    assert sum(len(item["marker_judgments"]) for item in payload["content_judgments"]) == expected_markers
    parsed = _parse_response_annotation_payload(
        json.dumps(payload),
        scoring_input,
    )
    assert parsed["presentation_findings"] == []
    assert parsed["accuracy_findings"] == []


def test_streamlit_workflow_gates_follow_up_on_locked_session_state() -> None:
    """The follow-up renderer is structurally below the initial validation return."""
    source = inspect.getsource(_render_conversation_annotation)
    assert "if state_key not in st.session_state" in source
    assert "Validate and lock initial response" in source
    assert source.index("return") < source.index("_render_scoring_input(st, follow_up_input)")
