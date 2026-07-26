"""OpenRouter implementation of option-information generation and review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Type, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, utc_now
from src.data_models.experiments import ProviderCallProvenance, TokenUsage
from src.data_models.scenario_review import AutomatedReviewKind, AutomatedScenarioReview, ControlledFieldChange, ReviewDecision, ReviewFinding
from src.data_models.scenarios import (
    ArtifactProvenance,
    CandidateScenario,
    DecisionOption,
    FactPair,
    FactPairType,
    FactPolarity,
    FinanceEntityType,
    MaterialFact,
    OptionDescription,
    SeedOptionId,
    V11HiddenDesign,
    V11OptionDefinition,
    V11ReplicationSeed,
    V11UseCaseSeed,
    infer_scenario_stage,
)
from src.experiments.model_catalog import load_model_catalog
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT, SCENARIO_REVIEW_SYSTEM_PROMPT, SCENARIO_REVISION_SYSTEM_PROMPT
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
    options: List[V11OptionDefinition] = Field(min_length=2, max_length=2)
    customer_query: str = Field(min_length=1, pattern=r"\S")
    customer_supporting_option: SeedOptionId
    owner_supporting_option: SeedOptionId
    owner_benefit_mechanism: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_option_ids(self) -> "GenerationDecisionInput":
        """Require exactly one input definition for each neutral option."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation input requires exactly OPTION_A and OPTION_B")
        if self.customer_supporting_option == self.owner_supporting_option:
            raise ValueError("generation input ownership mappings must differ")
        return self


class ScenarioGenerationInput(ImmutableModel):
    """Define the exact single-call payload sent to the scenario generator."""

    deployment: GenerationDeploymentInput
    decision: GenerationDecisionInput


class GeneratedOptionInformationDraft(ImmutableModel):
    """Return one documentation-style information record for a decision option."""

    option_id: SeedOptionId
    description: str = Field(min_length=1, max_length=400, pattern=r"\S")
    favourable_fact: str = Field(min_length=1, max_length=400, pattern=r"\S")
    adverse_fact: str = Field(min_length=1, max_length=400, pattern=r"\S")

    @model_validator(mode="after")
    def validate_private_identifiers_absent(self) -> "GeneratedOptionInformationDraft":
        """Keep internal option identifiers out of all generated prose fields."""
        text_fields = [self.description, self.favourable_fact, self.adverse_fact]
        if any(option_id.value in text for option_id in SeedOptionId for text in text_fields):
            raise ValueError("generated option text must not contain internal option identifiers")
        return self


class ScenarioOptionInformationDraft(ImmutableModel):
    """Return one description and two directional facts for each option."""

    options: List[GeneratedOptionInformationDraft] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_option_mapping(self) -> "ScenarioOptionInformationDraft":
        """Require exactly one generated record for each internal option identifier."""
        if {option.option_id for option in self.options} != set(SeedOptionId):
            raise ValueError("generation output requires one information record for each option identifier")
        return self


