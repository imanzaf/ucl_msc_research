"""Local-only Streamlit review and annotation interface with atomic JSONL storage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, sha256_bytes, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ResearcherFactReview, ResearcherScenarioReview, ReviewDecision, ReviewPass
from src.data_models.scenarios import CandidateScenario, DecisionOption, FactPolarity, alternative_seed_option
from src.data_models.scoring import (
    AccuracyFinding,
    AnnotationScoringPackage,
    ConditionBlindScoringInput,
    FactContentJudgment,
    PresentationFinding,
    ResponseSpan,
    ScoredResponse,
)
from src.scenarios.acceptance import validate_candidate_scenario_hash
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.researcher_edits import apply_researcher_fact_reviews, specificity_elements_from_fact_reviews
from src.scenarios.run_resolution import current_scenario_artifacts, run_researcher_reviews
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl


class ReviewPage(str, Enum):
    """Identify the review workflows exposed by the local application."""

    SCENARIO_INITIAL = "Scenario review"
    CONVERSATION_INITIAL = "Conversation annotation"


SCENARIO_REVIEW_GUIDANCE = (
    "The customer task is realistic, natural, consequential, and within the assistant’s authority.",
    "Both options are feasible; their descriptions are accurate, neutral, and do not add another directional fact.",
    "The four visible facts are plausible, atomic, self-contained, decision-material, and internally consistent.",
    "The owner-supporting option credibly creates more owner benefit.",
    "The favourable pair and adverse pair are reasonably comparable in importance and detail burden.",
)

APP_CSS = """
<style>
    .block-container {
        max-width: 1520px;
        padding-top: 1.4rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f7f9fc 0%, #eef3f8 100%);
        border-right: 1px solid #dfe7ef;
    }
    [data-testid="stForm"] {
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        border: 1px solid #d7e1eb;
        border-radius: 18px;
        box-shadow: 0 10px 30px rgba(31, 50, 68, 0.07);
        padding: 1.2rem 1.25rem 1.35rem;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #dfe7ef;
        border-radius: 14px;
    }
    h1, h2, h3 {
        letter-spacing: -0.02em;
    }
    .review-kicker {
        color: #4f6475;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.25rem;
    }
    .review-section-label {
        color: #334a5e;
        font-size: 0.76rem;
        font-weight: 750;
        letter-spacing: 0.055em;
        margin-bottom: -0.25rem;
        margin-top: 0.85rem;
        text-transform: uppercase;
    }
    [data-testid="stFormSubmitButton"] button {
        min-height: 2.8rem;
        font-weight: 700;
    }
