"""OpenRouter backend for three isolated single-response scoring contracts."""

from __future__ import annotations

import re
from typing import Dict, List, TypeVar

from pydantic import BaseModel

from src.data_models.common import sha256_bytes, utc_now
from src.data_models.experiments import TokenUsage, provider_compatible_seed
from src.data_models.manifests import EvaluatedModelSnapshot
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    AccuracyResponse,
    BlindFactReference,
    ConditionBlindScoringInput,
    FactContentAssessmentResult,
    FactContentJudgment,
    FactContentResponse,
    FactPresentationAssessmentResult,
    FactPresentationResponse,
    PresentationFinding,
    ResponseSpan,
    StructuredCallProvenance,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scoring_contracts import render_accuracy_assessment_prompt, render_content_assessment_prompt, render_presentation_assessment_prompt
from src.prompts.template_utils import RenderedPrompt
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)


def derive_content_judgment(
    response: FactContentResponse,
    scoring_input: ConditionBlindScoringInput,
    fact: BlindFactReference,
) -> FactContentJudgment:
    """Derive exact response spans and attach the requested fact identifier."""
    expected_marker_ids = {marker.element_id for marker in fact.specificity_markers}
    returned_marker_ids = {marker.element_id for marker in response.markers}
    if returned_marker_ids != expected_marker_ids:
        raise ValueError("content response must decide every supplied specificity marker exactly once")

    response_text = scoring_input.agent_turn.content
    used_occurrences: Dict[str, int] = {}
    spans: List[ResponseSpan] = []
    for quote in response.evidence_sentences:
        occurrences = [match.start() for match in re.finditer(re.escape(quote), response_text)]
        occurrence_index = used_occurrences.get(quote, 0)
        if occurrence_index >= len(occurrences):
            raise ValueError("content evidence sentence is not an exact response substring")
        start_char = occurrences[occurrence_index]
        used_occurrences[quote] = occurrence_index + 1
        spans.append(
            ResponseSpan(
                turn_index=scoring_input.agent_turn.turn_index,
                start_char=start_char,
                end_char=start_char + len(quote),
                exact_quote=quote,
            )
        )
    return FactContentJudgment(
        fact_id=fact.fact_id,
        present=response.fact_present,
        evidence=sorted(spans, key=lambda span: span.start_char),
        marker_judgments=response.markers,
        reasoning=response.reasoning,
    )


def derive_presentation_findings(
    response: FactPresentationResponse,
    scoring_input: ConditionBlindScoringInput,
    fact: BlindFactReference,
) -> List[PresentationFinding]:
    """Validate exact evidence strings and attach the requested fact identifier."""
    for shift in response.shifts:
        if shift.evidence not in scoring_input.agent_turn.content:
            raise ValueError("presentation evidence is not an exact response substring")
    return [PresentationFinding(fact_id=fact.fact_id, **shift.model_dump(mode="python")) for shift in response.shifts]


def validate_accuracy_response(response: AccuracyResponse, scoring_input: ConditionBlindScoringInput) -> AccuracyResponse:
    """Require every false-claim evidence string to quote the response exactly."""
    if any(claim.evidence not in scoring_input.agent_turn.content for claim in response.false_claims):
        raise ValueError("false-claim evidence is not an exact response substring")
    return response


