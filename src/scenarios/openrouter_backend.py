"""OpenRouter implementation of integrated scenario generation and review."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel, Field, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, utc_now
from src.data_models.experiments import ProviderCallProvenance, TokenUsage
from src.data_models.scenario_review import AutomatedReviewKind, AutomatedScenarioReview, ControlledFieldChange, ReviewDecision, ReviewFinding
from src.data_models.scenarios import (
    ArtifactProvenance,
    CandidateScenario,
    DecisionOption,
    EvidencePairType,
    EvidenceSpan,
    FactPair,
    FactPolarity,
    MaterialFact,
    MinimalCompleteResponse,
    NeutralFact,
    NumericCalculation,
    NumericInput,
    ReplicationSeed,
    SourceItem,
    SpecificityElement,
    SpecificityElementType,
    UseCaseSeed,
    infer_scenario_stage,
)
from src.experiments.model_catalog import load_model_catalog
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scenario_generation import (
    BATCH_DIVERSITY_REVIEW_SYSTEM_PROMPT,
    SCENARIO_GENERATION_SYSTEM_PROMPT,
    SCENARIO_QUALITY_REVIEW_SYSTEM_PROMPT,
    SCENARIO_REVISION_SYSTEM_PROMPT,
)
from src.scenarios.numeric_engine import compute_numeric_registry
from src.scenarios.rendering_templates import SOURCE_FORMAT_BY_USE_CASE
from src.scenarios.source_rendering import build_source_packet, validate_evidence_span
from src.scenarios.word_count import count_words
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)


class SpecificityElementDraft(ImmutableModel):
    """Return one predefined concrete detail without an identifier."""

    element_type: SpecificityElementType
    canonical_value: str = Field(min_length=1)
    unit: Optional[str] = Field(default=None, min_length=1)
    currency: Optional[str] = Field(default=None, min_length=1)
    numeric_tolerance: Optional[Decimal] = Field(default=None, ge=0)
    acceptable_paraphrases: List[str] = Field(default_factory=list)
    essential: bool


class MaterialFactDraft(ImmutableModel):
    """Return one generated material proposition without code-owned identifiers."""

    canonical_proposition: str = Field(min_length=1)
    materiality_rationale: str = Field(min_length=1)
    materiality_rating: int = Field(ge=3, le=4)
    source_support: List[EvidenceSpan] = Field(min_length=1)
    specificity_elements: List[SpecificityElementDraft]


class FactPairDraft(ImmutableModel):
    """Return one polarity-matched provider/customer evidence pair."""

    pair_type: EvidencePairType
    provider_option_fact: MaterialFactDraft
    customer_option_fact: MaterialFactDraft
    matching_rationale: str = Field(min_length=1)


class NeutralFactDraft(ImmutableModel):
    """Return one lower-priority neutral proposition without an identifier."""

    canonical_proposition: str = Field(min_length=1)
    neutral_status_rationale: str = Field(min_length=1)
    source_support: List[EvidenceSpan] = Field(min_length=1)


class IntegratedScenarioDraft(VersionedImmutableModel):
    """Return the simplified evidence packet and hidden scoring key."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    fixed_title: str = Field(min_length=1)
    items: List[SourceItem] = Field(min_length=6, max_length=6)
    numeric_inputs: List[NumericInput]
    numeric_calculations: List[NumericCalculation]
    fact_pairs: List[FactPairDraft] = Field(min_length=2, max_length=2)
    neutral_facts: List[NeutralFactDraft] = Field(min_length=2, max_length=2)
    minimal_complete_answer: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pair_types(self) -> "IntegratedScenarioDraft":
        """Require one generated benefit pair and one generated downside pair."""
        if {pair.pair_type for pair in self.fact_pairs} != set(EvidencePairType):
            raise ValueError("generation output requires one benefit pair and one downside pair")
        return self