class ScenarioReviewDraft(ImmutableModel):
    """Return one candidate decision from a semantic review call."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    decision: ReviewDecision
    findings: List[ReviewFinding]

    @model_validator(mode="after")
    def validate_decision(self) -> "ScenarioReviewDraft":
        """Require an accepted scenario assessment to contain no findings."""
        if self.decision == ReviewDecision.ACCEPT and self.findings:
            raise ValueError("accepted scenario assessment cannot contain findings")
        return self


class ScenarioReviewBatchDraft(VersionedImmutableModel):
    """Return one semantic assessment for every candidate under review."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_reviews: List[ScenarioReviewDraft] = Field(min_length=1, max_length=2)


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
        system_prompt: str,
        payload: Dict[str, Any],
        output_model: Type[StructuredT],
    ) -> ProviderStructuredResponse[StructuredT]:
        """Run one deterministic structured call and retain its provider provenance."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
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

    def _generation_prompt(self, revision: bool) -> str:
        """Return the exact initial or revision generation contract."""
        return SCENARIO_REVISION_SYSTEM_PROMPT if revision else SCENARIO_GENERATION_SYSTEM_PROMPT

    def _generation_payload(self, use_case: V11UseCaseSeed, replication: V11ReplicationSeed) -> Dict[str, Any]:
        """Pass one task-family decision and the conflict needed to generate four facts."""
        payload = ScenarioGenerationInput(
            deployment=GenerationDeploymentInput(
                entity_type=use_case.deployment_context.entity_type,
                general_task=use_case.deployment_context.task,
            ),
            decision=GenerationDecisionInput(
                decision_type=replication.decision_type,
                options=replication.options,
                customer_query=replication.customer_messages.initial_message,
                customer_supporting_option=replication.customer_supporting_option,
                owner_supporting_option=replication.owner_supporting_option,
                owner_benefit_mechanism=replication.owner_benefit_mechanism,
            ),
        )
        return payload.model_dump(mode="json")

    def _option_descriptions_facts_and_pairs(
        self,
        replication: V11ReplicationSeed,
        scenario_id: str,
        draft: ScenarioOptionInformationDraft,
    ) -> Tuple[List[OptionDescription], List[MaterialFact], List[FactPair]]:
        """Map generated option information to neutral descriptions and hidden fact coordinates."""
        generated_options = {option.option_id: option for option in draft.options}
        option_name_by_id = {option.option_id: option.option_name for option in replication.options}
        option_descriptions = [
            OptionDescription(option_id=option_id, description=generated_options[option_id].description)
            for option_id in replication.presentation_order
        ]
        option_mapping = {
            DecisionOption.OWNER_OPTION: replication.owner_supporting_option,
            DecisionOption.CUSTOMER_OPTION: replication.customer_supporting_option,
        }
        material_facts: List[MaterialFact] = []
        fact_pairs: List[FactPair] = []
        for pair_number, pair_type in enumerate(FactPairType, start=1):
            polarity = FactPolarity.BENEFIT if pair_type == FactPairType.BENEFIT_COMPARISON else FactPolarity.DOWNSIDE
            pair_id = f"{scenario_id}_P{pair_number}"
            pair_fact_ids: Dict[DecisionOption, str] = {}
            for offset, option in enumerate(DecisionOption):
                option_id = option_mapping[option]
                option_information = generated_options[option_id]
                generated_text = option_information.favourable_fact if polarity == FactPolarity.BENEFIT else option_information.adverse_fact
                fact_id = f"{scenario_id}_F{(pair_number - 1) * 2 + offset + 1}"
                material_facts.append(
                    MaterialFact(
                        fact_id=fact_id,
                        pair_id=pair_id,
                        option=option,
                        polarity=polarity,
                        canonical_proposition=f"{option_name_by_id[option_id]}: {generated_text}",
                        materiality_rationale=f"{polarity.value} of {option_id.value} that is material to the customer's stated decision",
                        required_in_complete_response=True,
                        materiality_rating=4,
                    )
                )
                pair_fact_ids[option] = fact_id
            fact_pairs.append(
                FactPair(
                    pair_id=pair_id,
                    pair_type=pair_type,
                    provider_option_fact_id=pair_fact_ids[DecisionOption.OWNER_OPTION],
                    customer_option_fact_id=pair_fact_ids[DecisionOption.CUSTOMER_OPTION],
                    matching_rationale=f"Compare one customer-relevant {polarity.value} for each feasible option.",
                )
            )
        return option_descriptions, material_facts, fact_pairs

    def _assemble_candidate(
        self,
        use_case: V11UseCaseSeed,
        replication: V11ReplicationSeed,
        response: ProviderStructuredResponse[ScenarioOptionInformationDraft],
        prompt: str,
        parent_sha256: str | None = None,
    ) -> CandidateScenario:
        """Build one V4.1 candidate from generated option information."""
        draft = response.output
        option_descriptions, material_facts, fact_pairs = self._option_descriptions_facts_and_pairs(
            replication,
            replication.scenario_id,
            draft,
        )
        hidden_design = V11HiddenDesign(
            decision_type=replication.decision_type,
            options=replication.options,
            customer_supporting_option=replication.customer_supporting_option,
            owner_supporting_option=replication.owner_supporting_option,
            owner_benefit_mechanism=replication.owner_benefit_mechanism,
            presentation_order=replication.presentation_order,
        )
        payload = {
            "schema_version": "4.1.0",
            "scenario_id": replication.scenario_id,
            "use_case_id": use_case.use_case_id,
            "study_stage": infer_scenario_stage(replication.scenario_id),
            "deployment_context": use_case.deployment_context,
            "customer_messages": replication.customer_messages,
            "hidden_design": hidden_design,
            "option_descriptions": option_descriptions,
            "material_facts": material_facts,
            "fact_pairs": fact_pairs,
            "provenance": ArtifactProvenance(
                created_at=utc_now(),
                created_by="openrouter_scenario_backend",
                generator_model_id=self.generator_model_id,
                generator_prompt_sha256=sha256_bytes(prompt.encode("utf-8")),
                parent_sha256=parent_sha256,
                provider_calls=[self._provider_call(response, self.generator_model_id)],
            ),
        }
        return CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})

    def generate_candidate(self, use_case: V11UseCaseSeed, replication: V11ReplicationSeed) -> CandidateScenario:
        """Generate two option-information records in one model call."""
        prompt = self._generation_prompt(revision=False)
        response = self._structured(
            self.generation_client,
            self.generator_model_id,
            prompt,
            self._generation_payload(use_case, replication),
            ScenarioOptionInformationDraft,
        )
        return self._assemble_candidate(use_case, replication, response, prompt)

    def review_candidates(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Review one C1 or a complete R1-R2 batch with the shared semantic contract."""
        candidate_by_id = {candidate.scenario_id: candidate for candidate in candidates}
        if len(candidate_by_id) != len(candidates):
            raise ValueError("scenario review candidates must have unique identifiers")
        is_calibration_review = len(candidates) == 1 and candidates[0].scenario_id.endswith("_C1")
        if is_calibration_review:
            if fixed_diversity_candidates:
                raise ValueError("C1 semantic review must not include a diversity anchor")
            payload = {"candidates_to_review": [candidates[0].model_dump(mode="json")]}
        else:
            if len(candidates) != 2 or len(fixed_diversity_candidates) != 1:
                raise ValueError("evaluation semantic review requires R1-R2 and one fixed C1 anchor")
            use_case_ids = {candidate.use_case_id for candidate in [*candidates, *fixed_diversity_candidates]}
            if len(use_case_ids) != 1:
                raise ValueError("evaluation review candidates must belong to one use case")
            use_case_id = next(iter(use_case_ids))
            expected_candidate_ids = {f"{use_case_id}_R{index}" for index in range(1, 3)}
            anchor = fixed_diversity_candidates[0]
            if set(candidate_by_id) != expected_candidate_ids or anchor.scenario_id != f"{use_case_id}_C1":
                raise ValueError("evaluation semantic review requires exact C1 and R1-R2 identifiers")
            payload = {
                "candidates_to_review": [candidate.model_dump(mode="json") for candidate in candidates],
                "fixed_c1_anchor": anchor.model_dump(mode="json"),
            }
        prompt = SCENARIO_REVIEW_SYSTEM_PROMPT
        response = self._structured(
            self.review_client,
            self.reviewer_model_id,
            prompt,
            payload,
            ScenarioReviewBatchDraft,
        )
        draft: ScenarioReviewBatchDraft = response.output
        draft_by_id = {review.scenario_id: review for review in draft.scenario_reviews}
        if len(draft_by_id) != len(draft.scenario_reviews) or set(draft_by_id) != set(candidate_by_id):
            raise ValueError("scenario-review response must assess each candidate exactly once")
        provider_call = self._provider_call(response, self.reviewer_model_id)
        prompt_sha256 = sha256_bytes(prompt.encode("utf-8"))
        return [
            AutomatedScenarioReview(
                schema_version="3.0.0",
                scenario_id=scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=draft_by_id[scenario_id].decision,
                findings=draft_by_id[scenario_id].findings,
                reviewed_artifact_sha256=candidate_by_id[scenario_id].candidate_sha256,
                reviewer_model_id=self.reviewer_model_id,
                reviewer_prompt_sha256=prompt_sha256,
                provider_call=provider_call,
                reviewed_at=utc_now(),
            )
            for scenario_id in sorted(candidate_by_id)
        ]

    def revise_candidate(
        self,
        use_case: V11UseCaseSeed,
        replication: V11ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Regenerate the integrated candidate once and record finding-linked content changes."""
        prompt = self._generation_prompt(revision=True)
        finding_ids = sorted({finding.finding_id for review in reviews for finding in review.findings})
        if not finding_ids:
            raise ValueError("candidate revision requires at least one review finding")
        response = self._structured(
            self.generation_client,
            self.generator_model_id,
            prompt,
            {
                "frozen_generation_input": self._generation_payload(use_case, replication),
                "cycle_number": cycle_number,
                "candidate": candidate.model_dump(mode="json"),
                "findings": [finding.model_dump(mode="json") for review in reviews for finding in review.findings],
            },
            ScenarioOptionInformationDraft,
        )
        revised_candidate = self._assemble_candidate(
            use_case,
            replication,
            response,
            prompt,
            parent_sha256=candidate.candidate_sha256,
        )
        generated_fields = (
            "option_descriptions",
            "material_facts",
            "fact_pairs",
        )
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
        if not changes:
            raise ValueError("integrated candidate revision did not change any generated content")
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
