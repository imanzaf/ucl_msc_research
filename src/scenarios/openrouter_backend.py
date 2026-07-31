"""OpenRouter implementation of option-information generation and review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Type, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, utc_now
from src.data_models.experiments import ProviderCallProvenance, TokenUsage
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    ReviewDecision,
    ReviewFinding,
    review_finding_reference,
)
from src.data_models.scenarios import (
    ArtifactProvenance,
    CandidateScenario,
    FinanceEntityType,
    ScenarioFactInformation,
    ScenarioHiddenDesign,
    ScenarioOptionDefinition,
    ScenarioOptionInformation,
    ScenarioReplicationSeed,
    ScenarioUseCaseSeed,
    SeedOptionId,
    infer_scenario_stage,
)
from src.experiments.model_catalog import load_model_catalog
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scenario_generation import render_scenario_generation_prompt, render_scenario_review_prompt, render_scenario_revision_prompt
from src.prompts.template_utils import RenderedPrompt
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)
STRUCTURED_MAX_OUTPUT_TOKENS = 2_000


class GenerationDeploymentInput(ImmutableModel):
    """Provide the broad deployment details needed to draft realistic facts."""

    entity_type: FinanceEntityType
    general_task: str = Field(min_length=1, pattern=r"\S")


class GenerationDecisionInput(ImmutableModel):
    """Provide one seed-owned decision and its hidden ownership mapping."""

    decision_type: str = Field(min_length=1, pattern=r"\S")
    options: List[ScenarioOptionDefinition] = Field(min_length=2, max_length=2)
    owner_supporting_option: SeedOptionId
    owner_benefit_mechanism: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_option_ids(self) -> "GenerationDecisionInput":
        """Require exactly one input definition for each neutral option."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation input requires exactly OPTION_A and OPTION_B")
        return self


class ScenarioGenerationInput(ImmutableModel):
    """Define the exact single-call payload sent to the scenario generator."""

    deployment: GenerationDeploymentInput
    decision: GenerationDecisionInput


class ScenarioRevisionInput(ImmutableModel):
    """Define a query-free payload for one bounded scenario revision."""

    frozen_generation_input: ScenarioGenerationInput
    cycle_number: int = Field(ge=1)
    current_options: List[ScenarioOptionInformation] = Field(min_length=2, max_length=2)
    findings: List[ReviewFinding] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_option_mapping(self) -> "ScenarioRevisionInput":
        """Require one current information record for each option identifier."""
        if {option.option_id for option in self.current_options} != set(SeedOptionId):
            raise ValueError("revision input requires one information record for each option identifier")
        return self


GeneratedMaterialFactDraft = ScenarioFactInformation
GeneratedOptionInformationDraft = ScenarioOptionInformation


