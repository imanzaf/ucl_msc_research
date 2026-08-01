"""Local-only Streamlit review and annotation interface with atomic JSONL storage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ReviewPass
from src.data_models.scenarios import (
    AcceptedScenario,
    CandidateScenario,
    CustomerMessages,
    DeploymentContext,
    FactPolarity,
    ScenarioFactInformation,
    ScenarioHiddenDesign,
    ScenarioOptionDefinition,
    ScenarioOptionInformation,
    SeedOptionId,
)
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
from src.scenarios.candidate_compatibility import read_candidate_scenario
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.revisions import editable_candidate_content, save_candidate_revision
from src.scenarios.run_resolution import current_scenario_artifacts
from src.storage import append_model_jsonl_validated, read_model_json, read_model_jsonl


class ReviewPage(str, Enum):
    """Identify the review workflows exposed by the local application."""

    SCENARIO_EDITOR = "Scenario editor"
    CONVERSATION_INITIAL = "Conversation annotation"


SCENARIO_SELECTION_KEY = "scenario_review_selected_id"
SCENARIO_NAVIGATION_TARGET_KEY = "scenario_review_navigation_target"


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
        max-width: 1120px;
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
    """Read candidates, save versions, publish selections, and persist annotations."""

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
    def conversation_annotations_path(self) -> Path:
        """Return the append-only conversation-annotation JSONL path."""
        return self.output_root / "conversation_annotations.jsonl"

    def list_candidates(self) -> List[CandidateScenario]:
        """Load the current hash-valid candidate version for every scenario."""
        if (self.candidate_root / "run_config.json").is_file():
            candidates = [artifact.candidate for _, artifact in sorted(current_scenario_artifacts(self.candidate_root).items())]
        else:
            candidates = [read_candidate_scenario(path) for path in sorted(self.candidate_root.glob("*/candidate.json"))]
        for candidate in candidates:
            validate_candidate_scenario_hash(candidate)
        return candidates

    def list_scoring_inputs(self) -> List[AnnotationScoringPackage]:
        """Load paired response-isolated annotation packages."""
        return [read_model_json(path, AnnotationScoringPackage) for path in sorted(self.scoring_input_root.glob("*.json"))]

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

    def save_scenario_revision(
        self,
        scenario: CandidateScenario,
        edited_content: Dict[str, Any],
        edited_by: str,
        notes: str,
    ) -> CandidateScenario:
        """Save one edited candidate as the next version in the selected run."""
        if not (self.candidate_root / "run_config.json").is_file():
            raise ValueError("scenario editing requires a named run root")
        current = self._candidate(scenario.scenario_id)
        if current.candidate_sha256 != scenario.candidate_sha256:
            raise ValueError("this scenario changed after the page loaded; refresh before saving")
        revised, _, _ = save_candidate_revision(
            run_root=self.candidate_root,
            parent=current,
            edited_content=edited_content,
            edited_by=edited_by,
            notes=notes,
        )
        return revised

    def publish_scenarios(self, scenario_ids: List[str], published_by: str) -> List[AcceptedScenario]:
        """Publish selected current versions directly from the named run."""
        if not (self.candidate_root / "run_config.json").is_file():
            raise ValueError("scenario publication requires a named run root")
        from src.cli.commands.scenarios.publish import publish_selected_candidates

        published, _ = publish_selected_candidates(self.candidate_root, scenario_ids, published_by)
        return published


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
        expected_element_ids = {marker.element_id for marker in fact.specificity_markers}
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
    """Validate all three human outputs for both isolated responses."""
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


def scenario_navigation_targets(scenario_ids: List[str], current_scenario_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Return the previous and next scenario IDs around the current selection."""
    if current_scenario_id not in scenario_ids:
        raise ValueError(f"current scenario is not available for review: {current_scenario_id}")
    current_index = scenario_ids.index(current_scenario_id)
    previous_scenario_id = scenario_ids[current_index - 1] if current_index > 0 else None
    next_scenario_id = scenario_ids[current_index + 1] if current_index < len(scenario_ids) - 1 else None
    return previous_scenario_id, next_scenario_id


def _queue_scenario_navigation(st: Any, scenario_id: str) -> None:
    """Queue a scenario selection for the next top-to-bottom rerun."""
    st.session_state[SCENARIO_NAVIGATION_TARGET_KEY] = scenario_id


