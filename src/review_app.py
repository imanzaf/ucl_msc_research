"""Local-only Streamlit review and annotation interface with atomic JSONL storage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ResearcherScenarioReview, ReviewPass
from src.data_models.scenarios import CandidateScenario, MinimalCompleteResponse
from src.data_models.scoring import ConditionBlindScoringInput, EvaluationCheckpoint, ResponseSpan
from src.scenarios.acceptance import validate_candidate_scenario_hash
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl, write_model_json_atomic


class ReviewPage(str, Enum):
    """Identify the review workflows exposed by the local application."""

    SCENARIO_INITIAL = "Scenario review"
    CONVERSATION_INITIAL = "Conversation annotation"


ModelT = TypeVar("ModelT", bound=BaseModel)


class ReviewStore:
    """Read accepted inputs and atomically persist schema-validated review records."""

    def __init__(
        self,
        candidate_root: Path,
        scoring_input_root: Path,
        output_root: Path,
        annotation_sample_manifest_path: Optional[Path] = None,
    ) -> None:
        """Configure local artifact and output paths without opening a database."""
        self.candidate_root = candidate_root
        self.scoring_input_root = scoring_input_root
        self.output_root = output_root
        self.annotation_sample_manifest_path = annotation_sample_manifest_path

    @property
    def scenario_reviews_path(self) -> Path:
        """Return the append-only scenario-review JSONL path."""
        return self.output_root / "scenario_reviews.jsonl"

    @property
    def conversation_annotations_path(self) -> Path:
        """Return the append-only conversation-annotation JSONL path."""
        return self.output_root / "conversation_annotations.jsonl"

    def list_candidates(self) -> List[CandidateScenario]:
        """Load hash-valid generated candidates awaiting researcher acceptance."""
        candidates = [read_model_json(path, CandidateScenario) for path in sorted(self.candidate_root.glob("*/candidate.json"))]
        for candidate in candidates:
            validate_candidate_scenario_hash(candidate)
        return candidates

    def list_scoring_inputs(self) -> List[ConditionBlindScoringInput]:
        """Load condition-blind conversation scoring inputs."""
        return [read_model_json(path, ConditionBlindScoringInput) for path in sorted(self.scoring_input_root.glob("*.json"))]

    def scenario_reviews(self) -> List[ResearcherScenarioReview]:
        """Load all persisted scenario review passes."""
        return read_model_jsonl(self.scenario_reviews_path, ResearcherScenarioReview)

    def conversation_annotations(self) -> List[ConversationAnnotation]:
        """Load all persisted conversation annotation passes."""
        return read_model_jsonl(self.conversation_annotations_path, ConversationAnnotation)

    def _candidate(self, scenario_id: str) -> CandidateScenario:
        """Resolve one candidate by its immutable scenario ID."""
        candidate = next((item for item in self.list_candidates() if item.scenario_id == scenario_id), None)
        if candidate is None:
            raise ValueError(f"unknown candidate scenario: {scenario_id}")
        return candidate

    def _scoring_input(self, blind_conversation_id: str) -> ConditionBlindScoringInput:
        """Resolve one condition-blind scoring input by its opaque ID."""
        for path in self.scoring_input_root.rglob("*.json"):
            scoring_input = read_model_json(path, ConditionBlindScoringInput)
            if scoring_input.blind_conversation_id == blind_conversation_id:
                return scoring_input
        raise ValueError(f"unknown blind conversation: {blind_conversation_id}")

    def _annotation_sample(self) -> Optional[AnnotationSampleManifest]:
        """Load and authenticate the frozen sample when conversation review is configured."""
        if self.annotation_sample_manifest_path is None:
            return None
        if not self.annotation_sample_manifest_path.exists():
            raise ValueError("conversation review requires the frozen annotation-sample manifest")
        sample = read_model_json(self.annotation_sample_manifest_path, AnnotationSampleManifest)
        validate_model_self_hash(sample, "manifest_sha256")
        return sample

    def save_scenario_review(self, review: ResearcherScenarioReview) -> None:
        """Validate and append the scenario's single researcher review under a lock."""
        candidate = self._candidate(review.scenario_id)
        if review.reviewed_artifact_sha256 != candidate.candidate_sha256:
            raise ValueError("scenario review does not bind the selected candidate hash")
        if review.reviewed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("scenario review timestamp cannot be in the future")

        def validate(existing: List[ResearcherScenarioReview], new: ResearcherScenarioReview) -> None:
            """Require one immutable researcher review per scenario."""
            if any(record.review_id == new.review_id for record in existing):
                raise ValueError(f"duplicate scenario review id: {new.review_id}")
            if any(record.scenario_id == new.scenario_id for record in existing):
                raise ValueError("a researcher scenario review already exists for this item")

        append_model_jsonl_validated(self.scenario_reviews_path, review, validate)

    def save_conversation_annotation(self, annotation: ConversationAnnotation) -> None:
        """Validate blinded content/workflow linkage and append one annotation while locked."""
        sample = self._annotation_sample()
        scoring_input = self._scoring_input(annotation.blind_conversation_id)
        if annotation.scoring_input_sha256 != artifact_sha256(scoring_input):
            raise ValueError("annotation does not bind the selected scoring input")
        _validate_annotation_content(annotation, scoring_input)
        if annotation.submitted_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("annotation timestamp cannot be in the future")

        def validate(existing: List[ConversationAnnotation], new: ConversationAnnotation) -> None:
            """Require one sampled annotation per researcher and conversation."""
            if any(record.annotation_id == new.annotation_id for record in existing):
                raise ValueError(f"duplicate conversation annotation id: {new.annotation_id}")
            if sample is not None and new.blind_conversation_id not in sample.conversation_ids:
                raise ValueError("annotation is outside the frozen conversation sample")
            if any(record.blind_conversation_id == new.blind_conversation_id and record.researcher_id == new.researcher_id for record in existing):
                raise ValueError("an annotation already exists for this researcher/item")

        append_model_jsonl_validated(self.conversation_annotations_path, annotation, validate)

    def save_approved_minimal_response(self, response: MinimalCompleteResponse) -> None:
        """Validate and atomically save the researcher-edited minimal response used at acceptance."""
        candidate = self._candidate(response.scenario_id)
        if not response.approved:
            raise ValueError("minimal response must carry explicit researcher approval")
        fact_ids = {fact.fact_id for fact in candidate.material_facts}
        essential_ids = {element.element_id for fact in candidate.material_facts for element in fact.specificity_elements if element.essential}
        if set(response.covered_fact_ids) != fact_ids or not essential_ids.issubset(response.covered_specificity_element_ids):
            raise ValueError("approved minimal response does not cover every required fact/detail")
        write_model_json_atomic(self.output_root / "approved_minimal_responses" / f"{response.scenario_id}.json", response)


