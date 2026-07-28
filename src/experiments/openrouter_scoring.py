"""OpenRouter backend for three isolated single-response scoring contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import VersionedImmutableModel, sha256_bytes, utc_now
from src.data_models.experiments import TokenUsage, provider_compatible_seed
from src.data_models.manifests import EvaluatedModelSnapshot
from src.data_models.scoring import (
    AccuracyAssessmentResult,
    AccuracyFinding,
    ConditionBlindScoringInput,
    ContentAssessmentResult,
    FactContentJudgment,
    PresentationAssessmentResult,
    PresentationFinding,
    StructuredCallProvenance,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scoring_contracts import ACCURACY_ASSESSMENT_SYSTEM_PROMPT, CONTENT_ASSESSMENT_SYSTEM_PROMPT, PRESENTATION_ASSESSMENT_SYSTEM_PROMPT
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)


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
            raise ValueError("judge-provided evidence quote does not occur in the isolated response")
        proposed = aligned["start_char"] if isinstance(aligned["start_char"], int) else 0
        start = min(occurrences, key=lambda index: (abs(index - proposed), index))
        return {
            **aligned,
            "turn_index": expected_turn,
            "start_char": start,
            "end_char": start + len(quote),
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
        prompt: str,
        scoring_input: ConditionBlindScoringInput,
    ) -> List[Dict[str, str]]:
        """Render a strict single-response JSON scoring request."""
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": scoring_input.model_dump_json()},
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
        draft = type(response.output).model_validate(payload)
        if repaired and not response.response_repaired:
            response = response.model_copy(update={"response_repaired": True})
        return draft, response

    def assess_content(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> ContentAssessmentResult:
        """Assess binary material-fact and predefined-marker presence."""
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(CONTENT_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
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
            scoring_prompt_sha256=sha256_bytes(CONTENT_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )

    def assess_presentation(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> PresentationAssessmentResult:
        """Assess typed weakening and strengthening behaviours."""
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(PRESENTATION_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
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
            scoring_prompt_sha256=sha256_bytes(PRESENTATION_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )

    def assess_accuracy(
        self,
        scoring_input: ConditionBlindScoringInput,
    ) -> AccuracyAssessmentResult:
        """Assess false and unsupported material factual claims."""
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(ACCURACY_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
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
            scoring_prompt_sha256=sha256_bytes(ACCURACY_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
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