def _select_scenario(st: Any, scenarios: List[CandidateScenario]) -> CandidateScenario:
    """Resolve the sidebar selection while honouring queued navigation."""
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    scenario_ids = list(scenario_by_id)
    target_scenario_id = st.session_state.pop(SCENARIO_NAVIGATION_TARGET_KEY, None)
    selected_scenario_id = target_scenario_id or st.session_state.get(SCENARIO_SELECTION_KEY)
    if selected_scenario_id not in scenario_by_id:
        selected_scenario_id = scenario_ids[0]
    if st.session_state.get(SCENARIO_SELECTION_KEY) != selected_scenario_id:
        st.session_state[SCENARIO_SELECTION_KEY] = selected_scenario_id
    selected_scenario_id = st.sidebar.selectbox(
        "Scenario",
        scenario_ids,
        key=SCENARIO_SELECTION_KEY,
        persist_state="session",
    )
    return scenario_by_id[selected_scenario_id]


def _render_scenario_navigation(st: Any, scenario_ids: List[str], current_scenario_id: str, location: str) -> None:
    """Render previous and next controls for one position in the review page."""
    previous_scenario_id, next_scenario_id = scenario_navigation_targets(scenario_ids, current_scenario_id)
    current_index = scenario_ids.index(current_scenario_id)
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.button(
            "Previous scenario",
            icon=":material/arrow_back:",
            disabled=previous_scenario_id is None,
            on_click=_queue_scenario_navigation,
            args=(st, previous_scenario_id or current_scenario_id),
            key=f"scenario_previous_{location}_{current_scenario_id}",
        )
        st.caption(f"Scenario {current_index + 1} of {len(scenario_ids)}")
        st.button(
            "Next scenario",
            icon=":material/arrow_forward:",
            icon_position="right",
            disabled=next_scenario_id is None,
            on_click=_queue_scenario_navigation,
            args=(st, next_scenario_id or current_scenario_id),
            key=f"scenario_next_{location}_{current_scenario_id}",
        )


def _render_scenario_overview(st: Any, scenario: CandidateScenario) -> None:
    """Display the task, user queries, and option descriptions once."""
    option_name_by_id = {option.option_id: option.option_name for option in scenario.hidden_design.options}
    description_by_id = {description.option_id: description.description for description in scenario.option_descriptions}

    st.markdown('<div class="review-kicker">Candidate scenario</div>', unsafe_allow_html=True)
    st.header(scenario.scenario_id)
    st.caption(
        f"{scenario.study_stage.value.title()} · {scenario.hidden_design.decision_type.capitalize()} · "
        f"{scenario.deployment_context.entity_type.value.capitalize()}"
    )

    st.subheader("Agent task")
    with st.container(border=True):
        st.markdown(f"**{scenario.deployment_context.role.value.replace('_', ' ').capitalize()}**")
        st.write(scenario.deployment_context.task)
        st.caption(f"Authority boundary: {scenario.deployment_context.authority_limits}")

    st.subheader("User queries")
    with st.container(border=True):
        st.markdown("**Neutral query**")
        st.write(scenario.customer_messages.neutral_user_query)
        st.markdown("**Concerned query**")
        st.write(scenario.customer_messages.concerned_user_query)
        st.markdown("**Follow-up**")
        st.write(scenario.customer_messages.follow_up_query)

    st.subheader("Option descriptions")
    for option_id in scenario.hidden_design.presentation_order:
        option_name = option_name_by_id[option_id]
        with st.container(border=True):
            st.markdown(f"**{option_name}**")
            st.write(description_by_id[option_id])


def _render_research_context(st: Any, scenario: CandidateScenario) -> None:
    """Display compact research context and optional diagnostics before editing."""
    option_name_by_id = {option.option_id: option.option_name for option in scenario.hidden_design.options}

    st.subheader("Research context")
    with st.container(border=True):
        owner_option = option_name_by_id[scenario.hidden_design.owner_supporting_option]
        st.markdown("**Owner-supporting option**")
        st.write(owner_option)
        st.markdown("**Owner benefit mechanism**")
        st.write(scenario.hidden_design.owner_benefit_mechanism)
        st.caption("This design is hidden from evaluated prompts.")

    with st.expander("Review criteria and pair diagnostics", icon=":material/checklist:"):
        for criterion in SCENARIO_REVIEW_GUIDANCE:
            st.markdown(f"- {criterion}")
        st.caption("Descriptive only. Use these to compare detail burden; there is no automatic threshold.")
        polarity_by_pair_id = {fact.pair_id: fact.polarity for fact in scenario.material_facts}
        rows = []
        for diagnostic in build_pair_diagnostics(scenario):
            pair_name = "Favourable facts" if polarity_by_pair_id[diagnostic.pair_id] == FactPolarity.BENEFIT else "Adverse facts"
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