def _validate_blind_span(span: ResponseSpan, checkpoint: EvaluationCheckpoint, scoring_input: ConditionBlindScoringInput) -> None:
    """Validate one annotation span against the condition-blind assistant text."""
    turn_by_index: Dict[int, str] = {turn.turn_index: turn.content for turn in scoring_input.agent_turns}
    if checkpoint == EvaluationCheckpoint.INITIAL and span.turn_index != 1:
        raise ValueError("initial annotation spans may cite only assistant turn 1")
    if checkpoint == EvaluationCheckpoint.CUMULATIVE and span.turn_index not in {1, 3}:
        raise ValueError("cumulative annotation spans may cite only assistant turns 1 and 3")
    content = turn_by_index.get(span.turn_index)
    if content is None or span.end_char > len(content) or content[span.start_char : span.end_char] != span.exact_quote:
        raise ValueError("annotation span does not match the exact blind-input response text")


def _validate_annotation_content(annotation: ConversationAnnotation, scoring_input: ConditionBlindScoringInput) -> None:
    """Validate fact IDs, per-fact evidence, checkpoints, quotes, and visible-evidence boundaries."""
    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    expected_fact_keys = {(fact_id, checkpoint) for fact_id in fact_by_id for checkpoint in EvaluationCheckpoint}
    observed_fact_keys = {(judgment.fact_id, judgment.checkpoint) for judgment in annotation.fact_judgments}
    if observed_fact_keys != expected_fact_keys:
        raise ValueError("annotation must contain both checkpoints for every blind fact")
    for judgment in annotation.fact_judgments:
        fact = fact_by_id[judgment.fact_id]
        permitted_references = {
            *{span.source_item_id for span in fact.source_support},
            *{element.element_id for element in fact.specificity_elements},
        }
        if not set(judgment.source_evidence_references).issubset(permitted_references):
            raise ValueError("annotation fact judgment cites evidence belonging to another fact")
        for span in [*judgment.response_spans, *judgment.framing_spans]:
            _validate_blind_span(span, judgment.checkpoint, scoring_input)
        expected_element_ids = {element.element_id for element in fact.specificity_elements}
        observed_element_ids = {item.element_id for item in judgment.specificity_element_judgments}
        if judgment.disclosure.value != "omitted" and observed_element_ids != expected_element_ids:
            raise ValueError("annotation must decide every typed specificity element for a present fact")
        for element_judgment in judgment.specificity_element_judgments:
            if element_judgment.element_id not in expected_element_ids:
                raise ValueError("annotation specificity judgment belongs to another fact")
            for span in element_judgment.response_spans:
                _validate_blind_span(span, judgment.checkpoint, scoring_input)
    if {judgment.checkpoint for judgment in annotation.response_judgments} != set(EvaluationCheckpoint):
        raise ValueError("annotation requires one response judgment at each checkpoint")
    for response_judgment in annotation.response_judgments:
        for field_name in [
            "supportive_acknowledgement_spans",
            "unsupported_reassurance_spans",
            "refusal_spans",
            "signposting_spans",
            "generic_risk_disclaimer_spans",
            "disclaimer_washing_spans",
        ]:
            for span in getattr(response_judgment, field_name):
                _validate_blind_span(span, response_judgment.checkpoint, scoring_input)
    visible_source_ids = {span.source_item_id for fact in scoring_input.facts for span in fact.source_support}
    claim_ids: Set[str] = set()
    for claim in annotation.claim_judgments:
        if claim.claim_id in claim_ids:
            raise ValueError("annotation claim ids must be unique")
        claim_ids.add(claim.claim_id)
        if not set(claim.visible_evidence_references).issubset(visible_source_ids):
            raise ValueError("annotation claim cites evidence outside the evaluated model's visible source")
        _validate_blind_span(claim.claim_span, claim.checkpoint, scoring_input)


