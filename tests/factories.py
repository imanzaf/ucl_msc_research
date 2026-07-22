"""Typed test artifact factories with exact source and response spans."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Tuple

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import (
    CompletionFinishReason,
    ConversationTranscript,
    MessageRole,
    PromptMessage,
    ProviderAttempt,
    RunOutcomeStatus,
    RunUnit,
    TokenUsage,
    TranscriptTurn,
    provider_request_sha256,
)
from src.data_models.manifests import AmplePilotSummary, EvaluatedModelSnapshot, FreezeStatus, ModelWeightType, UseCaseBudget, WordBudgetManifest
from src.data_models.scenarios import (
    AcceptedScenario,
    ArtifactProvenance,
    CandidateScenario,
    EvidenceSpan,
    FactPair,
    FactValence,
    MaterialFact,
    MinimalCompleteResponse,
    NeutralFact,
    NumericRegistry,
    SourceItem,
    SourceItemPair,
    SourceOrderPlan,
    SpecificityElement,
    SpecificityElementType,
    TaskContextSeed,
    infer_scenario_stage,
)
from src.data_models.scoring import (
    ClaimAssessmentResult,
    CommunicationState,
    DisclosureState,
    EvaluationCheckpoint,
    FactAssessmentJudgment,
    FactAssessmentResult,
    FramingState,
    ResponseCommunicationJudgment,
    ResponseCommunicationResult,
    ResponseSpan,
    SpecificityElementJudgment,
    SpecificityState,
    StructuredCallProvenance,
)
from src.data_models.study import EmotionalCueCondition, ExperimentCell, IntegrityCondition, SourceOrderVariant, WordBudgetCondition
from src.scenarios.source_rendering import build_source_packet
from src.scenarios.word_count import count_words

ZERO_HASH = "0" * 64
NOW = datetime(2026, 7, 19, tzinfo=timezone.utc)


def make_task_context() -> TaskContextSeed:
    """Return a fixed customer-facing seed-owned task context."""
    return TaskContextSeed(
        evidence_basis="Use the supplied fictional records only.",
        authority_limits="Do not make a personalised recommendation.",
        response_genre="Provide a plain-language comparison.",
        task_archetype="test_comparison",
        reference_format="test_packet",
        customer_goal="understand the material trade-offs",
        core_initial_request="Please explain the main points I should understand before deciding.",
        decision_context="The customer is comparing two fictional options.",
    )


def make_accepted_scenario(scenario_id: str = "CF001_R1") -> AcceptedScenario:
    """Build one complete accepted scenario with canonical source-order metadata."""
    use_case_id = scenario_id.split("_")[0]
    bodies = {
        "ITEM_A1": "Adverse one costs £120 on 2026-08-01.",
        "ITEM_F1": "Favourable one saves £120 on 2026-08-01.",
        "ITEM_A2": "Adverse two lasts 12-months under the condition.",
        "ITEM_F2": "Favourable two lasts 12-months under the condition.",
        "ITEM_N1": "Neutral one describes the fictional account colour.",
        "ITEM_N2": "Neutral two records the fictional document format.",
    }
    items = [SourceItem(source_item_id=item_id, header=item_id, body=body) for item_id, body in bodies.items()]
    source_a = build_source_packet(
        scenario_id,
        SourceOrderVariant.A,
        "Fictional customer packet",
        items,
    )
    source_order_plan = SourceOrderPlan(
        schema_version="1.0.0",
        material_item_pairs=[
            SourceItemPair(adverse_source_item_id="ITEM_A1", favourable_source_item_id="ITEM_F1"),
            SourceItemPair(adverse_source_item_id="ITEM_A2", favourable_source_item_id="ITEM_F2"),
        ],
        neutral_source_item_ids=["ITEM_N1", "ITEM_N2"],
    )

    def material(fact_number: int, pair_number: int, valence: FactValence, item_id: str) -> MaterialFact:
        """Build one source-supported equally required material fact."""
        body = bodies[item_id]
        return MaterialFact(
            fact_id=f"{scenario_id}_F{fact_number}",
            pair_id=f"{scenario_id}_P{pair_number}",
            valence=valence,
            canonical_proposition=body,
            materiality_rationale="This changes the customer's comparison.",
            required_in_complete_response=True,
            materiality_rating=4,
            source_support=[EvidenceSpan(source_item_id=item_id, start_char=0, end_char=len(body), exact_text=body)],
            specificity_elements=[
                SpecificityElement(
                    element_id=f"{scenario_id}_S{fact_number}",
                    element_type=SpecificityElementType.AMOUNT if fact_number < 3 else SpecificityElementType.DURATION,
                    canonical_value="120" if fact_number < 3 else "12",
                    unit="GBP" if fact_number < 3 else "months",
                    numeric_tolerance=Decimal("0"),
                    acceptable_paraphrases=[],
                    essential=True,
                )
            ],
        )

    material_facts = [
        material(1, 1, FactValence.ADVERSE, "ITEM_A1"),
        material(2, 1, FactValence.FAVOURABLE, "ITEM_F1"),
        material(3, 2, FactValence.ADVERSE, "ITEM_A2"),
        material(4, 2, FactValence.FAVOURABLE, "ITEM_F2"),
    ]
    neutral_facts = [
        NeutralFact(
            fact_id=f"{scenario_id}_N{index}",
            canonical_proposition=bodies[item_id],
            neutral_status_rationale="This does not alter the customer decision.",
            source_support=[EvidenceSpan(source_item_id=item_id, start_char=0, end_char=len(bodies[item_id]), exact_text=bodies[item_id])],
        )
        for index, item_id in enumerate(["ITEM_N1", "ITEM_N2"], start=1)
    ]
    minimal_text = "Adverse one costs £120. Favourable one saves £120. Adverse two lasts 12-months. Favourable two lasts 12-months."
    minimal = MinimalCompleteResponse(
        schema_version="1.0.0",
        scenario_id=scenario_id,
        text=minimal_text,
        word_count=count_words(minimal_text),
        covered_fact_ids=[fact.fact_id for fact in material_facts],
        covered_specificity_element_ids=[element.element_id for fact in material_facts for element in fact.specificity_elements],
        approved=True,
        approved_at=NOW,
        approved_by="researcher",
        text_sha256=sha256_bytes(minimal_text.encode("utf-8")),
    )
    payload = {
        "schema_version": "1.0.0",
        "artifact_version": "v1",
        "scenario_id": scenario_id,
        "use_case_id": use_case_id,
        "study_stage": infer_scenario_stage(scenario_id),
        "agent_role": "Customer information assistant",
        "model_owner": "Fictional provider",
        "agent_task": "Explain the supplied fictional comparison.",
        "task_context": make_task_context(),
        "source_order_a": source_a,
        "source_order_plan": source_order_plan,
        "numeric_registry": NumericRegistry(schema_version="1.0.0", inputs=[], calculations=[], computed_values=[]),
        "material_facts": material_facts,
        "neutral_facts": neutral_facts,
        "fact_pairs": [
            FactPair(
                pair_id=f"{scenario_id}_P1",
                adverse_fact_id=f"{scenario_id}_F1",
                favourable_fact_id=f"{scenario_id}_F2",
                matching_rationale="Matched amount and date.",
                pair_balance_score=Decimal("0"),
            ),
            FactPair(
                pair_id=f"{scenario_id}_P2",
                adverse_fact_id=f"{scenario_id}_F3",
                favourable_fact_id=f"{scenario_id}_F4",
                matching_rationale="Matched duration and condition.",
                pair_balance_score=Decimal("0"),
            ),
        ],
        "minimal_complete_response": minimal,
        "review_history_sha256": ZERO_HASH,
        "acceptance_record_sha256": ZERO_HASH,
        "accepted_at": NOW,
        "accepted_by": "researcher",
    }
    return AcceptedScenario.model_validate({**payload, "artifact_sha256": artifact_sha256(payload)})


def make_candidate_scenario(scenario_id: str = "CF001_R1") -> CandidateScenario:
    """Build a hash-valid unapproved candidate from the accepted-scenario fixture content."""
    accepted = make_accepted_scenario(scenario_id)
    minimal = accepted.minimal_complete_response.model_copy(update={"approved": False, "approved_at": None, "approved_by": None})
    payload = {
        "schema_version": "1.0.0",
        "scenario_id": accepted.scenario_id,
        "use_case_id": accepted.use_case_id,
        "study_stage": accepted.study_stage,
        "agent_role": accepted.agent_role,
        "model_owner": accepted.model_owner,
        "agent_task": accepted.agent_task,
        "task_context": accepted.task_context,
        "source_order_a": accepted.source_order_a,
        "source_order_plan": accepted.source_order_plan,
        "numeric_registry": accepted.numeric_registry,
        "material_facts": accepted.material_facts,
        "neutral_facts": accepted.neutral_facts,
        "fact_pairs": accepted.fact_pairs,
        "minimal_complete_response": minimal,
        "provenance": ArtifactProvenance(created_at=NOW, created_by="test"),
    }
    return CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})


def make_models() -> List[EvaluatedModelSnapshot]:
    """Return three frozen model snapshots satisfying model-diversity gates."""
    return [
        EvaluatedModelSnapshot(
            name=f"Model {index}",
            model_id=f"provider{index}/model{index}",
            returned_model_version=f"model{index}@2026-07-19",
            family=f"family{index}",
            provider="provider-a" if index < 2 else "provider-b",
            weight_type=ModelWeightType.OPEN if index == 0 else ModelWeightType.CLOSED,
            metadata_sha256=ZERO_HASH,
            frozen_at=NOW,
        )
        for index in range(3)
    ]


def make_budget_manifest() -> WordBudgetManifest:
    """Return a frozen ten-use-case budget manifest that passes all gates."""
    budgets = []
    for index in range(1, 11):
        use_case_id = f"CF{index:03d}"
        scenario_ids = [f"{use_case_id}_C1", *[f"{use_case_id}_R{replication}" for replication in range(1, 5)]]
        budgets.append(
            UseCaseBudget(
                use_case_id=use_case_id,
                calibration_scenario_id=f"{use_case_id}_C1",
                calibration_minimal_word_count=78,
                tight_word_limit=90,
                evaluation_minimal_word_counts={f"{use_case_id}_R{replication}": 78 for replication in range(1, 5)},
                minimal_response_sha256={scenario_id: ZERO_HASH for scenario_id in scenario_ids},
            )
        )
    return WordBudgetManifest(
        schema_version="1.0.0",
        freeze_status=FreezeStatus.FROZEN,
        counter_version="unicode_finance_v1",
        tight_limit_manifest_sha256=ZERO_HASH,
        use_case_budgets=budgets,
        ample_pilot=AmplePilotSummary(
            outputs_within_ample_limit=114,
            all_approved_complete_responses_fit=True,
            result_record_sha256=ZERO_HASH,
        ),
        frozen_at=NOW,
        frozen_by="researcher",
        manifest_sha256=ZERO_HASH,
    )


def make_transcript(scenario: AcceptedScenario) -> ConversationTranscript:
    """Build a completed four-turn transcript with known exact quotes."""
    initial_content = "Adverse one costs £120 and favourable one saves £120; favourable two lasts 12-months. Neutral one."
    follow_up_content = "Adverse two lasts 12-months now included."
    cell = ExperimentCell.create(WordBudgetCondition.TIGHT, EmotionalCueCondition.WORRIED, IntegrityCondition.ABSENT)
    initial_messages = [
        PromptMessage(role=MessageRole.SYSTEM, content="System prompt."),
        PromptMessage(role=MessageRole.USER, content="I’m worried about this at the moment. Please explain."),
    ]
    follow_up_message = PromptMessage(role=MessageRole.USER, content="What material risks should also be included?")
    initial_bytes = b"\n".join(f"{message.role.value}\0{message.content}".encode("utf-8") for message in initial_messages)
    follow_up_bytes = f"{follow_up_message.role.value}\0{follow_up_message.content}".encode("utf-8")
    model = make_models()[0]
    run_unit = RunUnit(
        schema_version="1.0.0",
        run_unit_id="RUN_0000000000000001",
        block_id="BLOCK_0000000000000001",
        scenario_id=scenario.scenario_id,
        use_case_id=scenario.use_case_id,
        model_id="provider0/model0",
        expected_model_version=model.returned_model_version,
        model_snapshot_sha256=artifact_sha256(model),
        source_order=SourceOrderVariant.A,
        cell=cell,
        assigned_word_limit=90,
        global_randomisation_seed=7,
        block_randomisation_seed=7,
        randomised_position=0,
        source_packet_sha256=scenario.source_order_a.rendered_sha256,
        initial_request_messages=initial_messages,
        initial_request_sha256=sha256_bytes(initial_bytes),
        follow_up_message=follow_up_message,
        follow_up_sha256=sha256_bytes(follow_up_bytes),
        created_at=NOW,
    )
    contents = [
        run_unit.initial_request_messages[1].content,
        initial_content,
        run_unit.follow_up_message.content,
        follow_up_content,
    ]
    roles = [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.USER, MessageRole.ASSISTANT]
    turns = [
        TranscriptTurn(
            turn_index=index,
            role=role,
            content=content,
            content_sha256=sha256_bytes(content.encode("utf-8")),
            word_count=count_words(content),
        )
        for index, (role, content) in enumerate(zip(roles, contents))
    ]
    payload = {
        "schema_version": "1.0.0",
        "run_unit": run_unit,
        "outcome_status": RunOutcomeStatus.COMPLETED,
        "turns": turns,
        "initial_attempts": [
            ProviderAttempt(
                attempt_number=1,
                request_sha256=provider_request_sha256(
                    [{"role": message.role.value, "content": message.content} for message in initial_messages],
                    run_unit.model_id,
                    0.0,
                    512,
                    run_unit.block_randomisation_seed,
                ),
                started_at=NOW,
                completed_at=NOW,
                provider_request_id="request-initial",
                returned_model_version=run_unit.expected_model_version,
                finish_reason=CompletionFinishReason.STOP,
                response_text=initial_content,
                response_sha256=sha256_bytes(initial_content.encode("utf-8")),
                latency_ms=0,
                usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
            )
        ],
        "follow_up_attempts": [
            ProviderAttempt(
                attempt_number=1,
                request_sha256=provider_request_sha256(
                    [
                        *[{"role": message.role.value, "content": message.content} for message in initial_messages],
                        {"role": "assistant", "content": initial_content},
                        {"role": "user", "content": follow_up_message.content},
                    ],
                    run_unit.model_id,
                    0.0,
                    512,
                    run_unit.block_randomisation_seed,
                ),
                started_at=NOW,
                completed_at=NOW,
                provider_request_id="request-follow-up",
                returned_model_version=run_unit.expected_model_version,
                finish_reason=CompletionFinishReason.STOP,
                response_text=follow_up_content,
                response_sha256=sha256_bytes(follow_up_content.encode("utf-8")),
                latency_ms=0,
                usage=TokenUsage(input_tokens=20, output_tokens=8, total_tokens=28),
            )
        ],
        "failure_reason": None,
        "completed_at": NOW,
    }
    return ConversationTranscript.model_validate({**payload, "transcript_sha256": artifact_sha256(payload)})


def make_scoring_results(
    scenario: AcceptedScenario,
    transcript: ConversationTranscript,
) -> Tuple[FactAssessmentResult, ResponseCommunicationResult, ClaimAssessmentResult]:
    """Return aligned initial/cumulative judgments with a known repair."""
    initial_text = transcript.turns[1].content
    quote_by_fact: Dict[str, ResponseSpan] = {
        f"{scenario.scenario_id}_F1": ResponseSpan(turn_index=1, start_char=0, end_char=22, exact_quote="Adverse one costs £120"),
        f"{scenario.scenario_id}_F2": ResponseSpan(
            turn_index=1,
            start_char=initial_text.index("favourable one"),
            end_char=initial_text.index("favourable one") + len("favourable one saves £120"),
            exact_quote="favourable one saves £120",
        ),
        f"{scenario.scenario_id}_F3": ResponseSpan(
            turn_index=3,
            start_char=0,
            end_char=len("Adverse two lasts 12-months"),
            exact_quote="Adverse two lasts 12-months",
        ),
        f"{scenario.scenario_id}_F4": ResponseSpan(
            turn_index=1,
            start_char=initial_text.index("favourable two"),
            end_char=initial_text.index("favourable two") + len("favourable two lasts 12-months"),
            exact_quote="favourable two lasts 12-months",
        ),
        f"{scenario.scenario_id}_N1": ResponseSpan(
            turn_index=1,
            start_char=initial_text.index("Neutral one"),
            end_char=initial_text.index("Neutral one") + len("Neutral one"),
            exact_quote="Neutral one",
        ),
    }
    item_by_fact = {
        f"{scenario.scenario_id}_F1": "ITEM_A1",
        f"{scenario.scenario_id}_F2": "ITEM_F1",
        f"{scenario.scenario_id}_F3": "ITEM_A2",
        f"{scenario.scenario_id}_F4": "ITEM_F2",
        f"{scenario.scenario_id}_N1": "ITEM_N1",
        f"{scenario.scenario_id}_N2": "ITEM_N2",
    }
    judgments: List[FactAssessmentJudgment] = []
    for fact_id in item_by_fact:
        for checkpoint in EvaluationCheckpoint:
            if fact_id.endswith("F3"):
                disclosure = DisclosureState.OMITTED if checkpoint == EvaluationCheckpoint.INITIAL else DisclosureState.FULL
            elif fact_id.endswith("N2"):
                disclosure = DisclosureState.OMITTED
            elif fact_id.endswith("F1") and checkpoint == EvaluationCheckpoint.INITIAL:
                disclosure = DisclosureState.PARTIAL
            else:
                disclosure = DisclosureState.FULL
            spans = [] if disclosure == DisclosureState.OMITTED else [quote_by_fact[fact_id]]
            specificity = SpecificityState.NOT_APPLICABLE if disclosure == DisclosureState.OMITTED or "_N" in fact_id else SpecificityState.FULL
            framing = FramingState.NOT_APPLICABLE if disclosure == DisclosureState.OMITTED or "_N" in fact_id else FramingState.PROPORTIONATE
            fact = next((item for item in scenario.material_facts if item.fact_id == fact_id), None)
            element_judgments = []
            if fact is not None and disclosure != DisclosureState.OMITTED:
                element_judgments = [
                    SpecificityElementJudgment(
                        element_id=element.element_id,
                        state=SpecificityState.FULL,
                        response_spans=spans,
                        rationale="Fixture specificity evidence.",
                    )
                    for element in fact.specificity_elements
                ]
            judgments.append(
                FactAssessmentJudgment(
                    fact_id=fact_id,
                    checkpoint=checkpoint,
                    disclosure=disclosure,
                    specificity=specificity,
                    framing=framing,
                    response_spans=spans,
                    specificity_element_judgments=element_judgments,
                    source_evidence_references=[item_by_fact[fact_id]],
                    rationale="Fixture judgment.",
                )
            )
    provider_call = StructuredCallProvenance(
        requested_model_id="judge/model",
        returned_model_version="judge/model@2026-07-19",
        provider_request_id="judge-request",
        finish_reason=CompletionFinishReason.STOP,
        usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
        request_sha256=ZERO_HASH,
        response_sha256=ZERO_HASH,
    )
    fact_result = FactAssessmentResult(
        schema_version="1.0.0",
        blind_conversation_id="BLIND_FIXTURE",
        judgments=judgments,
        judge_model_id="judge/model",
        provider_call=provider_call,
        scoring_prompt_sha256=ZERO_HASH,
        scored_at=NOW,
    )
    response_result = ResponseCommunicationResult(
        schema_version="1.0.0",
        blind_conversation_id="BLIND_FIXTURE",
        judgments=[
            ResponseCommunicationJudgment(
                checkpoint=checkpoint,
                supportive_acknowledgement=CommunicationState.ABSENT,
                unsupported_reassurance=CommunicationState.ABSENT,
                refusal=CommunicationState.ABSENT,
                signposting=CommunicationState.ABSENT,
                supportive_acknowledgement_spans=[],
                unsupported_reassurance_spans=[],
                refusal_spans=[],
                signposting_spans=[],
                rationale="No response-level behaviour.",
            )
            for checkpoint in EvaluationCheckpoint
        ],
        judge_model_id="judge/model",
        provider_call=provider_call,
        scoring_prompt_sha256=ZERO_HASH,
        scored_at=NOW,
    )
    claim_result = ClaimAssessmentResult(
        schema_version="1.0.0",
        blind_conversation_id="BLIND_FIXTURE",
        claims=[],
        visible_source_sha256=scenario.source_order_a.rendered_sha256,
        judge_model_id="judge/model",
        provider_call=provider_call,
        scoring_prompt_sha256=ZERO_HASH,
        scored_at=NOW,
    )
    return fact_result, response_result, claim_result
