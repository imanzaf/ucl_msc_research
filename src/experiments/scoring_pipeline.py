"""Run six isolated scoring calls and derive three metric checkpoints."""

from __future__ import annotations

import random
from typing import Dict, List, Literal, Protocol, Tuple, cast

from src.data_models.common import artifact_sha256
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    BlindFactReference,
    BlindSpecificityMarker,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    ConversationMetrics,
    EvaluationCheckpoint,
    FactContentAssessmentResult,
    FactPresentationAssessmentResult,
    PresentationAssessmentResult,
    ScoredResponse,
    ScoringTranscriptTurn,
)
from src.scenarios.fact_rendering import material_facts_without_option_prefix, ordered_visible_fact_groups, render_visible_facts, visible_facts_sha256
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results


class ConditionBlindScoringBackend(Protocol):
    """Define fact-level content/presentation and response-level accuracy calls."""

    def assess_content_fact(
        self,
        scoring_input: ConditionBlindScoringInput,
        fact: BlindFactReference,
    ) -> FactContentAssessmentResult:
        """Assess one fact's binary presence and predefined markers."""
        ...

    def assess_presentation_fact(
        self,
        scoring_input: ConditionBlindScoringInput,
        fact: BlindFactReference,
    ) -> FactPresentationAssessmentResult:
        """Identify zero or more presentation shifts for one fact."""
        ...

    def assess_accuracy(self, scoring_input: ConditionBlindScoringInput) -> AccuracyAssessmentResult:
        """Identify materially false factual claims."""
        ...


ScoringOutputs = Tuple[
    Dict[ScoredResponse, ContentAssessmentResult],
    Dict[ScoredResponse, PresentationAssessmentResult],
    Dict[ScoredResponse, AccuracyAssessmentResult],
    list[ConversationMetrics],
]


def aggregate_content_fact_results(
    scoring_input: ConditionBlindScoringInput,
    results: List[FactContentAssessmentResult],
) -> ContentAssessmentResult:
    """Aggregate four independently scored content facts for one response."""
    result_by_fact = {result.fact_id: result for result in results}
    expected_fact_ids = {fact.fact_id for fact in scoring_input.facts}
    if len(result_by_fact) != 4 or set(result_by_fact) != expected_fact_ids:
        raise ValueError("content aggregation requires one result for every supplied fact")
    judge_model_ids = {result.judge_model_id for result in results}
    prompt_hashes = {result.scoring_prompt_sha256 for result in results}
    if len(judge_model_ids) != 1 or len(prompt_hashes) != 1:
        raise ValueError("content fact results must use one judge and prompt contract")
    ordered_results = [result_by_fact[fact.fact_id] for fact in scoring_input.facts]
    return ContentAssessmentResult(
        schema_version="3.0.0",
        blind_conversation_id=scoring_input.blind_conversation_id,
        scored_response=scoring_input.scored_response,
        judgments=[result.judgment for result in ordered_results],
        judge_model_id=ordered_results[0].judge_model_id,
        provider_calls=[result.provider_call for result in ordered_results],
        scoring_prompt_sha256=ordered_results[0].scoring_prompt_sha256,
        scored_at=max(result.scored_at for result in ordered_results),
    )


def aggregate_presentation_fact_results(
    scoring_input: ConditionBlindScoringInput,
    results: List[FactPresentationAssessmentResult],
) -> PresentationAssessmentResult:
    """Aggregate four independently scored presentation facts for one response."""
    result_by_fact = {result.fact_id: result for result in results}
    expected_fact_ids = {fact.fact_id for fact in scoring_input.facts}
    if len(result_by_fact) != 4 or set(result_by_fact) != expected_fact_ids:
        raise ValueError("presentation aggregation requires one result for every supplied fact")
    judge_model_ids = {result.judge_model_id for result in results}
    prompt_hashes = {result.scoring_prompt_sha256 for result in results}
    if len(judge_model_ids) != 1 or len(prompt_hashes) != 1:
        raise ValueError("presentation fact results must use one judge and prompt contract")
    ordered_results = [result_by_fact[fact.fact_id] for fact in scoring_input.facts]
    return PresentationAssessmentResult(
        schema_version="3.0.0",
        blind_conversation_id=scoring_input.blind_conversation_id,
        scored_response=scoring_input.scored_response,
        findings=[finding for result in ordered_results for finding in result.findings],
        judge_model_id=ordered_results[0].judge_model_id,
        provider_calls=[result.provider_call for result in ordered_results],
        scoring_prompt_sha256=ordered_results[0].scoring_prompt_sha256,
        scored_at=max(result.scored_at for result in ordered_results),
    )


