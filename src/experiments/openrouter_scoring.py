"""OpenRouter backend for the three independent condition-blind scoring contracts."""

from __future__ import annotations

from typing import Dict, List, TypeVar

from pydantic import BaseModel, Field

from src.data_models.common import VersionedImmutableModel, sha256_bytes, utc_now
from src.data_models.experiments import TokenUsage
from src.data_models.manifests import EvaluatedModelSnapshot
from src.data_models.scoring import (
    ClaimAssessmentJudgment,
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    FactAssessmentJudgment,
    FactAssessmentResult,
    ResponseCommunicationJudgment,
    ResponseCommunicationResult,
    StructuredCallProvenance,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scoring_contracts import CLAIM_ASSESSMENT_SYSTEM_PROMPT, FACT_ASSESSMENT_SYSTEM_PROMPT, RESPONSE_COMMUNICATION_SYSTEM_PROMPT
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)


class FactAssessmentDraft(VersionedImmutableModel):
    """Return only fact judgments before code attaches judge provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    judgments: List[FactAssessmentJudgment] = Field(min_length=8, max_length=8)


class ResponseCommunicationDraft(VersionedImmutableModel):
    """Return only response judgments before code attaches judge provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    judgments: List[ResponseCommunicationJudgment] = Field(min_length=2, max_length=2)


class ClaimAssessmentDraft(VersionedImmutableModel):
    """Return only visible-evidence claim judgments before provenance."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    claims: List[ClaimAssessmentJudgment]


class OpenRouterScoringBackend:
    """Run three condition-blind structured calls through one configured judge."""

    def __init__(self, client: OpenRouterClient, judge_snapshot: EvaluatedModelSnapshot) -> None:
        """Configure a scoring-only client and exact judge model id."""
        self.client = client
        self.judge_snapshot = judge_snapshot
        self.judge_model_id = judge_snapshot.model_id

    def _provenance(self, response: ProviderStructuredResponse[StructuredT]) -> StructuredCallProvenance:
        """Validate returned judge identity and convert provider metadata to a strict record."""
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

    def _messages(self, prompt: str, scoring_input: ConditionBlindScoringInput) -> List[Dict[str, str]]:
        """Render a condition-blind strict JSON scoring request."""
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": scoring_input.model_dump_json()},
        ]

    def assess_facts(self, scoring_input: ConditionBlindScoringInput) -> FactAssessmentResult:
        """Assess disclosure, conditional specificity, and conditional framing."""
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(FACT_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
            FactAssessmentDraft,
            temperature=0.0,
            max_tokens=10000,
            seed=scoring_input.randomised_fact_order_seed,
        )
        draft = response.output
        return FactAssessmentResult(
            schema_version="2.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            judgments=draft.judgments,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=sha256_bytes(FACT_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )

    def assess_response(self, scoring_input: ConditionBlindScoringInput) -> ResponseCommunicationResult:
        """Assess acknowledgement, reassurance, refusal, signposting, and generic disclaimers."""
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(RESPONSE_COMMUNICATION_SYSTEM_PROMPT, scoring_input),
            ResponseCommunicationDraft,
            temperature=0.0,
            max_tokens=5000,
            seed=scoring_input.randomised_fact_order_seed,
        )
        draft = response.output
        return ResponseCommunicationResult(
            schema_version="2.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            judgments=draft.judgments,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=sha256_bytes(RESPONSE_COMMUNICATION_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )

    def assess_claims(self, scoring_input: ConditionBlindScoringInput) -> ClaimAssessmentResult:
        """Assess false and unsupported claims using visible evidence only."""
        response = self.client.complete_structured_with_provenance(
            self.judge_model_id,
            self._messages(CLAIM_ASSESSMENT_SYSTEM_PROMPT, scoring_input),
            ClaimAssessmentDraft,
            temperature=0.0,
            max_tokens=5000,
            seed=scoring_input.randomised_fact_order_seed,
        )
        draft = response.output
        return ClaimAssessmentResult(
            schema_version="2.0.0",
            blind_conversation_id=scoring_input.blind_conversation_id,
            claims=draft.claims,
            visible_facts_sha256=scoring_input.visible_facts_sha256,
            judge_model_id=self.judge_model_id,
            provider_call=self._provenance(response),
            scoring_prompt_sha256=sha256_bytes(CLAIM_ASSESSMENT_SYSTEM_PROMPT.encode("utf-8")),
            scored_at=utc_now(),
        )


def create_openrouter_scoring_backend(judge_snapshot: EvaluatedModelSnapshot) -> OpenRouterScoringBackend:
    """Create the configured scoring backend without exposing agent credentials."""
    client = OpenRouterClient.from_settings(
        get_api_settings(),
        get_model_settings(),
        OpenRouterCredentialRole.SCORING,
    )
    return OpenRouterScoringBackend(client=client, judge_snapshot=judge_snapshot)
