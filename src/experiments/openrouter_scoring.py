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


def _markdown_visible_text_with_mapping(line: str, line_offset: int) -> tuple[str, List[int]]:
    """Strip presentation-only Markdown while retaining visible-character source positions."""
    list_prefix = re.match(r"^\s*(?:(?:[-+*])|(?:\d+[.)]))\s+", line)
    start = list_prefix.end() if list_prefix is not None else 0
    visible: List[str] = []
    source_positions: List[int] = []
    index = start
    while index < len(line):
        token = next((value for value in ["**", "__", "~~", "`"] if line.startswith(value, index)), None)
        if token is not None:
            index += len(token)
            continue
        visible.append(line[index])
        source_positions.append(line_offset + index)
        index += 1
    return "".join(visible), source_positions


def _formatting_equivalent_spans(response_text: str, quote: str) -> List[tuple[int, int]]:
    """Resolve a judge quote after removing only Markdown presentation delimiters."""
    normalised_quote, _ = _markdown_visible_text_with_mapping(quote.strip(), 0)
    if not normalised_quote:
        return []
    spans: List[tuple[int, int]] = []
    line_offset = 0
    for line in response_text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        visible, source_positions = _markdown_visible_text_with_mapping(content, line_offset)
        search_start = 0
        while True:
            match_start = visible.find(normalised_quote, search_start)
            if match_start < 0:
                break
            match_end = match_start + len(normalised_quote)
            if match_start == 0 and match_end == len(visible):
                spans.append((line_offset, line_offset + len(content)))
            else:
                spans.append((source_positions[match_start], source_positions[match_end - 1] + 1))
            search_start = match_start + 1
        line_offset += len(line)
    return spans


def _resolve_evidence_span(response_text: str, quote: str, occurrence_index: int) -> tuple[int, int]:
    """Resolve exact evidence first, then a unique formatting-only Markdown equivalent."""
    exact_spans = [(match.start(), match.end()) for match in re.finditer(re.escape(quote), response_text)]
    if occurrence_index < len(exact_spans):
        return exact_spans[occurrence_index]
    formatting_spans = _formatting_equivalent_spans(response_text, quote)
    if occurrence_index >= len(formatting_spans):
        raise ValueError("content evidence sentence is not an exact response substring or Markdown-formatting equivalent")
    if len(set(formatting_spans)) != len(formatting_spans):
        raise ValueError("content evidence sentence has ambiguous Markdown-formatting matches")
    return formatting_spans[occurrence_index]


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
        occurrence_index = used_occurrences.get(quote, 0)
        start_char, end_char = _resolve_evidence_span(response_text, quote, occurrence_index)
        used_occurrences[quote] = occurrence_index + 1
        spans.append(
            ResponseSpan(
                turn_index=scoring_input.agent_turn.turn_index,
                start_char=start_char,
                end_char=end_char,
                exact_quote=response_text[start_char:end_char],
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
    """Resolve evidence to source text and attach the requested fact identifier."""
    used_occurrences: Dict[str, int] = {}
    findings: List[PresentationFinding] = []
    for shift in response.shifts:
        occurrence_index = used_occurrences.get(shift.evidence, 0)
        start_char, end_char = _resolve_evidence_span(scoring_input.agent_turn.content, shift.evidence, occurrence_index)
        used_occurrences[shift.evidence] = occurrence_index + 1
        payload = shift.model_dump(mode="python")
        payload["evidence"] = scoring_input.agent_turn.content[start_char:end_char]
        findings.append(PresentationFinding(fact_id=fact.fact_id, **payload))
    return findings


def validate_accuracy_response(response: AccuracyResponse, scoring_input: ConditionBlindScoringInput) -> AccuracyResponse:
    """Resolve every false-claim evidence string to the exact source response text."""
    used_occurrences: Dict[str, int] = {}
    resolved_claims = []
    for claim in response.false_claims:
        occurrence_index = used_occurrences.get(claim.evidence, 0)
        start_char, end_char = _resolve_evidence_span(scoring_input.agent_turn.content, claim.evidence, occurrence_index)
        used_occurrences[claim.evidence] = occurrence_index + 1
        resolved_claims.append(
            claim.model_copy(update={"evidence": scoring_input.agent_turn.content[start_char:end_char]}),
        )
    return response.model_copy(update={"false_claims": resolved_claims})


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
