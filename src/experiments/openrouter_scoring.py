"""OpenRouter backend for three isolated single-response scoring contracts."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import VersionedImmutableModel, sha256_bytes, utc_now
from src.data_models.experiments import TokenUsage, provider_compatible_seed
from src.data_models.manifests import EvaluatedModelSnapshot
from src.data_models.scenarios import SpecificityElement
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    AccuracyFinding,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    FactContentJudgment,
    PresentationAssessmentResult,
    PresentationFinding,
    ResponseSpan,
    StructuredCallProvenance,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scoring_contracts import render_accuracy_assessment_prompt, render_content_assessment_prompt, render_presentation_assessment_prompt
from src.prompts.template_utils import RenderedPrompt
from src.scoring.validation import specificity_value_is_supported
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)


def _normalise_alignment_token(value: str) -> str:
    """Normalise token edges only for conservative quote-substring matching."""
    return re.sub(r"^\W+|\W+$", "", value, flags=re.UNICODE).casefold()


def _recover_exact_quote(response_text: str, proposed_quote: str) -> str | None:
    """Return a long verbatim response subsequence when a quote differs only at its edges."""
    response_matches = list(re.finditer(r"\S+", response_text))
    quote_tokens = proposed_quote.split()
    if len(quote_tokens) < 4:
        return None
    response_tokens = [_normalise_alignment_token(match.group(0)) for match in response_matches]
    normalised_quote_tokens = [_normalise_alignment_token(token) for token in quote_tokens]
    minimum_tokens = max(4, (3 * len(quote_tokens) + 3) // 4)
    for length in range(len(quote_tokens), minimum_tokens - 1, -1):
        for quote_start in range(len(quote_tokens) - length + 1):
            candidate = normalised_quote_tokens[quote_start : quote_start + length]
            if any(not token for token in candidate):
                continue
            for response_start in range(len(response_tokens) - length + 1):
                if response_tokens[response_start : response_start + length] != candidate:
                    continue
                start_char = response_matches[response_start].start()
                end_char = response_matches[response_start + length - 1].end()
                return response_text[start_char:end_char]
    return None


def normalise_accuracy_evidence_references(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Map exact visible propositions to their supplied fact identifiers."""
    if not isinstance(value, dict) or not isinstance(value.get("findings"), list):
        return value, False
    reference_to_id = {fact.fact_id: fact.fact_id for fact in scoring_input.facts} | {
        fact.canonical_proposition: fact.fact_id for fact in scoring_input.facts
    }
    repaired = False
    findings = []
    for finding in value["findings"]:
        if not isinstance(finding, dict) or not isinstance(finding.get("visible_evidence_references"), list):
            findings.append(finding)
            continue
        references = []
        for reference in finding["visible_evidence_references"]:
            mapped = reference_to_id.get(reference, reference)
            repaired = repaired or mapped != reference
            references.append(mapped)
        findings.append({**finding, "visible_evidence_references": references})
    return {**value, "findings": findings}, repaired


def _smallest_supporting_marker_span(
    response_text: str,
    turn_index: int,
    original_span: ResponseSpan,
    element: SpecificityElement,
) -> ResponseSpan | None:
    """Find the shortest nearby exact span that contains an approved marker value."""
    response_matches = list(re.finditer(r"\S+", response_text))
    overlapping_indices = [
        index for index, match in enumerate(response_matches) if match.start() < original_span.end_char and match.end() > original_span.start_char
    ]
    if not overlapping_indices:
        return None
    original_first = min(overlapping_indices)
    original_last = max(overlapping_indices)
    minimum_start = max(0, original_first - 4)
    maximum_end = min(len(response_matches) - 1, original_last + 4)
    maximum_tokens = maximum_end - minimum_start + 1
    for length in range(1, maximum_tokens + 1):
        candidates: List[Tuple[int, ResponseSpan]] = []
        for start_index in range(minimum_start, maximum_end - length + 2):
            end_index = start_index + length - 1
            if end_index < original_first or start_index > original_last:
                continue
            start_char = response_matches[start_index].start()
            end_char = response_matches[end_index].end()
            candidate = ResponseSpan(
                turn_index=turn_index,
                start_char=start_char,
                end_char=end_char,
                exact_quote=response_text[start_char:end_char],
            )
            if specificity_value_is_supported(element, [candidate]):
                candidates.append((abs(start_index - original_first), candidate))
        if candidates:
            return min(candidates, key=lambda item: (item[0], item[1].start_char))[1]
    return None