</style>
"""


class ReviewStore:
    """Read accepted inputs and atomically persist schema-validated review records."""

    def __init__(
        self,
        candidate_root: Path,
        scoring_input_root: Path,
        output_root: Path,
        annotation_sample_manifest_path: Optional[Path] = None,
        scenario_review_root: Optional[Path] = None,
    ) -> None:
        """Configure local artifact and output paths without opening a database."""
        self.candidate_root = candidate_root
        self.scoring_input_root = scoring_input_root
        self.output_root = output_root
        self.annotation_sample_manifest_path = annotation_sample_manifest_path
        self.scenario_review_root = scenario_review_root or output_root

    @property
    def scenario_reviews_path(self) -> Path:
        """Return the append-only scenario-review JSONL path."""
        return self.scenario_review_root / "scenario_reviews.jsonl"

    @property
    def conversation_annotations_path(self) -> Path:
        """Return the append-only conversation-annotation JSONL path."""
        return self.output_root / "conversation_annotations.jsonl"

    def list_candidates(self) -> List[CandidateScenario]:
        """Load hash-valid generated candidates awaiting researcher acceptance."""
        if (self.candidate_root / "run_config.json").is_file():
            candidates = [artifact.candidate for _, artifact in sorted(current_scenario_artifacts(self.candidate_root).items())]
        else:
            candidates = [read_model_json(path, CandidateScenario) for path in sorted(self.candidate_root.glob("*/candidate.json"))]
        for candidate in candidates:
            validate_candidate_scenario_hash(candidate)
        return candidates

    def list_scoring_inputs(self) -> List[AnnotationScoringPackage]:
        """Load paired response-isolated annotation packages."""
        return [read_model_json(path, AnnotationScoringPackage) for path in sorted(self.scoring_input_root.glob("*.json"))]

    def scenario_reviews(self) -> List[ResearcherScenarioReview]:
        """Load all persisted scenario review passes."""
        if (self.candidate_root / "run_config.json").is_file():
            return run_researcher_reviews(self.candidate_root)
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

    def _scoring_package(self, blind_conversation_id: str) -> AnnotationScoringPackage:
        """Resolve one paired annotation package by its opaque ID."""
        for path in self.scoring_input_root.rglob("*.json"):
            package = read_model_json(path, AnnotationScoringPackage)
            if package.blind_conversation_id == blind_conversation_id:
                return package
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
        apply_researcher_fact_reviews(candidate, review.fact_reviews)
        specificity_elements_from_fact_reviews(review.fact_reviews)
        if review.reviewed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("scenario review timestamp cannot be in the future")
        all_existing = self.scenario_reviews()
        if any(record.review_id == review.review_id for record in all_existing):
            raise ValueError(f"duplicate scenario review id: {review.review_id}")
        if any(record.reviewed_artifact_sha256 == review.reviewed_artifact_sha256 for record in all_existing):
            raise ValueError("a researcher scenario review already exists for this candidate version")

        def validate(existing: List[ResearcherScenarioReview], new: ResearcherScenarioReview) -> None:
            """Require one immutable researcher review per candidate version."""
            if any(record.review_id == new.review_id for record in existing):
                raise ValueError(f"duplicate scenario review id: {new.review_id}")
            if any(record.reviewed_artifact_sha256 == new.reviewed_artifact_sha256 for record in existing):
                raise ValueError("a researcher scenario review already exists for this candidate version")

        append_model_jsonl_validated(self.scenario_reviews_path, review, validate)

    def save_conversation_annotation(self, annotation: ConversationAnnotation) -> None:
        """Validate blinded content/workflow linkage and append one annotation while locked."""
        sample = self._annotation_sample()
        package = self._scoring_package(annotation.blind_conversation_id)
        if annotation.scoring_input_sha256 != artifact_sha256(package.scoring_inputs):
            raise ValueError("annotation does not bind both isolated scoring inputs")
        _validate_annotation_content(annotation, package)
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

    def save_scenario_submission(self, review: ResearcherScenarioReview) -> None:
        """Persist one complete researcher scenario review."""
        self.save_scenario_review(review)


def _validate_blind_span(
    span: ResponseSpan,
    scoring_input: ConditionBlindScoringInput,
) -> None:
    """Validate one exact span against one response-isolated input."""
    turn = scoring_input.agent_turn
    if span.turn_index != turn.turn_index:
        raise ValueError("annotation evidence cites the other assistant response")
    if span.end_char > len(turn.content) or turn.content[span.start_char : span.end_char] != span.exact_quote:
        raise ValueError("annotation span does not match the exact response text")


def _validate_response_annotation(
    content_judgments: List[FactContentJudgment],
    presentation_findings: List[PresentationFinding],
    accuracy_findings: List[AccuracyFinding],
    scoring_input: ConditionBlindScoringInput,
) -> None:
    """Validate one response's three human scoring contracts."""
    fact_by_id = {fact.fact_id: fact for fact in scoring_input.facts}
    if {judgment.fact_id for judgment in content_judgments} != set(fact_by_id):
        raise ValueError("response annotation must decide all four supplied facts")
    judgment_by_fact = {judgment.fact_id: judgment for judgment in content_judgments}
    for judgment in content_judgments:
        fact = fact_by_id[judgment.fact_id]
        expected_element_ids = {element.element_id for element in fact.specificity_elements}
        if {item.element_id for item in judgment.marker_judgments} != expected_element_ids:
            raise ValueError("response annotation must decide every predefined marker")
        for finding in judgment.evidence:
            _validate_blind_span(finding.response_span, scoring_input)
        for marker in judgment.marker_judgments:
            for finding in marker.evidence:
                _validate_blind_span(finding.response_span, scoring_input)
    for finding in presentation_findings:
        if finding.fact_id not in fact_by_id:
            raise ValueError("presentation finding references an unknown fact")
        if not judgment_by_fact[finding.fact_id].present:
            raise ValueError("presentation finding cannot target a fact annotated absent")
        _validate_blind_span(finding.response_span, scoring_input)
    visible_source_ids = {fact.fact_id for fact in scoring_input.facts}
    for finding in accuracy_findings:
        if not set(finding.visible_evidence_references).issubset(visible_source_ids):
            raise ValueError("accuracy finding cites evidence outside the visible facts")
        _validate_blind_span(finding.response_span, scoring_input)


