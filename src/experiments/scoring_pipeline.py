"""Run six isolated scoring calls and derive three metric checkpoints."""

from __future__ import annotations

import random
from typing import Dict, Literal, Protocol, Tuple, cast

from src.data_models.common import artifact_sha256
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    BlindFactReference,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    ConversationMetrics,
    EvaluationCheckpoint,
    PresentationAssessmentResult,
    ScoredResponse,
    ScoringTranscriptTurn,
)
from src.scenarios.fact_rendering import material_facts_without_option_prefix, render_visible_facts, visible_facts_sha256
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results


class ConditionBlindScoringBackend(Protocol):
    """Define three independent contracts over one isolated response."""

    def assess_content(self, scoring_input: ConditionBlindScoringInput) -> ContentAssessmentResult:
        """Assess binary fact and predefined-marker presence."""
        ...

    def assess_presentation(self, scoring_input: ConditionBlindScoringInput) -> PresentationAssessmentResult:
        """Identify typed weakening and strengthening findings."""
        ...

    def assess_accuracy(self, scoring_input: ConditionBlindScoringInput) -> AccuracyAssessmentResult:
        """Identify false and unsupported factual claims."""
        ...


ScoringOutputs = Tuple[
    Dict[ScoredResponse, ContentAssessmentResult],
    Dict[ScoredResponse, PresentationAssessmentResult],
    Dict[ScoredResponse, AccuracyAssessmentResult],
    list[ConversationMetrics],
]


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
    facts = [
        BlindFactReference(
            fact_id=fact.fact_id,
            canonical_proposition=fact.canonical_proposition,
            specificity_elements=specificity_by_fact[fact.fact_id],
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
    """Execute and validate three independent contracts for both responses."""
    if set(scoring_inputs) != set(ScoredResponse):
        raise ValueError("scoring requires isolated initial and follow-up inputs")
    content_results: Dict[ScoredResponse, ContentAssessmentResult] = {}
    presentation_results: Dict[ScoredResponse, PresentationAssessmentResult] = {}
    accuracy_results: Dict[ScoredResponse, AccuracyAssessmentResult] = {}
    for response in ScoredResponse:
        scoring_input = scoring_inputs[response]
        content_results[response] = backend.assess_content(scoring_input)
        presentation_results[response] = backend.assess_presentation(scoring_input)
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
    """Build isolated inputs, run six calls, and derive all metrics."""
    scoring_inputs = build_condition_blind_inputs(transcript, scenario, fact_order_seed)
    outputs = score_condition_blind_inputs(
        scoring_inputs=scoring_inputs,
        transcript=transcript,
        scenario=scenario,
        backend=backend,
    )
    return scoring_inputs, *outputs