def build_condition_blind_inputs(
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
    fact_order_seed: int,
) -> Dict[ScoredResponse, ConditionBlindScoringInput]:
    """Hide labels, fix one fact order, and isolate the two assistant responses."""
    if transcript.outcome_status != RunOutcomeStatus.COMPLETED:
        raise ValueError("only completed transcripts can be scored")
    material_facts = material_facts_without_option_prefix(scenario)
    specificity_by_fact = {
        fact.fact_id: [element for element in scenario.specificity_elements if element.fact_id == fact.fact_id] for fact in material_facts
    }
    fact_text_by_id = {
        fact.fact_id: f"{option_name}: {fact.canonical_proposition}"
        for option_name, option_facts in ordered_visible_fact_groups(scenario)
        for fact in option_facts
    }
    facts = [
        BlindFactReference(
            fact_id=fact.fact_id,
            fact_text=fact_text_by_id[fact.fact_id],
            specificity_markers=[
                BlindSpecificityMarker(element_id=element.element_id, marker_text=element.canonical_value)
                for element in specificity_by_fact[fact.fact_id]
            ],
        )
        for fact in material_facts
    ]
    random.Random(fact_order_seed).shuffle(facts)
    assistant_turns = {
        ScoredResponse.INITIAL: next(turn for turn in transcript.turns if turn.turn_index == 1),
        ScoredResponse.FOLLOW_UP: next(turn for turn in transcript.turns if turn.turn_index == 3),
    }
    blind_id = "BLIND_" + artifact_sha256({"run_unit_id": transcript.run_unit.run_unit_id, "seed": fact_order_seed})[:20].upper()
    inputs: Dict[ScoredResponse, ConditionBlindScoringInput] = {}
    for response, turn in assistant_turns.items():
        inputs[response] = ConditionBlindScoringInput(
            schema_version="3.0.0",
            blind_conversation_id=blind_id,
            scored_response=response,
            visible_facts_text=render_visible_facts(scenario),
            visible_facts_sha256=visible_facts_sha256(scenario),
            facts=facts,
            agent_turn=ScoringTranscriptTurn(
                turn_index=cast(Literal[1, 3], turn.turn_index),
                content=turn.content,
            ),
            randomised_fact_order_seed=fact_order_seed,
        )
    return inputs


def score_condition_blind_inputs(
    scoring_inputs: Dict[ScoredResponse, ConditionBlindScoringInput],
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
    backend: ConditionBlindScoringBackend,
) -> ScoringOutputs:
    """Execute fact-level content/presentation and response-level accuracy calls."""
    if set(scoring_inputs) != set(ScoredResponse):
        raise ValueError("scoring requires isolated initial and follow-up inputs")
    content_results: Dict[ScoredResponse, ContentAssessmentResult] = {}
    presentation_results: Dict[ScoredResponse, PresentationAssessmentResult] = {}
    accuracy_results: Dict[ScoredResponse, AccuracyAssessmentResult] = {}
    for response in ScoredResponse:
        scoring_input = scoring_inputs[response]
        content_results[response] = aggregate_content_fact_results(
            scoring_input,
            [backend.assess_content_fact(scoring_input, fact) for fact in scoring_input.facts],
        )
        presentation_results[response] = aggregate_presentation_fact_results(
            scoring_input,
            [backend.assess_presentation_fact(scoring_input, fact) for fact in scoring_input.facts],
        )
        accuracy_results[response] = backend.assess_accuracy(scoring_input)
        validate_scoring_results(
            scoring_input,
            transcript,
            content_results[response],
            presentation_results[response],
            accuracy_results[response],
        )
    metrics = [
        compute_conversation_metrics(
            transcript=transcript,
            scenario=scenario,
            content_results=content_results,
            presentation_results=presentation_results,
            accuracy_results=accuracy_results,
            checkpoint=checkpoint,
        )
        for checkpoint in EvaluationCheckpoint
    ]
    return content_results, presentation_results, accuracy_results, metrics


def score_conversation(
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
    backend: ConditionBlindScoringBackend,
    fact_order_seed: int,
) -> Tuple[Dict[ScoredResponse, ConditionBlindScoringInput], *ScoringOutputs]:
    """Build isolated inputs, run eighteen calls, and derive all metrics."""
    scoring_inputs = build_condition_blind_inputs(transcript, scenario, fact_order_seed)
    outputs = score_condition_blind_inputs(
        scoring_inputs=scoring_inputs,
        transcript=transcript,
        scenario=scenario,
        backend=backend,
    )
    return scoring_inputs, *outputs