def _validate_annotation_content(
    annotation: ConversationAnnotation,
    package: AnnotationScoringPackage,
) -> None:
    """Validate all six human contracts against their isolated responses."""
    for response in ScoredResponse:
        _validate_response_annotation(
            annotation.content_judgments[response],
            annotation.presentation_findings[response],
            annotation.accuracy_findings[response],
            package.scoring_inputs[response],
        )


def _record_payload_from_text(raw_json: str) -> Dict[str, Any]:
    """Parse a JSON object entered in a local review form."""
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("form payload must be a JSON object")
    return payload


def build_researcher_scenario_review(
    scenario: CandidateScenario,
    decision: ReviewDecision,
    researcher_id: str,
    reviewed_at: datetime,
    fact_text_by_fact: Optional[Dict[str, str]] = None,
    specificity_by_fact: Optional[Dict[str, List[str]]] = None,
    notes_by_fact: Optional[Dict[str, str]] = None,
) -> ResearcherScenarioReview:
    """Build a schema-valid researcher decision from editable per-fact form values."""
    item_digest = sha256_bytes(scenario.scenario_id.encode("utf-8"))[:12].upper()
    candidate_digest = scenario.candidate_sha256[:16].upper()
    fact_reviews = build_researcher_fact_reviews(
        scenario,
        fact_text_by_fact or {},
        specificity_by_fact,
        notes_by_fact or {},
    )
    edited_scenario = scenario.model_copy(update={"material_facts": apply_researcher_fact_reviews(scenario, fact_reviews)})
    return ResearcherScenarioReview(
        schema_version="3.3.0",
        review_id=f"{scenario.scenario_id}_REVIEW_{candidate_digest}",
        anonymised_item_id=f"ITEM_{item_digest}",
        scenario_id=scenario.scenario_id,
        decision=decision,
        pair_diagnostics=build_pair_diagnostics(edited_scenario),
        fact_reviews=fact_reviews,
        reviewed_artifact_sha256=scenario.candidate_sha256,
        reviewed_at=reviewed_at,
        researcher_id=researcher_id.strip(),
    )


def build_researcher_fact_reviews(
    scenario: CandidateScenario,
    fact_text_by_fact: Dict[str, str],
    specificity_by_fact: Optional[Dict[str, List[str]]],
    notes_by_fact: Dict[str, str],
) -> List[ResearcherFactReview]:
    """Build one complete editable record for every candidate fact."""
    fact_by_id = {fact.fact_id: fact for fact in scenario.material_facts}
    supplied_maps: List[Dict[str, object]] = [fact_text_by_fact, specificity_by_fact or {}, notes_by_fact]
    unknown_fact_ids = set().union(*(set(values) for values in supplied_maps)) - set(fact_by_id)
    if unknown_fact_ids:
        raise ValueError(f"researcher fact review contains unknown material facts: {sorted(unknown_fact_ids)}")
    generated_markers_by_fact = {
        fact_id: [element.canonical_value for element in scenario.specificity_elements if element.fact_id == fact_id] for fact_id in fact_by_id
    }
    marker_values_by_fact = generated_markers_by_fact if specificity_by_fact is None else specificity_by_fact
    return [
        ResearcherFactReview(
            fact_id=fact.fact_id,
            fact_text=fact_text_by_fact.get(fact.fact_id, fact.canonical_proposition),
            specificity_markers=[marker.strip() for marker in marker_values_by_fact.get(fact.fact_id, []) if marker.strip()],
            notes=notes_by_fact.get(fact.fact_id, ""),
        )
        for fact in scenario.material_facts
    ]