class ScenarioOptionInformationDraft(ImmutableModel):
    """Return one description and two directional facts for each option."""

    options: List[ScenarioOptionInformation] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_option_mapping(self) -> "ScenarioOptionInformationDraft":
        """Require exactly one generated record for each internal option identifier."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation output requires one information record for each option identifier")
        return self


class ScenarioReviewResponseDraft(VersionedImmutableModel):
    """Return one semantic assessment for the candidate under review."""

    schema_version: str = Field(pattern=r"^3\.1\.0$")
    decision: ReviewDecision
    findings: List[ReviewFinding]

    @model_validator(mode="after")
    def validate_decision(self) -> "ScenarioReviewResponseDraft":
        """Require an accepted scenario assessment to contain no findings."""
        if self.decision == ReviewDecision.ACCEPT and self.findings:
            raise ValueError("accepted scenario assessment cannot contain findings")
        return self


class OpenRouterScenarioBackend:
    """Generate, review, and revise integrated scenario artifacts with independent models."""

    def __init__(self, generation_client: OpenRouterClient, review_client: OpenRouterClient, generator_model_id: str, reviewer_model_id: str) -> None:
        """Configure independent clients and exact provider model ids."""
        if generator_model_id == reviewer_model_id:
            raise ValueError("scenario generator and reviewer model ids must differ")
        self.generation_client = generation_client
        self.review_client = review_client
        self.generator_model_id = generator_model_id
        self.reviewer_model_id = reviewer_model_id

    def _structured(
        self,
        client: OpenRouterClient,
        model_id: str,
        prompt: RenderedPrompt,
        output_model: Type[StructuredT],
    ) -> ProviderStructuredResponse[StructuredT]:
        """Run one deterministic structured call and retain its provider provenance."""
        messages = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]
        is_generation_model = model_id == self.generator_model_id
        return client.complete_structured_with_provenance(
            model_id,
            messages,
            output_model,
            temperature=None if is_generation_model else 0.0,
            max_tokens=STRUCTURED_MAX_OUTPUT_TOKENS,
            seed=7 if is_generation_model else None,
            require_supported_parameters=True,
        )

    def _provider_call(self, response: ProviderStructuredResponse[StructuredT], requested_model_id: str) -> ProviderCallProvenance:
        """Convert one structured provider response to an immutable audit record."""
        return ProviderCallProvenance(
            requested_model_id=requested_model_id,
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

    def _generation_payload(self, use_case: ScenarioUseCaseSeed, replication: ScenarioReplicationSeed) -> Dict[str, Any]:
        """Pass one task-family decision and the conflict needed to generate four facts."""
        payload = ScenarioGenerationInput(
            deployment=GenerationDeploymentInput(
                entity_type=use_case.deployment_context.entity_type,
                general_task=use_case.deployment_context.task,
            ),
            decision=GenerationDecisionInput(
                decision_type=replication.decision_type,
                options=replication.options,
                owner_supporting_option=replication.owner_supporting_option,
                owner_benefit_mechanism=replication.owner_benefit_mechanism,
            ),
        )
        return payload.model_dump(mode="json")

    def _revision_payload(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Dict[str, Any]:
        """Build the minimal typed revision payload without customer messages."""
        payload = ScenarioRevisionInput(
            frozen_generation_input=ScenarioGenerationInput.model_validate(self._generation_payload(use_case, replication)),
            cycle_number=cycle_number,
            current_options=candidate.options,
            findings=[finding for review in reviews for finding in review.findings],
        )
        return payload.model_dump(mode="json")

    def _reject_customer_queries_in_generation_payload(
        self,
        payload: Dict[str, Any],
        replication: ScenarioReplicationSeed,
    ) -> None:
        """Refuse any generator payload containing an exact seed-authored query."""
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        customer_queries = replication.customer_messages.model_dump(mode="json").values()
        if any(query in serialized_payload for query in customer_queries):
            raise ValueError("scenario generation payload must not contain seed-authored customer queries")

    def _assemble_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        response: ProviderStructuredResponse[ScenarioOptionInformationDraft],
        prompt_sha256: str,
        parent_sha256: str | None = None,
    ) -> CandidateScenario:
        """Build one V9.0 candidate from generated option information."""
        draft = response.output
        generated_options = {option.option_id: option for option in draft.options}
        options = [generated_options[option_id] for option_id in replication.presentation_order]
        hidden_design = ScenarioHiddenDesign(
            decision_type=replication.decision_type,
            options=replication.options,
            owner_supporting_option=replication.owner_supporting_option,
            owner_benefit_mechanism=replication.owner_benefit_mechanism,
            presentation_order=replication.presentation_order,
        )
        payload = {
            "schema_version": "9.0.0",
            "scenario_id": replication.scenario_id,
            "use_case_id": use_case.use_case_id,
            "study_stage": infer_scenario_stage(replication.scenario_id),
            "deployment_context": use_case.deployment_context,
            "customer_messages": replication.customer_messages,
            "hidden_design": hidden_design,
            "options": options,
            "provenance": ArtifactProvenance(
                created_at=utc_now(),
                created_by="openrouter_scenario_backend",
                generator_model_id=self.generator_model_id,
                generator_prompt_sha256=prompt_sha256,
                parent_sha256=parent_sha256,
                provider_calls=[self._provider_call(response, self.generator_model_id)],
            ),
        }
        return CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})

    def generate_candidate(self, use_case: ScenarioUseCaseSeed, replication: ScenarioReplicationSeed) -> CandidateScenario:
        """Generate two option-information records in one model call."""
        payload = self._generation_payload(use_case, replication)
        self._reject_customer_queries_in_generation_payload(payload, replication)
        prompt = render_scenario_generation_prompt(payload)
        response = self._structured(
            self.generation_client,
            self.generator_model_id,
            prompt,
            ScenarioOptionInformationDraft,
        )
        return self._assemble_candidate(use_case, replication, response, prompt.template_sha256)

    def review_candidates(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Review exactly one C1, R1, or R2 candidate per model call."""
        if len(candidates) != 1:
            raise ValueError("scenario review processes exactly one candidate at a time")
        candidate = candidates[0]
        is_calibration_review = candidate.scenario_id.endswith("_C1")
        if is_calibration_review:
            if fixed_diversity_candidates:
                raise ValueError("C1 semantic review must not include a diversity anchor")
            fixed_c1_anchor = None
        else:
            if len(fixed_diversity_candidates) != 1:
                raise ValueError("evaluation semantic review requires one R candidate and one fixed C1 anchor")
            fixed_c1_anchor = fixed_diversity_candidates[0]
            use_case_ids = {candidate.use_case_id, fixed_c1_anchor.use_case_id}
            if len(use_case_ids) != 1:
                raise ValueError("evaluation review candidates must belong to one use case")
            if candidate.scenario_id not in {f"{candidate.use_case_id}_R1", f"{candidate.use_case_id}_R2"}:
                raise ValueError("evaluation semantic review requires an R1 or R2 candidate")
            if fixed_c1_anchor.scenario_id != f"{candidate.use_case_id}_C1":
                raise ValueError("evaluation semantic review requires the matching C1 anchor")
        prompt = render_scenario_review_prompt(
            candidate.model_dump(mode="json"),
            fixed_c1_anchor.model_dump(mode="json") if fixed_c1_anchor is not None else None,
        )
        response = self._structured(
            self.review_client,
            self.reviewer_model_id,
            prompt,
            ScenarioReviewResponseDraft,
        )
        draft: ScenarioReviewResponseDraft = response.output
        provider_call = self._provider_call(response, self.reviewer_model_id)
        return [
            AutomatedScenarioReview(
                schema_version="3.1.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=draft.decision,
                findings=draft.findings,
                reviewed_artifact_sha256=candidate.candidate_sha256,
                reviewer_model_id=self.reviewer_model_id,
                reviewer_prompt_sha256=prompt.template_sha256,
                provider_call=provider_call,
                reviewed_at=utc_now(),
            )
        ]

    def revise_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Regenerate the integrated candidate once and record finding-linked content changes."""
        finding_ids = sorted({review_finding_reference(finding) for review in reviews for finding in review.findings})
        if not finding_ids:
            raise ValueError("candidate revision requires at least one review finding")
        payload = self._revision_payload(use_case, replication, candidate, reviews, cycle_number)
        self._reject_customer_queries_in_generation_payload(payload, replication)
        prompt = render_scenario_revision_prompt(payload)
        response = self._structured(
            self.generation_client,
            self.generator_model_id,
            prompt,
            ScenarioOptionInformationDraft,
        )
        revised_candidate = self._assemble_candidate(
            use_case,
            replication,
            response,
            prompt.template_sha256,
            parent_sha256=candidate.candidate_sha256,
        )
        generated_fields = ("options",)
        changes = [
            ControlledFieldChange(
                field_path=field_name,
                previous_value_sha256=artifact_sha256(getattr(candidate, field_name)),
                revised_value_sha256=artifact_sha256(getattr(revised_candidate, field_name)),
                reason=f"Integrated regeneration cycle {cycle_number} resolved the supplied automated findings.",
                finding_ids=finding_ids,
            )
            for field_name in generated_fields
            if getattr(candidate, field_name) != getattr(revised_candidate, field_name)
        ]
        return revised_candidate, changes


def create_openrouter_scenario_backend(invocation_root: Path) -> OpenRouterScenarioBackend:
    """Create independent clients whose raw logs stay within one invocation."""
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    catalog = load_model_catalog()
    generation_client = OpenRouterClient.from_settings(
        api_settings,
        model_settings,
        OpenRouterCredentialRole.SCENARIO_GENERATION,
        structured_log_dir=invocation_root / "provider_logs" / "generation",
    )
    review_client = OpenRouterClient.from_settings(
        api_settings,
        model_settings,
        OpenRouterCredentialRole.SCORING,
        structured_log_dir=invocation_root / "provider_logs" / "review",
    )
    return OpenRouterScenarioBackend(
        generation_client=generation_client,
        review_client=review_client,
        generator_model_id=catalog.scenario_generator_model.model_id,
        reviewer_model_id=catalog.scenario_reviewer_model.model_id,
    )