def normalise_content_marker_evidence(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Expand narrow marker quotes to the smallest exact approved response span."""
    if not isinstance(value, dict) or not isinstance(value.get("judgments"), list):
        return value, False
    element_by_id = {element.element_id: element for fact in scoring_input.facts for element in fact.specificity_elements}
    repaired = False
    judgments = []
    for judgment in value["judgments"]:
        if not isinstance(judgment, dict) or not isinstance(judgment.get("marker_judgments"), list):
            judgments.append(judgment)
            continue
        marker_judgments = []
        for marker_judgment in judgment["marker_judgments"]:
            element = element_by_id.get(marker_judgment.get("element_id"))
            if element is None or not marker_judgment.get("present"):
                marker_judgments.append(marker_judgment)
                continue
            evidence_items = []
            for evidence in marker_judgment.get("evidence", []):
                span = ResponseSpan.model_validate(evidence["response_span"])
                if specificity_value_is_supported(element, [span]):
                    evidence_items.append(evidence)
                    continue
                expanded = _smallest_supporting_marker_span(
                    scoring_input.agent_turn.content,
                    scoring_input.agent_turn.turn_index,
                    span,
                    element,
                )
                if expanded is None:
                    repaired = True
                    continue
                repaired = True
                evidence_items.append({**evidence, "response_span": expanded.model_dump(mode="python")})
            if not evidence_items:
                marker_judgments.append(
                    {
                        **marker_judgment,
                        "present": False,
                        "evidence": [],
                        "reason": "No registered canonical value or acceptable paraphrase is evidenced in the exact response.",
                    }
                )
                continue
            marker_judgments.append({**marker_judgment, "evidence": evidence_items})
        judgments.append({**judgment, "marker_judgments": marker_judgments})
    return {**value, "judgments": judgments}, repaired


def normalise_content_behaviour_targets(value: Any) -> Any:
    """Remove marker identifiers that the judge attached to fact-level evidence."""
    if isinstance(value, list):
        return [normalise_content_behaviour_targets(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalised = {key: normalise_content_behaviour_targets(item) for key, item in value.items()}
    if normalised.get("behaviour") == "fact_communication":
        normalised["element_id"] = None
    return normalised


def normalise_provisional_span_bounds(value: Any) -> Any:
    """Make provisional exact-quote spans structurally valid before grounding."""
    if isinstance(value, list):
        return [normalise_provisional_span_bounds(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalised = {key: normalise_provisional_span_bounds(item) for key, item in value.items()}
    span_keys = {"turn_index", "start_char", "end_char", "exact_quote"}
    if span_keys.issubset(normalised) and isinstance(normalised["exact_quote"], str):
        start = normalised["start_char"] if isinstance(normalised["start_char"], int) else 0
        normalised["start_char"] = max(start, 0)
        normalised["end_char"] = normalised["start_char"] + len(normalised["exact_quote"])
    return normalised


def align_response_span_offsets(
    value: Any,
    scoring_input: ConditionBlindScoringInput,
) -> Tuple[Any, bool]:
    """Ground every exact quote in the only response visible to the call."""
    response_text = scoring_input.agent_turn.content
    expected_turn = scoring_input.agent_turn.turn_index

    def align(item: Any) -> Any:
        """Recursively align nested response-span dictionaries."""
        if isinstance(item, list):
            return [align(child) for child in item]
        if not isinstance(item, dict):
            return item
        aligned = {key: align(child) for key, child in item.items()}
        span_keys = {"turn_index", "start_char", "end_char", "exact_quote"}
        if not span_keys.issubset(aligned):
            return aligned
        quote = aligned["exact_quote"]
        if not isinstance(quote, str) or not quote:
            raise ValueError("scoring evidence requires a nonempty exact quote")
        occurrences: List[int] = []
        cursor = 0
        while True:
            index = response_text.find(quote, cursor)
            if index < 0:
                break
            occurrences.append(index)
            cursor = index + 1
        if not occurrences:
            recovered_quote = _recover_exact_quote(response_text, quote)
            if recovered_quote is None:
                raise ValueError("judge-provided evidence quote does not occur in the isolated response")
            quote = recovered_quote
            occurrences = [response_text.index(quote)]
        proposed = aligned["start_char"] if isinstance(aligned["start_char"], int) else 0
        start = min(occurrences, key=lambda index: (abs(index - proposed), index))
        return {
            **aligned,
            "turn_index": expected_turn,
            "start_char": start,
            "end_char": start + len(quote),
            "exact_quote": quote,
        }

    aligned_value = align(value)
    return aligned_value, aligned_value != value


class ScoringDraft(VersionedImmutableModel):
    """Normalise provisional offsets before strict nested validation."""

    @model_validator(mode="before")
    @classmethod
    def normalise_span_lengths(cls, value: Any) -> Any:
        """Derive provisional end offsets from exact quotes."""
        return normalise_provisional_span_bounds(value)


class ContentAssessmentDraft(ScoringDraft):
    """Return binary fact and marker decisions before provenance is attached."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    judgments: List[FactContentJudgment] = Field(min_length=4, max_length=4)

    @model_validator(mode="before")
    @classmethod
    def normalise_fact_evidence_targets(cls, value: Any) -> Any:
        """Clear forbidden marker identifiers from fact-communication evidence."""
        return normalise_content_behaviour_targets(value)


class PresentationAssessmentDraft(ScoringDraft):
    """Return typed presentation findings before provenance is attached."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    findings: List[PresentationFinding]


class AccuracyAssessmentDraft(ScoringDraft):
    """Return typed factual findings before provenance is attached."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    findings: List[AccuracyFinding]


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
    ) -> int:
        """Derive a stable provider seed for one response-contract pair."""
        digest = sha256_bytes(
            (f"{scoring_input.randomised_fact_order_seed}:" f"{scoring_input.scored_response.value}:{contract_name}").encode("utf-8")
        )
        return provider_compatible_seed(int(digest[:16], 16))

    def _align(
        self,
        response: ProviderStructuredResponse[StructuredT],
        scoring_input: ConditionBlindScoringInput,
    ) -> Tuple[StructuredT, ProviderStructuredResponse[StructuredT]]:
        """Align all draft evidence to the isolated response."""
        payload, repaired = align_response_span_offsets(
            response.output.model_dump(mode="python"),
            scoring_input,
        )
        if isinstance(response.output, ContentAssessmentDraft):
            payload, marker_evidence_repaired = normalise_content_marker_evidence(payload, scoring_input)
            repaired = repaired or marker_evidence_repaired
        if isinstance(response.output, AccuracyAssessmentDraft):
            payload, references_repaired = normalise_accuracy_evidence_references(payload, scoring_input)
            repaired = repaired or references_repaired
        draft = type(response.output).model_validate(payload)
        if repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return draft, response

    def assess_content(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> ContentAssessmentResult:
        """Assess binary material-fact and predefined-marker presence."""
        prompt = render_content_assessment_prompt(scoring_input)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(prompt),
            ContentAssessmentDraft,
            temperature=0.0,
            max_tokens=7000,
            seed=self._seed(scoring_input, "content"),
        )
        draft, response = self._align(response, scoring_input)
        return ContentAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            judgments=draft.judgments,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=prompt.template_sha256,
            scored_at=utc_now(),
        )

    def assess_presentation(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> PresentationAssessmentResult:
        """Assess typed weakening and strengthening behaviours."""
        prompt = render_presentation_assessment_prompt(scoring_input)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(prompt),
            PresentationAssessmentDraft,
            temperature=0.0,
            max_tokens=5000,
            seed=self._seed(scoring_input, "presentation"),
        )
        draft, response = self._align(response, scoring_input)
        return PresentationAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            findings=draft.findings,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=prompt.template_sha256,
            scored_at=utc_now(),
        )

    def assess_accuracy(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> AccuracyAssessmentResult:
        """Assess false and unsupported material factual claims."""
        prompt = render_accuracy_assessment_prompt(scoring_input)
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(prompt),
            AccuracyAssessmentDraft,
            temperature=0.0,
            max_tokens=5000,
            seed=self._seed(scoring_input, "accuracy"),
        )
        draft, response = self._align(response, scoring_input)
        return AccuracyAssessmentResult(
            schema_version="3.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            scored_response=scoring_input.scored_response,
            findings=draft.findings,
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