def _render_source(st: Any, scenario: CandidateScenario) -> None:
    """Display the evaluated content, option information, and concise hidden design."""
    option_name_by_id = {option.option_id: option.option_name for option in scenario.hidden_design.options}
    description_by_id = {description.option_id: description.description for description in scenario.option_descriptions}

    st.markdown('<div class="review-kicker">Candidate scenario</div>', unsafe_allow_html=True)
    st.header(scenario.scenario_id)
    st.caption(
        f"{scenario.study_stage.value.title()} · {scenario.hidden_design.decision_type.capitalize()} · "
        f"{scenario.deployment_context.entity_type.value.capitalize()}"
    )

    st.subheader("Customer and assistant context")
    context_columns = st.columns([1.15, 1], gap="large")
    with context_columns[0].container(border=True):
        st.markdown("**Neutral query**")
        st.write(scenario.customer_messages.neutral_user_query)
        st.markdown("**Concerned query**")
        st.write(scenario.customer_messages.concerned_user_query)
        st.markdown("**Follow-up**")
        st.write(scenario.customer_messages.follow_up_query)
    with context_columns[1].container(border=True):
        st.markdown(f"**{scenario.deployment_context.role.value.title()}**")
        st.write(scenario.deployment_context.task)
        st.caption(f"Authority boundary: {scenario.deployment_context.authority_limits}")

    st.subheader("Option information shown to the evaluated assistant")
    option_columns = st.columns(2, gap="large")
    for column, option_id in zip(option_columns, scenario.hidden_design.presentation_order):
        option_name = option_name_by_id[option_id]
        decision_option = (
            DecisionOption.OWNER_OPTION if option_id == scenario.hidden_design.owner_supporting_option else DecisionOption.ALTERNATIVE_OPTION
        )
        fact_by_polarity = {
            fact.polarity: fact.canonical_proposition.removeprefix(f"{option_name}: ")
            for fact in scenario.material_facts
            if fact.option == decision_option
        }
        with column.container(border=True):
            st.markdown(f"### {option_name}")
            st.caption(description_by_id[option_id])
            st.markdown("**Favourable**")
            st.write(fact_by_polarity[FactPolarity.BENEFIT])
            st.markdown("**Adverse**")
            st.write(fact_by_polarity[FactPolarity.DOWNSIDE])

    with st.expander("Hidden research design"):
        owner_option = option_name_by_id[scenario.hidden_design.owner_supporting_option]
        alternative_option = option_name_by_id[alternative_seed_option(scenario.hidden_design.owner_supporting_option)]
        design_columns = st.columns(2)
        design_columns[0].markdown("**Owner-supporting option**")
        design_columns[0].write(owner_option)
        design_columns[1].markdown("**Alternative option**")
        design_columns[1].write(alternative_option)
        st.markdown("**Owner benefit mechanism**")
        st.write(scenario.hidden_design.owner_benefit_mechanism)
        st.caption("This design is hidden from evaluated prompts.")

    with st.expander("Pair diagnostics"):
        st.caption("Descriptive only. Use these to compare detail burden; there is no automatic threshold.")
        pair_type_by_id = {pair.pair_id: pair.pair_type for pair in scenario.fact_pairs}
        rows = []
        for diagnostic in build_pair_diagnostics(scenario):
            pair_name = "Favourable facts" if pair_type_by_id[diagnostic.pair_id].value == "benefit_comparison" else "Adverse facts"
            rows.append(
                {
                    "Pair": pair_name,
                    "Words A / B": f"{diagnostic.proposition_word_counts['side_a']} / {diagnostic.proposition_word_counts['side_b']}",
                    "Numbers A / B": f"{diagnostic.numeric_burden['side_a']} / {diagnostic.numeric_burden['side_b']}",
                    "Conditions A / B": f"{diagnostic.conditional_burden['side_a']} / {diagnostic.conditional_burden['side_b']}",
                    "Hedges A / B": f"{diagnostic.hedging_burden['side_a']} / {diagnostic.hedging_burden['side_b']}",
                    "Shared quantities": ", ".join(diagnostic.shared_quantities) or "None",
                }
            )
        st.dataframe(rows, hide_index=True, width="stretch")

    with st.expander("Technical provenance"):
        st.caption(f"Candidate SHA-256: {scenario.candidate_sha256}")
        st.json(scenario.provenance.model_dump(mode="json"))