class OpenRouterScoringBackend:
    """Run three isolated structured calls through one configured judge."""

    def __init__(self, client: OpenRouterClient, judge_snapshot: EvaluatedModelSnapshot) -> None:
        """Configure a scoring-only client and exact judge snapshot."""
        self.client = client
        self.judge_snapshot = judge_snapshot
        self.judge_model_id = judge_snapshot.model_id

    def _provenance(
        self,
        response: ProviderStructuredResponse[StructuredT],
    ) -> StructuredCallProvenance:
        """Validate judge identity and retain complete provider metadata."""
        if response.returned_model_version != self.judge_snapshot.returned_model_version:
            raise ValueError(
                f"scoring judge snapshot mismatch: expected {self.judge_snapshot.returned_model_version}, "
                f"received {response.returned_model_version}"
            )
        return StructuredCallProvenance(
            requested_model_id=self.judge_model_id,
            returned_model_version=response.returned_model_version,
            provider_request_id=response.provider_request_id,
            finish_reason=response.finish_reason,
            usage=TokenUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.input_tokens + response.output_tokens,
                cost_credits=response.cost_credits,
                upstream_inference_cost=response.upstream_inference_cost,
            ),
            request_sha256=response.request_sha256,
            response_sha256=response.response_sha256,
            response_repaired=response.response_repaired,
        )

    def _messages(
        self,
        prompt: RenderedPrompt,
    ) -> List[Dict[str, str]]:
        """Convert one rendered scoring template to provider messages."""
        return [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]

    def _seed(
        self,
        scoring_input: ConditionBlindScoringInput,
        contract_name: str,
        fact_id: str | None = None,
    ) -> int:
        """Derive a stable provider seed for one response-contract-fact call."""
        digest = sha256_bytes(
            (f"{scoring_input.randomised_fact_order_seed}:" f"{scoring_input.scored_response.value}:{contract_name}:{fact_id or 'response'}").encode(
                "utf-8"
            )
        )
        return provider_compatible_seed(int(digest[:16], 16))

    def assess_content_fact(
        self,
        scoring_input: ConditionBlindScoringInput,
        fact: BlindFactReference,
    ) -> FactContentAssessmentResult:
        """Assess one material fact and its predefined markers."""
        prompt = render_content_assessment_prompt(scoring_input, fact)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(prompt),
            FactContentResponse,
            temperature=0.0,
            max_tokens=2500,
            seed=self._seed(scoring_input, "content", fact.fact_id),
        )
        judgment = derive_content_judgment(response.output, scoring_input, fact)
        return FactContentAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            fact_id=fact.fact_id,
            judgment=judgment,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=prompt.template_sha256,
            scored_at=utc_now(),
        )

    def assess_presentation_fact(
        self,
        scoring_input: ConditionBlindScoringInput,
        fact: BlindFactReference,
    ) -> FactPresentationAssessmentResult:
        """Assess zero or more presentation shifts for one material fact."""
        prompt = render_presentation_assessment_prompt(scoring_input, fact)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(prompt),
            FactPresentationResponse,
            temperature=0.0,
            max_tokens=3000,
            seed=self._seed(scoring_input, "presentation", fact.fact_id),
        )
        findings = derive_presentation_findings(response.output, scoring_input, fact)
        return FactPresentationAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            fact_id=fact.fact_id,
            findings=findings,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=prompt.template_sha256,
            scored_at=utc_now(),
        )

    def assess_accuracy(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> AccuracyAssessmentResult:
        """Assess materially false factual claims."""
        prompt = render_accuracy_assessment_prompt(scoring_input)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(prompt),
            AccuracyResponse,
            temperature=0.0,
            max_tokens=5000,
            seed=self._seed(scoring_input, "accuracy"),
        )
        accuracy = validate_accuracy_response(response.output, scoring_input)
        return AccuracyAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            false_claim_present=accuracy.false_claim_present,
            false_claims=accuracy.false_claims,
            visible_facts_sha256=scoring_input.visible_facts_sha256,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=prompt.template_sha256,
            scored_at=utc_now(),
        )


def create_openrouter_scoring_backend(
    judge_snapshot: EvaluatedModelSnapshot,
) -> OpenRouterScoringBackend:
    """Create the configured scoring backend without agent credentials."""
    client = OpenRouterClient.from_settings(
        get_api_settings(),
        get_model_settings(),
        OpenRouterCredentialRole.SCORING,
    )
    return OpenRouterScoringBackend(client=client, judge_snapshot=judge_snapshot)
