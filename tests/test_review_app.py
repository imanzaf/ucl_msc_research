"""Tests for staged six-contract conversation annotation."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Dict

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
    _render_scenario_overview,
    _render_scenario_review_form,
    _render_scenario_workspace,
    _validate_annotation_content,
    scenario_navigation_targets,
)
from src.scenarios.candidate_compatibility import candidate_scenario_from_payload
from src.storage import write_model_json_atomic
from tests.factories import (
    NOW,
    ZERO_HASH,
    flattened_candidate_content,
    make_accepted_scenario,
    make_candidate_scenario,
    make_scoring_results,
    make_transcript,
)


def _legacy_candidate_payload() -> Dict[str, Any]:
    """Return one self-hashed schema-6 candidate fixture."""
    candidate = make_candidate_scenario("CF001_C1")
    content = flattened_candidate_content(candidate)
    option_name_by_coordinate = {
        "owner_option": "arranged overdraft",
        "alternative_option": "linked-savings automatic sweep",
    }
    for fact in content["material_facts"]:
        fact["canonical_proposition"] = f"{option_name_by_coordinate[fact['option']]}: {fact['canonical_proposition']}"
        fact["materiality_rationale"] = "The fact is relevant to the customer's choice."
        fact["required_in_complete_response"] = True
        fact["materiality_rating"] = 4
    payload = {
        "schema_version": "6.0.0",
        **content,
        "fact_pairs": [
            {
                "pair_id": "CF001_C1_P1",
                "pair_type": "benefit_comparison",
                "owner_option_fact_id": "CF001_C1_F1",
                "alternative_option_fact_id": "CF001_C1_F2",
                "matching_rationale": "Compare the two benefit facts.",
            },
            {
                "pair_id": "CF001_C1_P2",
                "pair_type": "downside_comparison",
                "owner_option_fact_id": "CF001_C1_F3",
                "alternative_option_fact_id": "CF001_C1_F4",
                "matching_rationale": "Compare the two downside facts.",
            },
        ],
    }
    return {**payload, "candidate_sha256": artifact_sha256(payload)}


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


def test_scenario_review_uses_one_linear_context_edit_decision_flow() -> None:
    """Show source content once and place the decision after every fact editor."""
    workspace_source = inspect.getsource(_render_scenario_workspace)
    assert "st.columns" not in workspace_source
    assert workspace_source.count("_render_scenario_navigation") == 2
    assert workspace_source.index("_render_scenario_navigation") < workspace_source.index("_render_scenario_overview")
    assert workspace_source.index("_render_scenario_overview") < workspace_source.index("_render_scenario_review_form")

    overview_source = inspect.getsource(_render_scenario_overview)
    assert "material_facts" not in overview_source
    assert overview_source.index('st.subheader("Agent task")') < overview_source.index('st.subheader("User queries")')
    assert overview_source.index('st.subheader("User queries")') < overview_source.index('st.subheader("Option descriptions")')

    form_source = inspect.getsource(_render_scenario_review_form)
    assert 'persist_state="session"' in form_source
    assert form_source.index("for polarity in") < form_source.index('st.text_input("Researcher ID", value="imanzafar")')
    assert form_source.index('st.text_input("Researcher ID", value="imanzafar")') < form_source.index("st.segmented_control")


def test_scenario_navigation_targets_cover_boundaries_and_middle() -> None:
    """Disable navigation at list boundaries and expose both directions in the middle."""
    scenario_ids = ["CF001_C1", "CF002_C1", "CF003_C1"]
    assert scenario_navigation_targets(scenario_ids, "CF001_C1") == (None, "CF002_C1")
    assert scenario_navigation_targets(scenario_ids, "CF002_C1") == ("CF001_C1", "CF003_C1")
    assert scenario_navigation_targets(scenario_ids, "CF003_C1") == ("CF002_C1", None)
    with pytest.raises(ValueError, match="not available"):
        scenario_navigation_targets(scenario_ids, "CF004_C1")


def test_schema_six_candidate_is_authenticated_and_converted_for_review() -> None:
    """Open an existing schema-6 run as a deterministic schema-9 review candidate."""
    legacy_payload = _legacy_candidate_payload()
    candidate = candidate_scenario_from_payload(legacy_payload)
    assert candidate.schema_version == "9.0.0"
    assert "fact_pairs" not in type(candidate).model_fields
    assert candidate.candidate_sha256 != legacy_payload["candidate_sha256"]
    assert [fact.fact_id for fact in candidate.material_facts] == [f"CF001_C1_F{index}" for index in range(1, 5)]
    assert all(
        not fact.canonical_proposition.startswith(("arranged overdraft:", "linked-savings automatic sweep:")) for fact in candidate.material_facts
    )
    assert all(
        set(type(fact).model_fields) == {"fact_id", "pair_id", "option", "polarity", "canonical_proposition"} for fact in candidate.material_facts
    )


def test_schema_seven_candidate_is_authenticated_without_redundant_fact_metadata() -> None:
    """Convert one authenticated schema-7 candidate into the option-centric schema."""
    current = make_candidate_scenario("CF001_C1")
    payload = flattened_candidate_content(current)
    for fact in payload["material_facts"]:
        fact["materiality_rationale"] = "The fact is relevant to the customer's choice."
        fact["required_in_complete_response"] = True
        fact["materiality_rating"] = 4
    previous_payload = {"schema_version": "7.0.0", **payload}
    previous_payload["candidate_sha256"] = artifact_sha256(previous_payload)

    candidate = candidate_scenario_from_payload(previous_payload)

    assert candidate.schema_version == "9.0.0"
    assert candidate.candidate_sha256 != previous_payload["candidate_sha256"]
    assert not {"option_descriptions", "material_facts", "specificity_elements"} & set(candidate.model_dump(mode="json"))


def test_schema_six_compatibility_rejects_an_inconsistent_pair_manifest() -> None:
    """Reject legacy pair metadata that does not match the authenticated facts."""
    legacy_payload = _legacy_candidate_payload()
    legacy_payload["fact_pairs"][0]["owner_option_fact_id"] = "CF001_C1_F2"
    legacy_payload["candidate_sha256"] = artifact_sha256({key: value for key, value in legacy_payload.items() if key != "candidate_sha256"})
    with pytest.raises(ValueError, match="pair manifest"):
        candidate_scenario_from_payload(legacy_payload)
