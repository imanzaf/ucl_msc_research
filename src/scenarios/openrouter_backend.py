"""OpenRouter implementation of initial option-information generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Type, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import ImmutableModel, artifact_sha256, utc_now
from src.data_models.experiments import ProviderCallProvenance, TokenUsage
from src.data_models.scenarios import (
    AcceptedScenario,
    ArtifactProvenance,
    CandidateScenario,
    ComparisonScope,
    FinanceEntityType,
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
from src.prompts.scenario_generation import render_scenario_generation_prompt
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
    comparison_scope: ComparisonScope
    external_option_id: SeedOptionId | None

    @model_validator(mode="after")
    def validate_option_ids(self) -> "GenerationDecisionInput":
        """Require exactly one input definition for each neutral option."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation input requires exactly OPTION_A and OPTION_B")
        if self.comparison_scope == ComparisonScope.INTRA_PROVIDER and self.external_option_id is not None:
            raise ValueError("intra-provider generation input cannot identify an external option")
        if self.comparison_scope == ComparisonScope.PROVIDER_VS_EXTERNAL:
            if self.external_option_id is None:
                raise ValueError("provider-versus-external generation input requires one external option")
            if self.external_option_id == self.owner_supporting_option:
                raise ValueError("the provider owner cannot benefit from the external option")
        return self


class GenerationExampleInput(ImmutableModel):
    """Provide only C1 option-information records as an R-generation example."""

    options: List[ScenarioOptionInformation] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_option_mapping(self) -> "GenerationExampleInput":
        """Require one accepted information record for each example option."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation example requires one information record for each option identifier")
        return self


class ScenarioGenerationInput(ImmutableModel):
    """Define the exact single-call payload sent to the scenario generator."""

    deployment: GenerationDeploymentInput
    decision: GenerationDecisionInput
    c1_example: GenerationExampleInput | None = None


class ScenarioOptionInformationDraft(ImmutableModel):
    """Return one description and two directional facts for each option."""

    options: List[ScenarioOptionInformation] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_option_mapping(self) -> "ScenarioOptionInformationDraft":
        """Require exactly one generated record for each internal option identifier."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation output requires one information record for each option identifier")
        return self


class OpenRouterScenarioBackend:
    """Generate one initial candidate per OpenRouter call."""

    def __init__(
        self,
        generation_client: OpenRouterClient,
        generator_model_id: str,
    ) -> None:
        """Configure the sole generation client and model."""
        self.generation_client = generation_client
        self.generator_model_id = generator_model_id

    def _structured(
        self,
        prompt: RenderedPrompt,
        output_model: Type[StructuredT],
    ) -> ProviderStructuredResponse[StructuredT]:
        """Run one deterministic structured call and retain its provider provenance."""
        messages = [
            {"role": "system", "content": prompt.system},
            {"role": "user", "content": prompt.user},
        ]
        return self.generation_client.complete_structured_with_provenance(
            self.generator_model_id,
            messages,
            output_model,
            temperature=None,
            max_tokens=STRUCTURED_MAX_OUTPUT_TOKENS,
            seed=7,
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

    def _generation_example(
        self,
        use_case: ScenarioUseCaseSeed,
        candidate: AcceptedScenario,
    ) -> GenerationExampleInput:
        """Extract only option information from the matching published C1 artifact."""
        if candidate.scenario_id != f"{use_case.use_case_id}_C1" or candidate.use_case_id != use_case.use_case_id:
            raise ValueError("evaluation generation requires the matching C1 example")
        if candidate.deployment_context != use_case.deployment_context:
            raise ValueError("C1 generation example must use the selected deployment context")
        return GenerationExampleInput(options=candidate.options)

    def _generation_payload(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        fixed_c1_example: AcceptedScenario | None,
    ) -> Dict[str, Any]:
        """Pass one task-family decision and the conflict needed to generate four facts."""
        is_calibration_generation = replication.scenario_id.endswith("_C1")
        if is_calibration_generation and fixed_c1_example is not None:
            raise ValueError("C1 generation must not include a C1 example")
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
                comparison_scope=replication.comparison_scope,
                external_option_id=replication.external_option_id,
            ),
            c1_example=self._generation_example(use_case, fixed_c1_example) if fixed_c1_example is not None else None,
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
            comparison_scope=replication.comparison_scope,
            external_option_id=replication.external_option_id,
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
                provider_calls=[self._provider_call(response, self.generator_model_id)],
            ),
        }
        return CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})

    def generate_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        fixed_c1_example: AcceptedScenario | None = None,
    ) -> CandidateScenario:
        """Generate two option-information records in one model call."""
        is_calibration_generation = replication.scenario_id.endswith("_C1")
        if not is_calibration_generation:
            if replication.scenario_id not in {f"{use_case.use_case_id}_R1", f"{use_case.use_case_id}_R2"}:
                raise ValueError("evaluation generation requires an R1 or R2 seed")
            if fixed_c1_example is None:
                raise ValueError("evaluation generation requires one published C1 example")
            if not isinstance(fixed_c1_example, AcceptedScenario):
                raise ValueError("evaluation generation requires a published AcceptedScenario record")
        payload = self._generation_payload(use_case, replication, fixed_c1_example)
        self._reject_customer_queries_in_generation_payload(payload, replication)
        prompt = render_scenario_generation_prompt(payload)
        response = self._structured(
            prompt,
            ScenarioOptionInformationDraft,
        )
        return self._assemble_candidate(use_case, replication, response, prompt.template_sha256)


def create_openrouter_scenario_backend(invocation_root: Path) -> OpenRouterScenarioBackend:
    """Create the generation-only backend used by the active scenario workflow."""
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    catalog = load_model_catalog()
    generation_client = OpenRouterClient.from_settings(
        api_settings,
        model_settings,
        OpenRouterCredentialRole.SCENARIO_GENERATION,
        structured_log_dir=invocation_root / "provider_logs" / "generation",
    )
    return OpenRouterScenarioBackend(
        generation_client=generation_client,
        generator_model_id=catalog.scenario_generator_model.model_id,
    )