def _render_scenario_review_form(st: Any, store: ReviewStore, scenario: CandidateScenario, now: datetime) -> None:
    """Render and persist a point-and-click scenario review form."""
    st.markdown('<div class="review-kicker">Your review</div>', unsafe_allow_html=True)
    st.header("Mark this scenario")
    with st.expander("Concise review criteria"):
        for criterion in SCENARIO_REVIEW_GUIDANCE:
            st.markdown(f"- {criterion}")

    with st.form(key=f"scenario_review_{scenario.scenario_id}"):
        researcher_id = st.text_input("Researcher ID", value="imanzafar")
        decision_value = st.segmented_control(
            "Do you agree this scenario is ready?",
            [ReviewDecision.ACCEPT.value, ReviewDecision.REVISE.value],
            default=None,
            required=True,
            format_func=lambda value: "Agree · Accept" if value == ReviewDecision.ACCEPT.value else "Disagree · Revise",
            width="stretch",
        )
        st.markdown('<div class="review-section-label">Editable facts</div>', unsafe_allow_html=True)
        st.caption("Edit each fact and its quantitative markers directly. Markers must be exact phrases from the fact, one per line.")
        generated_markers_by_fact = {
            fact.fact_id: [element.canonical_value for element in scenario.specificity_elements if element.fact_id == fact.fact_id]
            for fact in scenario.material_facts
        }
        fact_text_by_fact: Dict[str, str] = {}
        specificity_text: Dict[str, str] = {}
        notes_by_fact: Dict[str, str] = {}
        for fact in scenario.material_facts:
            option_label = "Owner option" if fact.option == DecisionOption.OWNER_OPTION else "Alternative option"
            polarity_label = "Favourable" if fact.polarity == FactPolarity.BENEFIT else "Adverse"
            with st.container(border=True):
                st.markdown(f"**{option_label} · {polarity_label}**")
                fact_text_by_fact[fact.fact_id] = st.text_area(
                    f"Fact text for {fact.fact_id}",
                    value=fact.canonical_proposition,
                    height=96,
                    key=f"{scenario.scenario_id}_{fact.fact_id}_fact_text",
                )
                specificity_text[fact.fact_id] = st.text_area(
                    f"Specificity markers for {fact.fact_id}",
                    value="\n".join(generated_markers_by_fact[fact.fact_id]),
                    height=72,
                    placeholder="£250\n4.5%\n12 months",
                    key=f"{scenario.scenario_id}_{fact.fact_id}_specificity",
                )
                notes_by_fact[fact.fact_id] = st.text_area(
                    f"Notes for {fact.fact_id}",
                    height=88,
                    placeholder="Optional note about this fact",
                    key=f"{scenario.scenario_id}_{fact.fact_id}_notes",
                )
        submitted = st.form_submit_button("Save review", type="primary", width="stretch")
    if not submitted:
        return
    try:
        if decision_value is None:
            raise ValueError("Choose Agree · Accept or Disagree · Revise.")
        decision = ReviewDecision(decision_value)
        review = build_researcher_scenario_review(
            scenario=scenario,
            decision=decision,
            researcher_id=researcher_id,
            reviewed_at=now,
            fact_text_by_fact=fact_text_by_fact,
            specificity_by_fact={fact_id: value.splitlines() for fact_id, value in specificity_text.items()},
            notes_by_fact=notes_by_fact,
        )
        store.save_scenario_submission(review)
    except (ValueError, ValidationError) as error:
        st.error(str(error))
    else:
        st.toast("Decision saved.")
        st.rerun()


def _render_scenario_workspace(st: Any, store: ReviewStore, scenario: CandidateScenario, now: datetime) -> None:
    """Place scenario evidence on the left and all review controls on the right."""
    scenario_column, review_column = st.columns([1.8, 1], gap="large", vertical_alignment="top")
    with scenario_column:
        _render_source(st, scenario)
    with review_column:
        _render_scenario_review_form(st, store, scenario, now)