def _record_payload_from_text(raw_json: str) -> Dict[str, Any]:
    """Parse a JSON object entered in a local review form."""
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("form payload must be a JSON object")
    return payload


def _render_source(st: Any, scenario: CandidateScenario) -> None:
    """Display the canonical source and hidden validation metadata for scenario review."""
    st.subheader(scenario.scenario_id)
    st.markdown(scenario.source_order_a.rendered_text)
    with st.expander("Evaluated deployment context"):
        st.caption("This is the guidance and natural customer dialogue passed to evaluated models.")
        st.json(
            {
                "deployment_context": scenario.deployment_context.model_dump(mode="json"),
                "customer_messages": scenario.customer_messages.model_dump(mode="json"),
            }
        )
    with st.expander("Hidden research design"):
        st.caption(
            "Hidden from evaluated prompts. Verify a real high-stakes choice, opposed customer/provider actions, and directional fact alignment."
        )
        st.json(
            {
                "research_metadata": scenario.research_metadata.model_dump(mode="json"),
                "diagnostic_design": scenario.diagnostic_design.model_dump(mode="json"),
            }
        )
    st.subheader("Blinded pair diagnostics")
    st.caption("Descriptive only: the mandatory pair-matching judgement controls acceptance; no automatic balance threshold is applied.")
    st.json([diagnostic.model_dump(mode="json") for diagnostic in build_pair_diagnostics(scenario)])
    with st.expander("Facts and minimal complete response"):
        st.json(
            {
                "material_facts": [fact.model_dump(mode="json") for fact in scenario.material_facts],
                "neutral_facts": [fact.model_dump(mode="json") for fact in scenario.neutral_facts],
                "numeric_registry": scenario.numeric_registry.model_dump(mode="json"),
                "source_order_plan": scenario.source_order_plan.model_dump(mode="json"),
                "minimal_complete_response": scenario.minimal_complete_response.model_dump(mode="json"),
            }
        )


