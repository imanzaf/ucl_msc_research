"""OpenRouter implementation of integrated scenario generation and review."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple, Type, TypeVar

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
    FinanceEntityType,
    MaterialFact,
    SourceItem,
    SourceOptionId,
    SourceOptionRecordDesign,
    V09ReplicationSeed,
    V09UseCaseSeed,
    infer_scenario_stage,
)
from src.experiments.model_catalog import load_model_catalog
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.paths import ACTIVE_SCENARIO_GENERATION_ROOT
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT, SCENARIO_REVIEW_SYSTEM_PROMPT, SCENARIO_REVISION_SYSTEM_PROMPT
from src.scenarios.rendering_templates import SOURCE_FORMAT_BY_USE_CASE, SourceFormat
from src.scenarios.source_rendering import build_source_packet, validate_evidence_span
from src.settings.api_settings import OpenRouterCredentialRole, get_api_settings
from src.settings.model_settings import get_model_settings

StructuredT = TypeVar("StructuredT", bound=BaseModel)
STRUCTURED_MAX_OUTPUT_TOKENS = 6_000


class GenerationDeploymentInput(ImmutableModel):
    """Provide only the broad deployment details needed to draft realistic evidence."""

    entity_type: FinanceEntityType
    general_task: str = Field(min_length=1, pattern=r"\S")


class GenerationSourceDesignInput(ImmutableModel):
    """Provide the seed-owned option and comparison specification without replications."""

    decision_topic: str = Field(min_length=1, pattern=r"\S")
    option_records: List[SourceOptionRecordDesign] = Field(min_length=2, max_length=2)
    common_comparison_basis: str = Field(min_length=1, pattern=r"\S")

    @model_validator(mode="after")
    def validate_option_ids(self) -> "GenerationSourceDesignInput":
        """Require exactly one input record for each neutral option."""
        if {record.option_id for record in self.option_records} != set(SourceOptionId):
            raise ValueError("generation input requires exactly OPTION_A and OPTION_B")
        return self


class ScenarioGenerationInput(ImmutableModel):
    """Define the exact condition-blind payload sent to the scenario generator."""

    deployment: GenerationDeploymentInput
    source_generation: GenerationSourceDesignInput
    replication_variation: str = Field(min_length=1, pattern=r"\S")
    evidence_format: SourceFormat


class GeneratedFactDraft(ImmutableModel):
    """Return one canonical option fact before drafting its visible evidence item."""

    option_id: SourceOptionId
    polarity: FactPolarity
    text: str = Field(min_length=1, pattern=r"\S")


class EvidenceItemDraft(ImmutableModel):
    """Return one natural evidence item corresponding to a generated fact."""

    option_id: SourceOptionId
    polarity: FactPolarity
    text: str = Field(min_length=1, pattern=r"\S")


def _fact_cells(items: List[GeneratedFactDraft] | List[EvidenceItemDraft]) -> set[Tuple[SourceOptionId, FactPolarity]]:
    """Return the option-by-polarity cells represented by generated items."""
    return {(item.option_id, item.polarity) for item in items}


class IntegratedScenarioDraft(VersionedImmutableModel):
    """Return canonical facts first, followed by their natural visible evidence items."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    facts: List[GeneratedFactDraft] = Field(min_length=4, max_length=4)
    evidence_items: List[EvidenceItemDraft] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_cells(self) -> "IntegratedScenarioDraft":
        """Require one canonical fact and evidence item for every option-by-polarity cell."""
        expected_cells = {(option_id, polarity) for option_id in SourceOptionId for polarity in FactPolarity}
        if _fact_cells(self.facts) != expected_cells or _fact_cells(self.evidence_items) != expected_cells:
            raise ValueError("generation output requires one fact and one evidence item for every option-by-polarity cell")
        return self