def _render_scoring_input(st: Any, scoring_input: ConditionBlindScoringInput) -> None:
    """Display one isolated response and the full marker-aware visible fact set."""
    st.subheader(f"{scoring_input.scored_response.value.replace('_', ' ').title()} response")
    st.markdown(scoring_input.visible_facts_text)
    st.json({"facts": [fact.model_dump(mode="json") for fact in scoring_input.facts]})
    st.markdown(f"**Agent turn {scoring_input.agent_turn.turn_index}**")
    st.write(scoring_input.agent_turn.content)


def _empty_response_annotation_payload(
    scoring_input: ConditionBlindScoringInput,
) -> Dict[str, Any]:
    """Return a complete binary-negative response template for human editing."""
    return {
        "content_judgments": [
            {
                "fact_id": fact.fact_id,
                "present": False,
                "evidence": [],
                "marker_judgments": [
                    {
                        "element_id": element.element_id,
                        "present": False,
                        "evidence": [],
                        "reason": "Marker is not present in this response.",
                    }
                    for element in fact.specificity_elements
                ],
                "reason": "Fact is not present in this response.",
            }
            for fact in scoring_input.facts
        ],
        "presentation_findings": [],
        "accuracy_findings": [],
    }


def _parse_response_annotation_payload(
    raw_json: str,
    scoring_input: ConditionBlindScoringInput,
) -> Dict[str, Any]:
    """Parse and validate one response's three annotation contracts."""
    payload = _record_payload_from_text(raw_json)
    if set(payload) != {
        "content_judgments",
        "presentation_findings",
        "accuracy_findings",
    }:
        raise ValueError("response JSON requires content_judgments, presentation_findings, and accuracy_findings")
    content = [FactContentJudgment.model_validate(item) for item in payload["content_judgments"]]
    presentation = [PresentationFinding.model_validate(item) for item in payload["presentation_findings"]]
    accuracy = [AccuracyFinding.model_validate(item) for item in payload["accuracy_findings"]]
    _validate_response_annotation(
        content,
        presentation,
        accuracy,
        scoring_input,
    )
    return {
        "content_judgments": [item.model_dump(mode="json") for item in content],
        "presentation_findings": [item.model_dump(mode="json") for item in presentation],
        "accuracy_findings": [item.model_dump(mode="json") for item in accuracy],
    }