def _render_scoring_input(st: Any, scoring_input: ConditionBlindScoringInput) -> None:
    """Display only condition-blind evidence, randomised facts, and agent responses."""
    st.subheader(scoring_input.blind_conversation_id)
    st.markdown(scoring_input.visible_source_text)
    st.json({"facts": [fact.model_dump(mode="json") for fact in scoring_input.facts]})
    for turn in scoring_input.agent_turns:
        st.markdown(f"**Agent turn {turn.turn_index}**")
        st.write(turn.content)


def _submit_json_record(
    st: Any,
    key: str,
    model_type: Type[ModelT],
    save_callback: Callable[[ModelT], None],
    bound_fields: Dict[str, Any],
    label: str = "Schema-valid record JSON",
) -> None:
    """Bind trusted workflow fields, validate strict JSON, and save atomically."""
    raw_json = st.text_area(label, height=320, key=f"{key}_payload")
    if st.button("Validate and save", key=f"{key}_submit"):
        try:
            payload = _record_payload_from_text(raw_json)
            payload.update(bound_fields)
            record = model_type.model_validate(payload)
            save_callback(record)
        except (ValueError, ValidationError, json.JSONDecodeError) as error:
            st.error(str(error))
        else:
            st.success("Saved atomically.")


def run_streamlit_app(store: ReviewStore) -> None:
    """Render the local-only review application without execution controls."""
    import streamlit as st

    st.set_page_config(page_title="Local review", layout="wide")
    st.title("Local review and annotation")
    st.caption("Review only: no API, generation, experiment execution, or automated scoring controls.")
    page = ReviewPage(st.sidebar.selectbox("Page", [item.value for item in ReviewPage]))
    now = datetime.now(timezone.utc)
    if page == ReviewPage.SCENARIO_INITIAL:
        scenarios = store.list_candidates()
        if not scenarios:
            st.info("No generated candidates are available for review.")
            return
        reviewed_ids = {review.scenario_id for review in store.scenario_reviews()}
        pending = [scenario for scenario in scenarios if scenario.scenario_id not in reviewed_ids]
        if not pending:
            st.info("All candidate scenarios have a researcher review.")
            return
        scenario = st.selectbox("Scenario", pending, format_func=lambda item: item.scenario_id)
        _render_source(st, scenario)
        _submit_json_record(
            st,
            "scenario_initial",
            ResearcherScenarioReview,
            store.save_scenario_review,
            {
                "schema_version": "2.0.0",
                "scenario_id": scenario.scenario_id,
                "reviewed_artifact_sha256": scenario.candidate_sha256,
                "reviewed_at": now,
                "pair_diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in build_pair_diagnostics(scenario)],
            },
        )
        _submit_json_record(
            st,
            "scenario_minimal_response",
            MinimalCompleteResponse,
            store.save_approved_minimal_response,
            {
                "schema_version": "2.0.0",
                "scenario_id": scenario.scenario_id,
                "approved": True,
                "approved_at": now,
            },
            label="Minimal complete response approval JSON (content must remain unchanged)",
        )
        return
    scoring_inputs = store.list_scoring_inputs()
    if not scoring_inputs:
        st.info("No condition-blind scoring inputs are available.")
        return
    if page == ReviewPage.CONVERSATION_INITIAL:
        annotated_ids = {
            annotation.blind_conversation_id for annotation in store.conversation_annotations() if annotation.annotation_pass == ReviewPass.INITIAL
        }
        pending_inputs = [item for item in scoring_inputs if item.blind_conversation_id not in annotated_ids]
        if not pending_inputs:
            st.info("All sampled conversations have an initial annotation.")
            return
        scoring_input = st.selectbox("Conversation", pending_inputs, format_func=lambda item: item.blind_conversation_id)
        _render_scoring_input(st, scoring_input)
        _submit_json_record(
            st,
            "conversation_initial",
            ConversationAnnotation,
            store.save_conversation_annotation,
            {
                "schema_version": "2.0.0",
                "blind_conversation_id": scoring_input.blind_conversation_id,
                "annotation_pass": ReviewPass.INITIAL,
                "scoring_input_sha256": artifact_sha256(scoring_input),
                "submitted_at": now,
            },
        )
