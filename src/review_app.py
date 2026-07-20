"""Local-only Streamlit review and annotation interface with atomic JSONL storage."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.data_models.annotations import ConversationAnnotation, repeat_washout_elapsed
from src.data_models.common import artifact_sha256, sha256_bytes, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ResearcherScenarioReview, ReviewPass
from src.data_models.scenarios import CandidateScenario, MinimalCompleteResponse
from src.data_models.scoring import ConditionBlindScoringInput, EvaluationCheckpoint, ResponseSpan
from src.scenarios.acceptance import validate_candidate_scenario_hash
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl, write_model_json_atomic


class ReviewPage(str, Enum):
    """Identify the six review workflows exposed by the local application."""

    SCENARIO_INITIAL = "Scenario review"
    SCENARIO_REPEAT = "Scenario repeat review"
    SCENARIO_RESOLUTION = "Scenario resolution"
    CONVERSATION_INITIAL = "Conversation annotation"
    CONVERSATION_REPEAT = "Conversation repeat annotation"
    CONVERSATION_RESOLUTION = "Conversation resolution"


ModelT = TypeVar("ModelT", bound=BaseModel)


def build_repeat_scoring_input(
    original: ConditionBlindScoringInput,
    initial_annotation_id: str,
) -> ConditionBlindScoringInput:
    """Derive a deterministic new opaque id and non-identical fact order for a repeat."""
    seed = int(sha256_bytes(f"{original.randomised_fact_order_seed}:{initial_annotation_id}:repeat".encode("utf-8"))[:16], 16)
    facts = list(original.facts)
    random.Random(seed).shuffle(facts)
    if facts == original.facts:
        facts = [*facts[1:], facts[0]]
    blind_id = "BLIND_REPEAT_" + sha256_bytes(f"{original.blind_conversation_id}:{initial_annotation_id}".encode("utf-8"))[:20].upper()
    payload = original.model_dump(mode="json")
    payload.update(
        {
            "blind_conversation_id": blind_id,
            "facts": facts,
            "randomised_fact_order_seed": seed,
        }
    )
    return ConditionBlindScoringInput.model_validate(payload)


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
        """Validate workflow linkage and append one review under an interprocess lock."""
        candidate = self._candidate(review.scenario_id)
        if review.reviewed_artifact_sha256 != candidate.candidate_sha256:
            raise ValueError("scenario review does not bind the selected candidate hash")
        if review.reviewed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("scenario review timestamp cannot be in the future")

        def validate(existing: List[ResearcherScenarioReview], new: ResearcherScenarioReview) -> None:
            """Validate scenario uniqueness, repeat washout, and resolution links while locked."""
            if any(record.review_id == new.review_id for record in existing):
                raise ValueError(f"duplicate scenario review id: {new.review_id}")
            if new.review_pass == ReviewPass.INITIAL:
                if any(
                    record.review_pass == ReviewPass.INITIAL and record.scenario_id == new.scenario_id and record.researcher_id == new.researcher_id
                    for record in existing
                ):
                    raise ValueError("an initial scenario review already exists for this researcher/item")
                return
            initial = next((record for record in existing if record.review_id == new.initial_review_id), None)
            if initial is None or initial.review_pass != ReviewPass.INITIAL:
                raise ValueError("linked initial scenario review does not exist")
            if initial.scenario_id != new.scenario_id or initial.researcher_id != new.researcher_id:
                raise ValueError("linked scenario reviews must share item and researcher")
            if new.review_pass == ReviewPass.REPEAT:
                if not repeat_washout_elapsed(initial.reviewed_at, new.reviewed_at):
                    raise ValueError("scenario repeat review is blocked until the 14-day washout has elapsed")
                if any(record.review_pass == ReviewPass.REPEAT and record.initial_review_id == initial.review_id for record in existing):
                    raise ValueError("the initial scenario review already has a repeat")
                return
            repeated = next((record for record in existing if record.review_id == new.repeat_review_id), None)
            if repeated is None or repeated.review_pass != ReviewPass.REPEAT or repeated.initial_review_id != initial.review_id:
                raise ValueError("scenario resolution must bind a valid initial/repeat pair")
            if repeated.scenario_id != new.scenario_id or repeated.researcher_id != new.researcher_id:
                raise ValueError("scenario resolution pair must share item and researcher")
            if repeated.reviewed_at > new.reviewed_at:
                raise ValueError("scenario resolution cannot predate the repeat review")
            if initial.decision == repeated.decision and initial.labels == repeated.labels:
                raise ValueError("scenario resolution is permitted only for a disagreement")
            if any(
                record.review_pass == ReviewPass.RESOLUTION
                and record.initial_review_id == initial.review_id
                and record.repeat_review_id == repeated.review_id
                for record in existing
            ):
                raise ValueError("the scenario review pair is already resolved")

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
            """Validate annotation uniqueness, washout, and resolution links while locked."""
            if any(record.annotation_id == new.annotation_id for record in existing):
                raise ValueError(f"duplicate conversation annotation id: {new.annotation_id}")
            if new.annotation_pass == ReviewPass.INITIAL:
                if sample is not None and new.blind_conversation_id not in sample.conversation_ids:
                    raise ValueError("initial annotation is outside the frozen conversation sample")
                if any(
                    record.annotation_pass == ReviewPass.INITIAL
                    and record.blind_conversation_id == new.blind_conversation_id
                    and record.researcher_id == new.researcher_id
                    for record in existing
                ):
                    raise ValueError("an initial annotation already exists for this researcher/item")
                return
            initial = next((record for record in existing if record.annotation_id == new.initial_annotation_id), None)
            if initial is None or initial.annotation_pass != ReviewPass.INITIAL:
                raise ValueError("linked initial annotation does not exist")
            if initial.researcher_id != new.researcher_id:
                raise ValueError("linked annotations must share one researcher")
            if new.annotation_pass == ReviewPass.REPEAT:
                if sample is not None and initial.blind_conversation_id not in sample.repeat_conversation_ids:
                    raise ValueError("conversation was not selected for the frozen repeat sample")
                if not repeat_washout_elapsed(initial.submitted_at, new.submitted_at):
                    raise ValueError("conversation repeat annotation is blocked until the 14-day washout has elapsed")
                if any(record.annotation_pass == ReviewPass.REPEAT and record.initial_annotation_id == initial.annotation_id for record in existing):
                    raise ValueError("the initial annotation already has a repeat")
                expected_repeat = self._build_repeat_scoring_input(initial)
                if new.blind_conversation_id != expected_repeat.blind_conversation_id:
                    raise ValueError("repeat annotation does not use the required reshuffled blind input")
                if new.anonymised_item_id == initial.anonymised_item_id:
                    raise ValueError("repeat annotation requires a new anonymised item id")
                return
            repeated = next((record for record in existing if record.annotation_id == new.repeat_annotation_id), None)
            if repeated is None or repeated.annotation_pass != ReviewPass.REPEAT or repeated.initial_annotation_id != initial.annotation_id:
                raise ValueError("annotation resolution must bind a valid initial/repeat pair")
            if repeated.blind_conversation_id != new.blind_conversation_id or repeated.researcher_id != new.researcher_id:
                raise ValueError("annotation resolution must use the repeat blind item and researcher")
            if repeated.submitted_at > new.submitted_at:
                raise ValueError("annotation resolution cannot predate the repeat annotation")
            disagreement = (
                initial.fact_judgments != repeated.fact_judgments
                or initial.response_judgments != repeated.response_judgments
                or initial.claim_judgments != repeated.claim_judgments
            )
            if not disagreement:
                raise ValueError("annotation resolution is permitted only for a disagreement")
            if any(
                record.annotation_pass == ReviewPass.RESOLUTION
                and record.initial_annotation_id == initial.annotation_id
                and record.repeat_annotation_id == repeated.annotation_id
                for record in existing
            ):
                raise ValueError("the annotation pair is already resolved")

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

    def eligible_scenario_repeats(self, now: datetime) -> List[Tuple[str, str]]:
        """Return initial scenario reviews whose fourteen-day washout has elapsed."""
        reviews = self.scenario_reviews()
        repeated_prior_ids = {review.initial_review_id for review in reviews if review.review_pass == ReviewPass.REPEAT}
        return [
            (review.scenario_id, review.review_id)
            for review in reviews
            if review.review_pass == ReviewPass.INITIAL
            and review.review_id not in repeated_prior_ids
            and repeat_washout_elapsed(review.reviewed_at, now)
        ]

    def eligible_conversation_repeats(self, now: datetime) -> List[Tuple[str, str]]:
        """Return initial annotations whose fourteen-day washout has elapsed."""
        annotations = self.conversation_annotations()
        sample = self._annotation_sample()
        allowed_ids = set(sample.repeat_conversation_ids) if sample is not None else {annotation.blind_conversation_id for annotation in annotations}
        repeated_prior_ids = {annotation.initial_annotation_id for annotation in annotations if annotation.annotation_pass == ReviewPass.REPEAT}
        return [
            (annotation.blind_conversation_id, annotation.annotation_id)
            for annotation in annotations
            if annotation.annotation_pass == ReviewPass.INITIAL
            and annotation.blind_conversation_id in allowed_ids
            and annotation.annotation_id not in repeated_prior_ids
            and repeat_washout_elapsed(annotation.submitted_at, now)
        ]

    def scenario_repeat_context(self, prior_review_id: str, now: datetime) -> CandidateScenario:
        """Return a repeat scenario without exposing any prior labels or notes."""
        prior = next((review for review in self.scenario_reviews() if review.review_id == prior_review_id), None)
        if prior is None:
            raise ValueError("unknown prior scenario review")
        if prior.review_pass != ReviewPass.INITIAL:
            raise ValueError("scenario repeat context must be requested from an initial review")
        if not repeat_washout_elapsed(prior.reviewed_at, now):
            raise ValueError("scenario repeat review is blocked until the 14-day washout has elapsed")
        return self._candidate(prior.scenario_id)

    def conversation_repeat_context(self, prior_annotation_id: str, now: datetime) -> ConditionBlindScoringInput:
        """Return a newly anonymised and fact-reshuffled repeat without prior labels."""
        prior = next(
            (annotation for annotation in self.conversation_annotations() if annotation.annotation_id == prior_annotation_id),
            None,
        )
        if prior is None:
            raise ValueError("unknown prior conversation annotation")
        if prior.annotation_pass != ReviewPass.INITIAL:
            raise ValueError("conversation repeat context must be requested from an initial annotation")
        sample = self._annotation_sample()
        if sample is not None and prior.blind_conversation_id not in sample.repeat_conversation_ids:
            raise ValueError("conversation was not selected for the frozen repeat sample")
        if not repeat_washout_elapsed(prior.submitted_at, now):
            raise ValueError("conversation repeat annotation is blocked until the 14-day washout has elapsed")
        repeated = self._build_repeat_scoring_input(prior)
        write_model_json_atomic(self.scoring_input_root / ".repeat_inputs" / f"{repeated.blind_conversation_id}.json", repeated)
        return repeated

    def _build_repeat_scoring_input(self, initial: ConversationAnnotation) -> ConditionBlindScoringInput:
        """Derive a deterministic new opaque id and non-identical fact order for a repeat."""
        return build_repeat_scoring_input(self._scoring_input(initial.blind_conversation_id), initial.annotation_id)

    def unresolved_scenario_pairs(self) -> List[Tuple[str, str, str]]:
        """Return disagreeing initial/repeat scenario pairs that lack a resolution."""
        reviews = self.scenario_reviews()
        resolved = {(item.initial_review_id, item.repeat_review_id) for item in reviews if item.review_pass == ReviewPass.RESOLUTION}
        initial_by_id = {item.review_id: item for item in reviews if item.review_pass == ReviewPass.INITIAL}
        return [
            (repeat.scenario_id, initial.review_id, repeat.review_id)
            for repeat in reviews
            if repeat.review_pass == ReviewPass.REPEAT
            and (initial := initial_by_id.get(repeat.initial_review_id or "")) is not None
            and (initial.decision != repeat.decision or initial.labels != repeat.labels)
            and (initial.review_id, repeat.review_id) not in resolved
        ]

    def unresolved_annotation_pairs(self) -> List[Tuple[str, str, str]]:
        """Return disagreeing initial/repeat annotation pairs that lack a resolution."""
        annotations = self.conversation_annotations()
        resolved = {(item.initial_annotation_id, item.repeat_annotation_id) for item in annotations if item.annotation_pass == ReviewPass.RESOLUTION}
        initial_by_id = {item.annotation_id: item for item in annotations if item.annotation_pass == ReviewPass.INITIAL}
        pairs: List[Tuple[str, str, str]] = []
        for repeat in annotations:
            if repeat.annotation_pass != ReviewPass.REPEAT:
                continue
            initial = initial_by_id.get(repeat.initial_annotation_id or "")
            if initial is None or (initial.annotation_id, repeat.annotation_id) in resolved:
                continue
            disagreement = (
                initial.fact_judgments != repeat.fact_judgments
                or initial.response_judgments != repeat.response_judgments
                or initial.claim_judgments != repeat.claim_judgments
            )
            if disagreement:
                pairs.append((repeat.blind_conversation_id, initial.annotation_id, repeat.annotation_id))
        return pairs


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
        for span in judgment.response_spans:
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
    """Display both source orders and feasibility evidence for scenario review."""
    st.subheader(scenario.scenario_id)
    st.markdown(scenario.source_order_a.rendered_text)
    with st.expander("Source order B"):
        st.markdown(scenario.source_order_b.rendered_text)
    with st.expander("Facts and minimal complete response"):
        st.json(
            {
                "material_facts": [fact.model_dump(mode="json") for fact in scenario.material_facts],
                "neutral_facts": [fact.model_dump(mode="json") for fact in scenario.neutral_facts],
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
    """Render the local-only six-page review application without execution controls."""
    import streamlit as st

    st.set_page_config(page_title="V9 local review", layout="wide")
    st.title("V9 local review and annotation")
    st.caption("Review only: no API, generation, experiment execution, or automated scoring controls.")
    page = ReviewPage(st.sidebar.selectbox("Page", [item.value for item in ReviewPage]))
    now = datetime.now(timezone.utc)
    if page in {ReviewPage.SCENARIO_INITIAL, ReviewPage.SCENARIO_REPEAT, ReviewPage.SCENARIO_RESOLUTION}:
        scenarios = store.list_candidates()
        if not scenarios:
            st.info("No generated candidates are available for review.")
            return
        if page == ReviewPage.SCENARIO_INITIAL:
            reviewed_ids = {review.scenario_id for review in store.scenario_reviews() if review.review_pass == ReviewPass.INITIAL}
            pending = [scenario for scenario in scenarios if scenario.scenario_id not in reviewed_ids]
            if not pending:
                st.info("All candidate scenarios have an initial review.")
                return
            scenario = st.selectbox("Scenario", pending, format_func=lambda item: item.scenario_id)
            _render_source(st, scenario)
            _submit_json_record(
                st,
                "scenario_initial",
                ResearcherScenarioReview,
                store.save_scenario_review,
                {
                    "schema_version": "1.0.0",
                    "scenario_id": scenario.scenario_id,
                    "review_pass": ReviewPass.INITIAL,
                    "reviewed_artifact_sha256": scenario.candidate_sha256,
                    "reviewed_at": now,
                    "initial_review_id": None,
                    "repeat_review_id": None,
                    "resolution_reason": None,
                },
            )
            _submit_json_record(
                st,
                "scenario_minimal_response",
                MinimalCompleteResponse,
                store.save_approved_minimal_response,
                {
                    "schema_version": "1.0.0",
                    "scenario_id": scenario.scenario_id,
                    "approved": True,
                    "approved_at": now,
                },
                label="Minimal complete response approval JSON (content must remain unchanged)",
            )
        elif page == ReviewPage.SCENARIO_REPEAT:
            eligible = store.eligible_scenario_repeats(now)
            if not eligible:
                st.info("No scenario repeat is eligible after the 14-day washout.")
                return
            scenario_id, prior_id = st.selectbox("Eligible repeat", eligible, format_func=lambda item: item[0])
            _render_source(st, store.scenario_repeat_context(prior_id, now))
            candidate = store.scenario_repeat_context(prior_id, now)
            _submit_json_record(
                st,
                f"scenario_repeat_{scenario_id}",
                ResearcherScenarioReview,
                store.save_scenario_review,
                {
                    "schema_version": "1.0.0",
                    "scenario_id": scenario_id,
                    "review_pass": ReviewPass.REPEAT,
                    "reviewed_artifact_sha256": candidate.candidate_sha256,
                    "reviewed_at": now,
                    "initial_review_id": prior_id,
                    "repeat_review_id": None,
                    "resolution_reason": None,
                },
            )
        else:
            unresolved = store.unresolved_scenario_pairs()
            if not unresolved:
                st.info("No disagreeing scenario-review pair requires resolution.")
                return
            scenario_id, initial_id, repeat_id = st.selectbox("Unresolved pair", unresolved, format_func=lambda item: item[0])
            pair_records = [review.model_dump(mode="json") for review in store.scenario_reviews() if review.review_id in {initial_id, repeat_id}]
            st.json(pair_records)
            candidate = store._candidate(scenario_id)
            _submit_json_record(
                st,
                "scenario_resolution",
                ResearcherScenarioReview,
                store.save_scenario_review,
                {
                    "schema_version": "1.0.0",
                    "scenario_id": scenario_id,
                    "review_pass": ReviewPass.RESOLUTION,
                    "reviewed_artifact_sha256": candidate.candidate_sha256,
                    "reviewed_at": now,
                    "initial_review_id": initial_id,
                    "repeat_review_id": repeat_id,
                },
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
                "schema_version": "1.0.0",
                "blind_conversation_id": scoring_input.blind_conversation_id,
                "annotation_pass": ReviewPass.INITIAL,
                "scoring_input_sha256": artifact_sha256(scoring_input),
                "submitted_at": now,
                "initial_annotation_id": None,
                "repeat_annotation_id": None,
                "resolution_reason": None,
            },
        )
    elif page == ReviewPage.CONVERSATION_REPEAT:
        eligible = store.eligible_conversation_repeats(now)
        if not eligible:
            st.info("No conversation repeat is eligible after the 14-day washout.")
            return
        _blind_id, prior_id = st.selectbox("Eligible repeat", eligible, format_func=lambda item: item[0])
        _render_scoring_input(st, store.conversation_repeat_context(prior_id, now))
        scoring_input = store.conversation_repeat_context(prior_id, now)
        _submit_json_record(
            st,
            f"conversation_repeat_{scoring_input.blind_conversation_id}",
            ConversationAnnotation,
            store.save_conversation_annotation,
            {
                "schema_version": "1.0.0",
                "blind_conversation_id": scoring_input.blind_conversation_id,
                "annotation_pass": ReviewPass.REPEAT,
                "scoring_input_sha256": artifact_sha256(scoring_input),
                "submitted_at": now,
                "initial_annotation_id": prior_id,
                "repeat_annotation_id": None,
                "resolution_reason": None,
            },
        )
    else:
        unresolved = store.unresolved_annotation_pairs()
        if not unresolved:
            st.info("No disagreeing annotation pair requires resolution.")
            return
        blind_id, initial_id, repeat_id = st.selectbox("Unresolved pair", unresolved, format_func=lambda item: item[0])
        pair_records = [
            annotation.model_dump(mode="json")
            for annotation in store.conversation_annotations()
            if annotation.annotation_id in {initial_id, repeat_id}
        ]
        st.json(pair_records)
        scoring_input = store._scoring_input(blind_id)
        _render_scoring_input(st, scoring_input)
        _submit_json_record(
            st,
            "conversation_resolution",
            ConversationAnnotation,
            store.save_conversation_annotation,
            {
                "schema_version": "1.0.0",
                "blind_conversation_id": blind_id,
                "annotation_pass": ReviewPass.RESOLUTION,
                "scoring_input_sha256": artifact_sha256(scoring_input),
                "submitted_at": now,
                "initial_annotation_id": initial_id,
                "repeat_annotation_id": repeat_id,
            },
        )