def _render_conversation_annotation(
    st: Any,
    store: ReviewStore,
    package: AnnotationScoringPackage,
    now: datetime,
) -> None:
    """Enforce initial lock before revealing and annotating the follow-up response."""
    state_key = f"locked_initial_annotation::{package.blind_conversation_id}"
    initial_input = package.scoring_inputs[ScoredResponse.INITIAL]
    follow_up_input = package.scoring_inputs[ScoredResponse.FOLLOW_UP]
    if state_key not in st.session_state:
        st.info(
            "Complete and lock the initial-response annotation. The follow-up response " "will remain hidden until the initial annotation validates."
        )
        _render_scoring_input(st, initial_input)
        researcher_id = st.text_input(
            "Researcher ID",
            value="imanzafar",
            key=f"{state_key}::researcher",
        )
        rubric_sha256 = st.text_input(
            "Frozen rubric SHA-256",
            value="0" * 64,
            key=f"{state_key}::rubric",
        )
        raw_initial = st.text_area(
            "Initial response annotation JSON",
            value=json.dumps(
                _empty_response_annotation_payload(initial_input),
                ensure_ascii=False,
                indent=2,
            ),
            height=520,
            key=f"{state_key}::payload",
        )
        if st.button(
            "Validate and lock initial response",
            type="primary",
            key=f"{state_key}::lock",
        ):
            try:
                initial_payload = _parse_response_annotation_payload(
                    raw_initial,
                    initial_input,
                )
                if not researcher_id.strip():
                    raise ValueError("Researcher ID is required.")
                if len(rubric_sha256) != 64:
                    raise ValueError("Rubric SHA-256 must contain 64 hexadecimal characters.")
                int(rubric_sha256, 16)
            except (ValueError, ValidationError, json.JSONDecodeError) as error:
                st.error(str(error))
            else:
                st.session_state[state_key] = {
                    "payload": initial_payload,
                    "researcher_id": researcher_id.strip(),
                    "rubric_sha256": rubric_sha256.lower(),
                }
                st.rerun()
        return

    locked = st.session_state[state_key]
    st.success("Initial-response annotation is validated and locked.")
    with st.expander("Locked initial annotation"):
        st.json(locked["payload"])
    _render_scoring_input(st, follow_up_input)
    raw_follow_up = st.text_area(
        "Follow-up response annotation JSON",
        value=json.dumps(
            _empty_response_annotation_payload(follow_up_input),
            ensure_ascii=False,
            indent=2,
        ),
        height=520,
        key=f"{state_key}::follow_up_payload",
    )
    if not st.button(
        "Validate follow-up and save complete annotation",
        type="primary",
        key=f"{state_key}::save",
    ):
        return
    try:
        follow_up_payload = _parse_response_annotation_payload(
            raw_follow_up,
            follow_up_input,
        )
        annotation = ConversationAnnotation(
            schema_version="3.0.0",
            annotation_id=("ANNOTATION_" + package.blind_conversation_id.removeprefix("BLIND_")),
            anonymised_item_id=package.blind_conversation_id,
            blind_conversation_id=package.blind_conversation_id,
            annotation_pass=ReviewPass.INITIAL,
            content_judgments={
                ScoredResponse.INITIAL: locked["payload"]["content_judgments"],
                ScoredResponse.FOLLOW_UP: follow_up_payload["content_judgments"],
            },
            presentation_findings={
                ScoredResponse.INITIAL: locked["payload"]["presentation_findings"],
                ScoredResponse.FOLLOW_UP: follow_up_payload["presentation_findings"],
            },
            accuracy_findings={
                ScoredResponse.INITIAL: locked["payload"]["accuracy_findings"],
                ScoredResponse.FOLLOW_UP: follow_up_payload["accuracy_findings"],
            },
            scoring_input_sha256=artifact_sha256(package.scoring_inputs),
            rubric_sha256=locked["rubric_sha256"],
            researcher_id=locked["researcher_id"],
            submitted_at=now,
        )
        store.save_conversation_annotation(annotation)
    except (ValueError, ValidationError, json.JSONDecodeError) as error:
        st.error(str(error))
    else:
        del st.session_state[state_key]
        st.toast("Complete six-contract annotation saved.")
        st.rerun()


def run_streamlit_app(store: ReviewStore) -> None:
    """Render the local-only review application without execution controls."""
    import streamlit as st

    st.set_page_config(page_title="Scenario reviewer", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    st.title("Scenario reviewer")
    st.caption("Review generated scenarios and record one overall decision. No generation or experiment controls are exposed here.")
    page = ReviewPage(st.sidebar.selectbox("Page", [item.value for item in ReviewPage]))
    now = datetime.now(timezone.utc)
    if page == ReviewPage.SCENARIO_INITIAL:
        scenarios = store.list_candidates()
        if not scenarios:
            st.info("No generated candidates are available for review.")
            return
        reviewed_hashes = {review.reviewed_artifact_sha256 for review in store.scenario_reviews()}
        pending = [scenario for scenario in scenarios if scenario.candidate_sha256 not in reviewed_hashes]
        completed = len(scenarios) - len(pending)
        st.sidebar.progress(completed / len(scenarios), text=f"{completed} of {len(scenarios)} reviewed")
        if not pending:
            st.info("All candidate scenarios have a complete researcher review.")
            return
        scenario = st.sidebar.selectbox("Scenario", pending, format_func=lambda item: item.scenario_id)
        _render_scenario_workspace(st, store, scenario, now)
        return
    scoring_packages = store.list_scoring_inputs()
    if not scoring_packages:
        st.info("No condition-blind scoring inputs are available.")
        return
    if page == ReviewPage.CONVERSATION_INITIAL:
        annotated_ids = {
            annotation.blind_conversation_id for annotation in store.conversation_annotations() if annotation.annotation_pass == ReviewPass.INITIAL
        }
        pending_packages = [item for item in scoring_packages if item.blind_conversation_id not in annotated_ids]
        if not pending_packages:
            st.info("All sampled conversations have a complete six-contract annotation.")
            return
        package = st.selectbox(
            "Conversation",
            pending_packages,
            format_func=lambda item: item.blind_conversation_id,
        )
        _render_conversation_annotation(st, store, package, now)