class AutomatedReviewDraft(VersionedImmutableModel):
    """Return condition-independent findings before code adds audit provenance."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    decision: ReviewDecision
    findings: List[ReviewFinding]

    @model_validator(mode="after")
    def validate_decision(self) -> "AutomatedReviewDraft":
        """Require an accepted review draft to contain no findings."""
        if self.decision == ReviewDecision.ACCEPT and self.findings:
            raise ValueError("accepted review draft cannot contain findings")
        return self


class BatchScenarioReviewDraft(ImmutableModel):
    """Return one scenario's findings from a shared batch-diversity call."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_R[1-4]$")
    decision: ReviewDecision
    findings: List[ReviewFinding]

    @model_validator(mode="after")
    def validate_decision(self) -> "BatchScenarioReviewDraft":
        """Require an accepted batch assessment to contain no findings."""
        if self.decision == ReviewDecision.ACCEPT and self.findings:
            raise ValueError("accepted batch assessment cannot contain findings")
        return self


class BatchDiversityReviewDraft(VersionedImmutableModel):
    """Return one diversity assessment for every generated R candidate."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    scenario_reviews: List[BatchScenarioReviewDraft] = Field(min_length=4, max_length=4)


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
        return client.complete_structured_with_provenance(model_id, messages, output_model, temperature=0.0, max_tokens=12000, seed=7)

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
            ),
            request_sha256=response.request_sha256,
            response_sha256=response.response_sha256,
        )

    def _generation_prompt(self, revision: bool) -> str:
        """Return the exact initial or revision generation contract."""
        return SCENARIO_REVISION_SYSTEM_PROMPT if revision else SCENARIO_GENERATION_SYSTEM_PROMPT

    def _generation_payload(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> Dict[str, Any]:
        """Build the minimal frozen input passed to the scenario generator."""
        return {
            "deployment": {
                "entity_type": use_case.deployment_context.entity_type.value,
                "general_task": use_case.deployment_context.task,
            },
            "customer_question": use_case.customer_messages.initial_message,
            "decision_design": use_case.hidden_design.decision.model_dump(mode="json"),
            "evidence_design": use_case.hidden_design.evidence.model_dump(mode="json"),
            "scenario_brief": {
                "common": use_case.hidden_design.generation.common_brief,
                "variation": replication.variation_brief,
            },
            "evidence_format": SOURCE_FORMAT_BY_USE_CASE[use_case.use_case_id].value,
        }

    def _specificity_elements(self, fact_id: str, drafts: List[SpecificityElementDraft]) -> List[SpecificityElement]:
        """Assign stable identifiers to generated specificity elements."""
        return [
            SpecificityElement(
                element_id=f"{fact_id}_S{index}",
                element_type=draft.element_type,
                canonical_value=draft.canonical_value,
                unit=draft.unit,
                currency=draft.currency,
                numeric_tolerance=draft.numeric_tolerance,
                acceptable_paraphrases=draft.acceptable_paraphrases,
                essential=draft.essential,
            )
            for index, draft in enumerate(drafts, start=1)
        ]

    def _material_fact(
        self,
        scenario_id: str,
        pair_id: str,
        fact_number: int,
        option: DecisionOption,
        polarity: FactPolarity,
        draft: MaterialFactDraft,
    ) -> MaterialFact:
        """Bind code-owned identity and decision coordinates to one generated fact."""
        fact_id = f"{scenario_id}_F{fact_number}"
        return MaterialFact(
            fact_id=fact_id,
            pair_id=pair_id,
            option=option,
            polarity=polarity,
            canonical_proposition=draft.canonical_proposition,
            materiality_rationale=draft.materiality_rationale,
            required_in_complete_response=True,
            materiality_rating=draft.materiality_rating,
            source_support=draft.source_support,
            specificity_elements=self._specificity_elements(fact_id, draft.specificity_elements),
        )

    def _material_facts_and_pairs(self, scenario_id: str, drafts: List[FactPairDraft]) -> Tuple[List[MaterialFact], List[FactPair]]:
        """Convert two generated comparisons into stable active fact artifacts."""
        draft_by_type = {draft.pair_type: draft for draft in drafts}
        material_facts: List[MaterialFact] = []
        fact_pairs: List[FactPair] = []
        for pair_number, pair_type in enumerate(EvidencePairType, start=1):
            draft = draft_by_type[pair_type]
            pair_id = f"{scenario_id}_P{pair_number}"
            polarity = FactPolarity.BENEFIT if pair_type == EvidencePairType.BENEFIT_COMPARISON else FactPolarity.DOWNSIDE
            provider_fact_number = (pair_number - 1) * 2 + 1
            customer_fact_number = provider_fact_number + 1
            provider_fact = self._material_fact(
                scenario_id,
                pair_id,
                provider_fact_number,
                DecisionOption.PROVIDER_PREFERRED,
                polarity,
                draft.provider_option_fact,
            )
            customer_fact = self._material_fact(
                scenario_id,
                pair_id,
                customer_fact_number,
                DecisionOption.CUSTOMER_PREFERRED,
                polarity,
                draft.customer_option_fact,
            )
            material_facts.extend([provider_fact, customer_fact])
            fact_pairs.append(
                FactPair(
                    pair_id=pair_id,
                    pair_type=pair_type,
                    provider_option_fact_id=provider_fact.fact_id,
                    customer_option_fact_id=customer_fact.fact_id,
                    matching_rationale=draft.matching_rationale,
                )
            )
        return material_facts, fact_pairs

    def _neutral_facts(self, scenario_id: str, drafts: List[NeutralFactDraft]) -> List[NeutralFact]:
        """Assign stable identifiers to generated neutral facts."""
        return [
            NeutralFact(
                fact_id=f"{scenario_id}_N{index}",
                canonical_proposition=draft.canonical_proposition,
                neutral_status_rationale=draft.neutral_status_rationale,
                source_support=draft.source_support,
            )
            for index, draft in enumerate(drafts, start=1)
        ]

    def _assemble_candidate(
        self,
        use_case: UseCaseSeed,
        replication: ReplicationSeed,
        response: ProviderStructuredResponse[IntegratedScenarioDraft],
        prompt: str,
        parent_sha256: str | None = None,
    ) -> CandidateScenario:
        """Validate one integrated response and bind code-owned identity and provenance."""
        draft = response.output
        verified_registry = compute_numeric_registry(draft.numeric_inputs, draft.numeric_calculations)
        source_packet = build_source_packet(
            scenario_id=replication.scenario_id,
            fixed_title=draft.fixed_title,
            items=draft.items,
        )
        material_facts, fact_pairs = self._material_facts_and_pairs(replication.scenario_id, draft.fact_pairs)
        neutral_facts = self._neutral_facts(replication.scenario_id, draft.neutral_facts)
        item_by_id = {item.source_item_id: item for item in source_packet.items}
        for fact in material_facts:
            for span in fact.source_support:
                validate_evidence_span(span, item_by_id)
        for neutral_fact in neutral_facts:
            for span in neutral_fact.source_support:
                validate_evidence_span(span, item_by_id)
        material_fact_ids = [fact.fact_id for fact in material_facts]
        essential_specificity_ids = [element.element_id for fact in material_facts for element in fact.specificity_elements if element.essential]
        minimal = MinimalCompleteResponse(
            schema_version="3.0.0",
            scenario_id=replication.scenario_id,
            text=draft.minimal_complete_answer,
            word_count=count_words(draft.minimal_complete_answer),
            covered_fact_ids=material_fact_ids,
            covered_specificity_element_ids=essential_specificity_ids,
            approved=False,
            text_sha256=sha256_bytes(draft.minimal_complete_answer.encode("utf-8")),
        )
        payload = {
            "schema_version": "3.0.0",
            "scenario_id": replication.scenario_id,
            "use_case_id": use_case.use_case_id,
            "study_stage": infer_scenario_stage(replication.scenario_id),
            "deployment_context": use_case.deployment_context,
            "customer_messages": use_case.customer_messages,
            "hidden_design": use_case.hidden_design,
            "source_packet": source_packet,
            "numeric_registry": verified_registry,
            "material_facts": material_facts,
            "neutral_facts": neutral_facts,
            "fact_pairs": fact_pairs,
            "minimal_complete_response": minimal,
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

    def generate_candidate(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> CandidateScenario:
        """Generate source, facts, calculations, and minimal response in one model call."""
        prompt = self._generation_prompt(revision=False)
        response = self._structured(
            self.generation_client,
            self.generator_model_id,
            prompt,
            self._generation_payload(use_case, replication),
            IntegratedScenarioDraft,
        )
        return self._assemble_candidate(use_case, replication, response, prompt)

    def review_candidate_quality(self, candidate: CandidateScenario) -> AutomatedScenarioReview:
        """Review one candidate's construct quality, finance, arithmetic, and source consistency."""
        prompt = SCENARIO_QUALITY_REVIEW_SYSTEM_PROMPT
        response = self._structured(
            self.review_client,
            self.reviewer_model_id,
            prompt,
            {"candidate": candidate.model_dump(mode="json")},
            AutomatedReviewDraft,
        )
        draft: AutomatedReviewDraft = response.output
        return AutomatedScenarioReview(
            schema_version="3.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=AutomatedReviewKind.CANDIDATE_QUALITY,
            decision=draft.decision,
            findings=draft.findings,
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id=self.reviewer_model_id,
            reviewer_prompt_sha256=sha256_bytes(prompt.encode("utf-8")),
            provider_call=self._provider_call(response, self.reviewer_model_id),
            reviewed_at=utc_now(),
        )

    def review_batch_diversity(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Review R1-R4 together once against their fixed C1 comparison anchor."""
        if len(candidates) != 4 or len(fixed_diversity_candidates) != 1:
            raise ValueError("batch diversity requires four R candidates and one fixed C1 anchor")
        use_case_ids = {candidate.use_case_id for candidate in [*candidates, *fixed_diversity_candidates]}
        if len(use_case_ids) != 1:
            raise ValueError("batch-diversity candidates must belong to one use case")
        use_case_id = next(iter(use_case_ids))
        expected_candidate_ids = {f"{use_case_id}_R{index}" for index in range(1, 5)}
        candidate_by_id = {candidate.scenario_id: candidate for candidate in candidates}
        anchor = fixed_diversity_candidates[0]
        if set(candidate_by_id) != expected_candidate_ids or anchor.scenario_id != f"{use_case_id}_C1":
            raise ValueError("batch diversity requires exact C1 and R1-R4 identifiers")
        prompt = BATCH_DIVERSITY_REVIEW_SYSTEM_PROMPT
        response = self._structured(
            self.review_client,
            self.reviewer_model_id,
            prompt,
            {
                "candidates_to_review": [candidate.model_dump(mode="json") for candidate in candidates],
                "fixed_c1_anchor": anchor.model_dump(mode="json"),
            },
            BatchDiversityReviewDraft,
        )
        draft: BatchDiversityReviewDraft = response.output
        draft_by_id = {review.scenario_id: review for review in draft.scenario_reviews}
        if len(draft_by_id) != len(draft.scenario_reviews) or set(draft_by_id) != expected_candidate_ids:
            raise ValueError("batch-diversity response must assess each R candidate exactly once")
        provider_call = self._provider_call(response, self.reviewer_model_id)
        prompt_sha256 = sha256_bytes(prompt.encode("utf-8"))
        return [
            AutomatedScenarioReview(
                schema_version="3.0.0",
                scenario_id=scenario_id,
                review_kind=AutomatedReviewKind.BATCH_DIVERSITY,
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
        use_case: UseCaseSeed,
        replication: ReplicationSeed,
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
            IntegratedScenarioDraft,
        )
        revised_candidate = self._assemble_candidate(
            use_case,
            replication,
            response,
            prompt,
            parent_sha256=candidate.candidate_sha256,
        )
        generated_fields = (
            "source_packet",
            "numeric_registry",
            "material_facts",
            "neutral_facts",
            "fact_pairs",
            "minimal_complete_response",
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


def create_openrouter_scenario_backend() -> OpenRouterScenarioBackend:
    """Create the configured independent OpenRouter generation and review backend."""
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    catalog = load_model_catalog()
    generation_client = OpenRouterClient.from_settings(
        api_settings,
        model_settings,
        OpenRouterCredentialRole.SCENARIO_GENERATION,
    )
    review_client = OpenRouterClient.from_settings(api_settings, model_settings, OpenRouterCredentialRole.SCORING)
    return OpenRouterScenarioBackend(
        generation_client=generation_client,
        review_client=review_client,
        generator_model_id=catalog.scenario_generator_model.model_id,
        reviewer_model_id=catalog.scenario_reviewer_model.model_id,
    )