def build_edited_candidate_content(
    scenario: CandidateScenario,
    deployment_task: str,
    authority_limits: str,
    neutral_query: str,
    concerned_query: str,
    follow_up_query: str,
    decision_type: str,
    owner_benefit_mechanism: str,
    option_names: Dict[SeedOptionId, str],
    option_values: Dict[SeedOptionId, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build all editable candidate sections from the structured editor values."""
    deployment_context = DeploymentContext(
        role=scenario.deployment_context.role,
        entity_type=scenario.deployment_context.entity_type,
        task=deployment_task,
        authority_limits=authority_limits,
    )
    customer_messages = CustomerMessages(
        neutral_user_query=neutral_query,
        concerned_user_query=concerned_query,
        follow_up_query=follow_up_query,
    )
    hidden_design = ScenarioHiddenDesign(
        decision_type=decision_type,
        options=[ScenarioOptionDefinition(option_id=option_id, option_name=option_names[option_id]) for option_id in SeedOptionId],
        owner_supporting_option=scenario.hidden_design.owner_supporting_option,
        owner_benefit_mechanism=owner_benefit_mechanism,
        presentation_order=scenario.hidden_design.presentation_order,
        comparison_scope=scenario.hidden_design.comparison_scope,
        external_option_id=scenario.hidden_design.external_option_id,
    )
    options = [
        ScenarioOptionInformation(
            option_id=option_id,
            description=str(option_values[option_id]["description"]),
            favourable_fact=ScenarioFactInformation(
                fact_text=str(option_values[option_id]["favourable_fact"]),
                specificity_markers=list(option_values[option_id]["favourable_markers"]),
            ),
            adverse_fact=ScenarioFactInformation(
                fact_text=str(option_values[option_id]["adverse_fact"]),
                specificity_markers=list(option_values[option_id]["adverse_markers"]),
            ),
        )
        for option_id in scenario.hidden_design.presentation_order
    ]
    return {
        "deployment_context": deployment_context.model_dump(mode="python"),
        "customer_messages": customer_messages.model_dump(mode="python"),
        "hidden_design": hidden_design.model_dump(mode="python"),
        "options": [option.model_dump(mode="python") for option in options],
    }


def _render_scenario_editor_form(
    st: Any,
    store: ReviewStore,
    scenario: CandidateScenario,
    scenario_ids: List[str],
) -> None:
    """Render editable scenario fields with direct save and publish actions."""
    option_name_by_id = {option.option_id: option.option_name for option in scenario.hidden_design.options}
    option_by_id = {option.option_id: option for option in scenario.options}
    version_key = scenario.candidate_sha256[:12]

    st.markdown('<div class="review-kicker">Scenario editor</div>', unsafe_allow_html=True)
    st.header("Edit this version")
    st.caption("Change any wording you need. Saving creates a new version; publishing is optional and applies only to this scenario.")
    with st.form(key=f"scenario_editor_{scenario.scenario_id}_{version_key}"):
        st.subheader("Task and customer messages")
        deployment_task = st.text_area("Assistant task", value=scenario.deployment_context.task, height=88)
        authority_limits = st.text_area("Authority limits", value=scenario.deployment_context.authority_limits, height=88)
        neutral_query = st.text_area("Neutral customer query", value=scenario.customer_messages.neutral_user_query, height=88)
        concerned_query = st.text_area("Concerned customer query", value=scenario.customer_messages.concerned_user_query, height=88)
        follow_up_query = st.text_area("Follow-up query", value=scenario.customer_messages.follow_up_query, height=72)

        st.subheader("Research design")
        decision_type = st.text_input("Decision type", value=scenario.hidden_design.decision_type)
        owner_benefit_mechanism = st.text_area(
            "Owner benefit mechanism",
            value=scenario.hidden_design.owner_benefit_mechanism,
            height=88,
        )

        option_names: Dict[SeedOptionId, str] = {}
        option_values: Dict[SeedOptionId, Dict[str, Any]] = {}
        st.subheader("Options and facts")
        st.caption("Specificity markers are optional; enter exact quantitative phrases from the fact, one per line.")
        for option_id in scenario.hidden_design.presentation_order:
            option = option_by_id[option_id]
            with st.container(border=True):
                option_names[option_id] = st.text_input(
                    f"{option_id.value} name",
                    value=option_name_by_id[option_id],
                )
                description = st.text_area("Neutral description", value=option.description, height=88, key=f"{version_key}_{option_id}_description")
                favourable_fact = st.text_area(
                    "Favourable fact",
                    value=option.favourable_fact.fact_text,
                    height=96,
                    key=f"{version_key}_{option_id}_favourable",
                )
                favourable_markers = st.text_area(
                    "Favourable specificity markers",
                    value="\n".join(option.favourable_fact.specificity_markers),
                    height=72,
                    key=f"{version_key}_{option_id}_favourable_markers",
                )
                adverse_fact = st.text_area(
                    "Adverse fact",
                    value=option.adverse_fact.fact_text,
                    height=96,
                    key=f"{version_key}_{option_id}_adverse",
                )
                adverse_markers = st.text_area(
                    "Adverse specificity markers",
                    value="\n".join(option.adverse_fact.specificity_markers),
                    height=72,
                    key=f"{version_key}_{option_id}_adverse_markers",
                )
                option_values[option_id] = {
                    "description": description,
                    "favourable_fact": favourable_fact,
                    "favourable_markers": [value.strip() for value in favourable_markers.splitlines() if value.strip()],
                    "adverse_fact": adverse_fact,
                    "adverse_markers": [value.strip() for value in adverse_markers.splitlines() if value.strip()],
                }

        st.subheader("Save or publish")
        researcher_id = st.text_input("Researcher ID", value="imanzafar")
        revision_notes = st.text_area("Revision notes", placeholder="Optional summary of your changes", height=72)
        with st.container(horizontal=True, horizontal_alignment="right"):
            save_submitted = st.form_submit_button("Save revised version", icon=":material/save:")
            publish_submitted = st.form_submit_button("Publish this version", type="primary", icon=":material/publish:")
    if not save_submitted and not publish_submitted:
        return
    try:
        edited_content = build_edited_candidate_content(
            scenario=scenario,
            deployment_task=deployment_task,
            authority_limits=authority_limits,
            neutral_query=neutral_query,
            concerned_query=concerned_query,
            follow_up_query=follow_up_query,
            decision_type=decision_type,
            owner_benefit_mechanism=owner_benefit_mechanism,
            option_names=option_names,
            option_values=option_values,
        )
        changed = edited_content != editable_candidate_content(scenario)
        saved_scenario = scenario
        if changed:
            saved_scenario = store.save_scenario_revision(
                scenario=scenario,
                edited_content=edited_content,
                edited_by=researcher_id,
                notes=revision_notes,
            )
        elif save_submitted:
            raise ValueError("No scenario fields changed, so there is no new version to save.")
        if publish_submitted:
            store.publish_scenarios([saved_scenario.scenario_id], researcher_id)
    except (ValueError, ValidationError) as error:
        st.error(str(error))
    else:
        if publish_submitted:
            _, next_scenario_id = scenario_navigation_targets(scenario_ids, scenario.scenario_id)
            if next_scenario_id is not None:
                st.session_state[SCENARIO_NAVIGATION_TARGET_KEY] = next_scenario_id
            st.toast("Current scenario version published.")
        else:
            st.toast("Revised scenario version saved.")
        st.rerun()


def _render_scenario_workspace(
    st: Any,
    store: ReviewStore,
    scenario: CandidateScenario,
    scenarios: List[CandidateScenario],
) -> None:
    """Render one scenario from overview through editing and publication."""
    scenario_ids = [item.scenario_id for item in scenarios]
    _render_scenario_navigation(st, scenario_ids, scenario.scenario_id, "top")
    _render_scenario_overview(st, scenario)
    _render_research_context(st, scenario)
    _render_scenario_editor_form(st, store, scenario, scenario_ids)
    _render_scenario_navigation(st, scenario_ids, scenario.scenario_id, "bottom")


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
                    for element in fact.specificity_markers
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

    st.set_page_config(page_title="Scenario editor", layout="wide")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    st.title("Scenario editor")
    st.caption("Edit generated scenarios, save new versions, and publish only the versions you choose.")
    page = ReviewPage(st.sidebar.selectbox("Page", [item.value for item in ReviewPage]))
    now = datetime.now(timezone.utc)
    if page == ReviewPage.SCENARIO_EDITOR:
        scenarios = store.list_candidates()
        if not scenarios:
            st.info("No generated candidates are available to edit.")
            return
        scenario = _select_scenario(st, scenarios)
        _render_scenario_workspace(st, store, scenario, scenarios)
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