class ScenarioReviewDraft(ImmutableModel):
    """Return one candidate decision from a semantic review call."""

    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[1-4])$")
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
    scenario_reviews: List[ScenarioReviewDraft] = Field(min_length=1, max_length=4)


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
            ),
            request_sha256=response.request_sha256,
            response_sha256=response.response_sha256,
            response_repaired=response.response_repaired,
        )

    def _generation_prompt(self, revision: bool) -> str:
        """Return the exact initial or revision generation contract."""
        return SCENARIO_REVISION_SYSTEM_PROMPT if revision else SCENARIO_GENERATION_SYSTEM_PROMPT

    def _generation_payload(self, use_case: V09UseCaseSeed, replication: V09ReplicationSeed) -> Dict[str, Any]:
        """Pass only visible-source requirements, never the hidden research interpretation."""
        source_design = use_case.hidden_design.source_generation
        payload = ScenarioGenerationInput(
            deployment=GenerationDeploymentInput(
                entity_type=use_case.deployment_context.entity_type,
                general_task=use_case.deployment_context.task,
            ),
            source_generation=GenerationSourceDesignInput(
                decision_topic=source_design.decision_topic,
                option_records=source_design.option_records,
                common_comparison_basis=source_design.common_comparison_basis,
            ),
            replication_variation=replication.variation_brief,
            evidence_format=SOURCE_FORMAT_BY_USE_CASE[use_case.use_case_id],
        )
        return payload.model_dump(mode="json")

    def _fact_label(self, record: SourceOptionRecordDesign, polarity: FactPolarity) -> str:
        """Return the seed-owned neutral display label for one option fact."""
        return record.benefit_fact_label if polarity == FactPolarity.BENEFIT else record.downside_fact_label

    def _source_items(
        self,
        use_case: V09UseCaseSeed,
        replication: V09ReplicationSeed,
        draft: IntegratedScenarioDraft,
    ) -> List[SourceItem]:
        """Render natural evidence items in the scenario's frozen option order."""
        record_designs = {record.option_id: record for record in use_case.hidden_design.source_generation.option_records}
        evidence_by_cell = {(item.option_id, item.polarity): item for item in draft.evidence_items}
        items: List[SourceItem] = []
        for option_id in replication.presentation_order:
            design = record_designs[option_id]
            for polarity in FactPolarity:
                evidence = evidence_by_cell[(option_id, polarity)]
                items.append(
                    SourceItem(
                        source_item_id=f"{option_id.value}_{polarity.value.upper()}",
                        header=f"{design.option_name} — {self._fact_label(design, polarity)}",
                        body=evidence.text,
                    )
                )
        return items

    def _full_item_span(self, item: SourceItem) -> EvidenceSpan:
        """Use a generated simple fact's complete body as its exact support span."""
        return EvidenceSpan(
            source_item_id=item.source_item_id,
            start_char=0,
            end_char=len(item.body),
            exact_text=item.body,
        )

    def _material_facts_and_pairs(
        self,
        use_case: V09UseCaseSeed,
        scenario_id: str,
        draft: IntegratedScenarioDraft,
        item_by_id: Dict[str, SourceItem],
    ) -> Tuple[List[MaterialFact], List[FactPair]]:
        """Map neutral option facts to hidden decision coordinates after generation."""
        generated_facts = {(fact.option_id, fact.polarity): fact for fact in draft.facts}
        decision = use_case.hidden_design.research.decision
        evidence_by_type = {pair.pair_type: pair for pair in use_case.hidden_design.research.evidence.pairs}
        option_mapping = {
            DecisionOption.PROVIDER_PREFERRED: decision.provider_preferred_option,
            DecisionOption.CUSTOMER_PREFERRED: decision.customer_preferred_option,
        }
        material_facts: List[MaterialFact] = []
        fact_pairs: List[FactPair] = []
        for pair_number, pair_type in enumerate(EvidencePairType, start=1):
            polarity = FactPolarity.BENEFIT if pair_type == EvidencePairType.BENEFIT_COMPARISON else FactPolarity.DOWNSIDE
            pair_id = f"{scenario_id}_P{pair_number}"
            pair_fact_ids: Dict[DecisionOption, str] = {}
            for offset, option in enumerate(DecisionOption):
                option_id = option_mapping[option]
                option_fact = generated_facts[(option_id, polarity)]
                source_item = item_by_id[f"{option_id.value}_{polarity.value.upper()}"]
                fact_id = f"{scenario_id}_F{(pair_number - 1) * 2 + offset + 1}"
                evidence_brief = evidence_by_type[pair_type]
                theme = evidence_brief.option_a_theme if option_id == SourceOptionId.OPTION_A else evidence_brief.option_b_theme
                material_facts.append(
                    MaterialFact(
                        fact_id=fact_id,
                        pair_id=pair_id,
                        option=option,
                        polarity=polarity,
                        canonical_proposition=option_fact.text,
                        materiality_rationale=theme,
                        required_in_complete_response=True,
                        materiality_rating=4,
                        source_support=[self._full_item_span(source_item)],
                    )
                )
                pair_fact_ids[option] = fact_id
            fact_pairs.append(
                FactPair(
                    pair_id=pair_id,
                    pair_type=pair_type,
                    provider_option_fact_id=pair_fact_ids[DecisionOption.PROVIDER_PREFERRED],
                    customer_option_fact_id=pair_fact_ids[DecisionOption.CUSTOMER_PREFERRED],
                    matching_rationale=evidence_by_type[pair_type].matching_requirements,
                )
            )
        return material_facts, fact_pairs

    def _fixed_source_title(self, use_case: V09UseCaseSeed, replication: V09ReplicationSeed) -> str:
        """Build a source heading in the scenario's frozen option order."""
        records = {record.option_id: record for record in use_case.hidden_design.source_generation.option_records}
        return " / ".join(records[option_id].option_name for option_id in replication.presentation_order)

    def _assemble_candidate(
        self,
        use_case: V09UseCaseSeed,
        replication: V09ReplicationSeed,
        response: ProviderStructuredResponse[IntegratedScenarioDraft],
        prompt: str,
        parent_sha256: str | None = None,
    ) -> CandidateScenario:
        """Build the candidate from generated facts and natural evidence items."""
        draft = response.output
        source_items = self._source_items(use_case, replication, draft)
        source_packet = build_source_packet(
            scenario_id=replication.scenario_id,
            fixed_title=self._fixed_source_title(use_case, replication),
            items=source_items,
        )
        item_by_id = {item.source_item_id: item for item in source_packet.items}
        material_facts, fact_pairs = self._material_facts_and_pairs(use_case, replication.scenario_id, draft, item_by_id)
        for fact in material_facts:
            for span in fact.source_support:
                validate_evidence_span(span, item_by_id)
        payload = {
            "schema_version": "3.0.0",
            "scenario_id": replication.scenario_id,
            "use_case_id": use_case.use_case_id,
            "study_stage": infer_scenario_stage(replication.scenario_id),
            "deployment_context": use_case.deployment_context,
            "customer_messages": use_case.customer_messages,
            "hidden_design": use_case.hidden_design,
            "source_packet": source_packet,
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

    def generate_candidate(self, use_case: V09UseCaseSeed, replication: V09ReplicationSeed) -> CandidateScenario:
        """Generate a visible evidence packet and simple fact lists in one model call."""
        prompt = self._generation_prompt(revision=False)
        response = self._structured(
            self.generation_client,
            self.generator_model_id,
            prompt,
            self._generation_payload(use_case, replication),
            IntegratedScenarioDraft,
        )
        return self._assemble_candidate(use_case, replication, response, prompt)

    def review_candidates(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Review one C1 or a complete R1-R4 batch with the shared semantic contract."""
        candidate_by_id = {candidate.scenario_id: candidate for candidate in candidates}
        if len(candidate_by_id) != len(candidates):
            raise ValueError("scenario review candidates must have unique identifiers")
        is_calibration_review = len(candidates) == 1 and candidates[0].scenario_id.endswith("_C1")
        if is_calibration_review:
            if fixed_diversity_candidates:
                raise ValueError("C1 semantic review must not include a diversity anchor")
            payload = {"candidates_to_review": [candidates[0].model_dump(mode="json")]}
        else:
            if len(candidates) != 4 or len(fixed_diversity_candidates) != 1:
                raise ValueError("evaluation semantic review requires R1-R4 and one fixed C1 anchor")
            use_case_ids = {candidate.use_case_id for candidate in [*candidates, *fixed_diversity_candidates]}
            if len(use_case_ids) != 1:
                raise ValueError("evaluation review candidates must belong to one use case")
            use_case_id = next(iter(use_case_ids))
            expected_candidate_ids = {f"{use_case_id}_R{index}" for index in range(1, 5)}
            anchor = fixed_diversity_candidates[0]
            if set(candidate_by_id) != expected_candidate_ids or anchor.scenario_id != f"{use_case_id}_C1":
                raise ValueError("evaluation semantic review requires exact C1 and R1-R4 identifiers")
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
        use_case: V09UseCaseSeed,
        replication: V09ReplicationSeed,
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


def create_openrouter_scenario_backend() -> OpenRouterScenarioBackend:
    """Create the configured independent OpenRouter generation and review backend."""
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    catalog = load_model_catalog()
    generation_client = OpenRouterClient.from_settings(
        api_settings,
        model_settings,
        OpenRouterCredentialRole.SCENARIO_GENERATION,
        structured_log_dir=ACTIVE_SCENARIO_GENERATION_ROOT / "raw_provider" / "generation",
    )
    review_client = OpenRouterClient.from_settings(
        api_settings,
        model_settings,
        OpenRouterCredentialRole.SCORING,
        structured_log_dir=ACTIVE_SCENARIO_GENERATION_ROOT / "raw_provider" / "review",
    )
    return OpenRouterScenarioBackend(
        generation_client=generation_client,
        review_client=review_client,
        generator_model_id=catalog.scenario_generator_model.model_id,
        reviewer_model_id=catalog.scenario_reviewer_model.model_id,
    )
