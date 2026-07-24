"""Run three independent condition-blind scoring contracts and validated metrics."""

from __future__ import annotations

import random
from typing import List, Literal, Protocol, Tuple, cast

from src.data_models.common import artifact_sha256
from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus
from src.data_models.scenarios import AcceptedScenario
from src.data_models.scoring import (
    BlindFactReference,
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    ConversationMetrics,
    EvaluationCheckpoint,
    FactAssessmentResult,
    ResponseCommunicationResult,
    ScoringTranscriptTurn,
)
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.validation import validate_scoring_results


class ConditionBlindScoringBackend(Protocol):
    """Define three isolated scoring calls over the same blinded input."""

    def assess_facts(self, scoring_input: ConditionBlindScoringInput) -> FactAssessmentResult:
        """Assess fact disclosure, specificity, and framing."""
        ...

    def assess_response(self, scoring_input: ConditionBlindScoringInput) -> ResponseCommunicationResult:
        """Assess acknowledgement, reassurance, refusal, signposting, and generic disclaimers."""
        ...

    def assess_claims(self, scoring_input: ConditionBlindScoringInput) -> ClaimAssessmentResult:
        """Assess false and unsupported claims against visible evidence."""
        ...


def build_condition_blind_input(
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
    fact_order_seed: int,
) -> ConditionBlindScoringInput:
    """Hide treatment/model labels and randomise fact order before scoring."""
    if transcript.outcome_status != RunOutcomeStatus.COMPLETED:
        raise ValueError("only completed transcripts can be scored")
    packet = scenario.source_packet
    specificity_by_fact = {
        fact.fact_id: [element for element in scenario.specificity_elements if element.fact_id == fact.fact_id] for fact in scenario.material_facts
    }
    facts = [
        BlindFactReference(
            fact_id=fact.fact_id,
            canonical_proposition=fact.canonical_proposition,
            source_support=fact.source_support,
            specificity_elements=specificity_by_fact[fact.fact_id],
        )
        for fact in scenario.material_facts
    ]
    random.Random(fact_order_seed).shuffle(facts)
    assistant_turns = [
        ScoringTranscriptTurn(turn_index=cast(Literal[1, 3], turn.turn_index), content=turn.content)
        for turn in transcript.turns
        if turn.turn_index in {1, 3}
    ]
    blind_id = "BLIND_" + artifact_sha256({"run_unit_id": transcript.run_unit.run_unit_id, "seed": fact_order_seed})[:20].upper()
    return ConditionBlindScoringInput(
        schema_version="2.0.0",
        blind_conversation_id=blind_id,
        visible_source_text=packet.rendered_text,
        visible_source_sha256=packet.rendered_sha256,
        facts=facts,
        agent_turns=assistant_turns,
        randomised_fact_order_seed=fact_order_seed,
    )


def score_conversation(
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
    backend: ConditionBlindScoringBackend,
    fact_order_seed: int,
    prompt_factor_isolation_valid: bool,
) -> Tuple[
    ConditionBlindScoringInput,
    FactAssessmentResult,
    ResponseCommunicationResult,
    ClaimAssessmentResult,
    List[ConversationMetrics],
]:
    """Execute, validate, and metricise all three scoring contracts."""
    scoring_input = build_condition_blind_input(transcript, scenario, fact_order_seed)
    fact_result, response_result, claim_result, metrics = score_condition_blind_input(
        scoring_input=scoring_input,
        transcript=transcript,
        scenario=scenario,
        backend=backend,
        prompt_factor_isolation_valid=prompt_factor_isolation_valid,
    )
    return scoring_input, fact_result, response_result, claim_result, metrics


def score_condition_blind_input(
    scoring_input: ConditionBlindScoringInput,
    transcript: ConversationTranscript,
    scenario: AcceptedScenario,
    backend: ConditionBlindScoringBackend,
    prompt_factor_isolation_valid: bool,
) -> Tuple[FactAssessmentResult, ResponseCommunicationResult, ClaimAssessmentResult, List[ConversationMetrics]]:
    """Execute and validate all contracts for one already-frozen blinded input."""
    fact_result = backend.assess_facts(scoring_input)
    response_result = backend.assess_response(scoring_input)
    claim_result = backend.assess_claims(scoring_input)
    validate_scoring_results(scoring_input, transcript, fact_result, response_result, claim_result)
    metrics = [
        compute_conversation_metrics(
            transcript=transcript,
            scenario=scenario,
            fact_result=fact_result,
            response_result=response_result,
            claim_result=claim_result,
            checkpoint=checkpoint,
            prompt_factor_isolation_valid=prompt_factor_isolation_valid,
        )
        for checkpoint in EvaluationCheckpoint
    ]
    return fact_result, response_result, claim_result, metrics
