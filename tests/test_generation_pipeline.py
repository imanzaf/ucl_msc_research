"""Test deterministic arithmetic, exact spans, rebuild reviews, and revision caps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Tuple, cast

import pytest

from src.data_models.common import artifact_sha256, utc_now
from src.data_models.experiments import CompletionFinishReason
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    FindingSeverity,
    ReviewDecision,
    ReviewFinding,
)
from src.data_models.scenarios import CandidateScenario, NumericCalculation, NumericInput, NumericOperation, ReplicationSeed, UseCaseSeed
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT
from src.scenarios.numeric_engine import compute_numeric_registry
from src.scenarios.openrouter_backend import (
    FactPairDraft,
    IntegratedScenarioDraft,
    MaterialFactDraft,
    NeutralFactDraft,
    OpenRouterScenarioBackend,
    SpecificityElementDraft,
)
from src.scenarios.pipeline import default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.scenarios.source_rendering import build_source_packet, validate_evidence_span
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]


class IntegratedGenerationClient:
    """Return one complete fixture draft while recording exact generation requests."""

    def __init__(self, draft: IntegratedScenarioDraft) -> None:
        """Store the integrated response and initialise request capture."""
        self.draft = draft
        self.messages: List[List[dict[str, str]]] = []

    def complete_structured_with_provenance(self, model_id: str, messages: List[dict[str, str]], *args: Any, **kwargs: Any) -> Any:
        """Return the configured integrated draft with valid provider provenance."""
        self.messages.append(messages)
        return ProviderStructuredResponse[IntegratedScenarioDraft](
            output=self.draft,
            provider_request_id="generation-request",
            returned_model_version="generator@snapshot",
            input_tokens=100,
            output_tokens=200,
            finish_reason=CompletionFinishReason.STOP,
            request_sha256=ZERO_HASH,
            response_sha256=ZERO_HASH,
        )


def make_integrated_draft() -> IntegratedScenarioDraft:
    """Build one complete response containing source, facts, arithmetic, and feasibility text."""
    candidate = make_candidate_scenario()
    inputs = [
        NumericInput(value_id="OLD", value="100", unit="GBP", source_note="fixture"),
        NumericInput(value_id="NEW", value="125", unit="GBP", source_note="fixture"),
    ]
    calculation = NumericCalculation(
        output_value_id="CHANGE",
        operation=NumericOperation.PERCENTAGE_CHANGE,
        operand_value_ids=["OLD", "NEW"],
        decimal_places=1,
        expected_unit="percent",
    )
    items = list(candidate.source_packet.items)
    items[0] = items[0].model_copy(update={"numeric_value_ids": ["OLD", "NEW", "CHANGE"]})
    fact_by_id = {fact.fact_id: fact for fact in candidate.material_facts}
    fact_pair_drafts = []
    for pair in candidate.fact_pairs:
        provider = fact_by_id[pair.provider_option_fact_id]
        customer = fact_by_id[pair.customer_option_fact_id]

        def fact_draft(fact: Any) -> MaterialFactDraft:
            """Remove code-owned identifiers from one fixture fact."""
            return MaterialFactDraft(
                canonical_proposition=fact.canonical_proposition,
                materiality_rationale=fact.materiality_rationale,
                materiality_rating=fact.materiality_rating,
                source_support=fact.source_support,
                specificity_elements=[
                    SpecificityElementDraft(
                        element_type=element.element_type,
                        canonical_value=element.canonical_value,
                        unit=element.unit,
                        currency=element.currency,
                        numeric_tolerance=element.numeric_tolerance,
                        acceptable_paraphrases=element.acceptable_paraphrases,
                        essential=element.essential,
                    )
                    for element in fact.specificity_elements
                ],
            )

        fact_pair_drafts.append(
            FactPairDraft(
                pair_type=pair.pair_type,
                provider_option_fact=fact_draft(provider),
                customer_option_fact=fact_draft(customer),
                matching_rationale=pair.matching_rationale,
            )
        )
    return IntegratedScenarioDraft(
        schema_version="3.0.0",
        fixed_title=candidate.source_packet.fixed_title,
        items=items,
        numeric_inputs=inputs,
        numeric_calculations=[calculation],
        fact_pairs=fact_pair_drafts,
        neutral_facts=[
            NeutralFactDraft(
                canonical_proposition=fact.canonical_proposition,
                neutral_status_rationale=fact.neutral_status_rationale,
                source_support=fact.source_support,
            )
            for fact in candidate.neutral_facts
        ],
        minimal_complete_answer=candidate.minimal_complete_response.text,
    )


class AlwaysReviseBackend:
    """Fake backend that proves stage-relevant reviews rerun until the two-cycle cap."""

    def __init__(self) -> None:
        """Create a backend with a stable accepted-scenario-derived candidate."""
        self.candidate = make_candidate_scenario()

    def generate_candidate(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> CandidateScenario:
        """Return the integrated fixture candidate."""
        return self.candidate

    def review_candidate_quality(self, candidate: CandidateScenario) -> AutomatedScenarioReview:
        """Return one quality finding so the candidate always requests revision."""
        finding = ReviewFinding(
            finding_id="CANDIDATE_QUALITY_1",
            severity=FindingSeverity.MAJOR,
            artifact_path="candidate.json",
            field_path="source_packet.fixed_title",
            message="Needs revision.",
            evidence="Fixture evidence.",
            suggested_action="Revise the field.",
        )
        return AutomatedScenarioReview(
            schema_version="3.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=AutomatedReviewKind.CANDIDATE_QUALITY,
            decision=ReviewDecision.REVISE,
            findings=[finding],
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id="independent/reviewer",
            reviewer_prompt_sha256=ZERO_HASH,
            reviewed_at=utc_now(),
        )

    def review_batch_diversity(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Accept batch diversity while the quality contract drives revision."""
        return [
            AutomatedScenarioReview(
                schema_version="3.0.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.BATCH_DIVERSITY,
                decision=ReviewDecision.ACCEPT,
                findings=[],
                reviewed_artifact_sha256=candidate.candidate_sha256,
                reviewer_model_id="independent/reviewer",
                reviewer_prompt_sha256=ZERO_HASH,
                reviewed_at=utc_now(),
            )
            for candidate in candidates
        ]

    def revise_candidate(
        self,
        use_case: UseCaseSeed,
        replication: ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Change the canonical title and return a controlled revision record input."""
        revised_source = build_source_packet(
            candidate.scenario_id,
            f"Revision {cycle_number}",
            candidate.source_packet.items,
        )
        payload = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
        payload["source_packet"] = revised_source.model_dump(mode="json")
        revised = CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})
        return revised, [
            ControlledFieldChange(
                field_path="source_packet",
                previous_value_sha256=ZERO_HASH,
                revised_value_sha256=ZERO_HASH,
                reason="Resolve all fixture findings.",
                finding_ids=[finding.finding_id for review in reviews for finding in review.findings],
            )
        ]


class BatchAcceptBackend:
    """Accept candidates while recording each shared diversity-review batch."""

    def __init__(self) -> None:
        """Initialise observed batch membership."""
        self.observed_batches: List[List[str]] = []

    def generate_candidate(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> CandidateScenario:
        """Build a valid integrated candidate for the requested replication."""
        return make_candidate_scenario(replication.scenario_id)

    def review_candidate_quality(self, candidate: CandidateScenario) -> AutomatedScenarioReview:
        """Accept one candidate's combined quality review."""
        return AutomatedScenarioReview(
            schema_version="3.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=AutomatedReviewKind.CANDIDATE_QUALITY,
            decision=ReviewDecision.ACCEPT,
            findings=[],
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id="independent/reviewer",
            reviewer_prompt_sha256=ZERO_HASH,
            reviewed_at=utc_now(),
        )

    def review_batch_diversity(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Record one complete R batch plus its C1 anchor and accept every R candidate."""
        self.observed_batches.append(sorted(item.scenario_id for item in [*fixed_diversity_candidates, *candidates]))
        return [
            AutomatedScenarioReview(
                schema_version="3.0.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.BATCH_DIVERSITY,
                decision=ReviewDecision.ACCEPT,
                findings=[],
                reviewed_artifact_sha256=candidate.candidate_sha256,
                reviewer_model_id="independent/reviewer",
                reviewer_prompt_sha256=ZERO_HASH,
                reviewed_at=utc_now(),
            )
            for candidate in candidates
        ]

    def revise_candidate(
        self,
        use_case: UseCaseSeed,
        replication: ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Reject an impossible revision call in this accepting fixture."""
        raise AssertionError("accepted candidates must not enter revision")


def test_numeric_engine_uses_decimal_and_rejects_division_by_zero() -> None:
    """Compute registered arithmetic once and fail loudly on invalid operations."""
    inputs = [
        NumericInput(value_id="OLD", value="100", unit="GBP", source_note="fixture"),
        NumericInput(value_id="NEW", value="125", unit="GBP", source_note="fixture"),
    ]
    calculation = NumericCalculation(
        output_value_id="CHANGE",
        operation=NumericOperation.PERCENTAGE_CHANGE,
        operand_value_ids=["OLD", "NEW"],
        decimal_places=1,
        expected_unit="percent",
    )
    registry = compute_numeric_registry(inputs, [calculation])
    assert str(registry.computed_values[0].value) == "25.0"
    zero = NumericInput(value_id="ZERO", value="0", unit="GBP", source_note="fixture")
    divide = NumericCalculation(
        output_value_id="BAD",
        operation=NumericOperation.DIVIDE,
        operand_value_ids=["OLD", "ZERO"],
        expected_unit="ratio",
    )
    with pytest.raises(ValueError, match="division by zero"):
        compute_numeric_registry([inputs[0], zero], [divide])


def test_openrouter_backend_generates_complete_candidate_in_one_call() -> None:
    """Return source, hidden facts, verified arithmetic, and minimal response together."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.8.0"
    seed = load_and_validate_seed(seed_root / "scenario_generation_seeds.json", seed_root / "scenario_generation_seed_schema.json")
    use_case = cast(UseCaseSeed, seed.use_cases[0])
    replication = next(item for item in use_case.hidden_design.generation.replications if item.scenario_id == "CF001_R1")
    client = IntegratedGenerationClient(make_integrated_draft())
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, client),
        review_client=cast(OpenRouterClient, client),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )

    candidate = backend.generate_candidate(use_case, replication)

    assert len(client.messages) == 1
    request_payload = json.loads(client.messages[0][1]["content"])
    assert set(request_payload) == {
        "deployment",
        "customer_question",
        "decision_design",
        "evidence_design",
        "scenario_brief",
        "evidence_format",
    }
    assert set(request_payload["deployment"]) == {"entity_type", "general_task"}
    assert request_payload["customer_question"] == use_case.customer_messages.initial_message
    assert use_case.customer_messages.follow_up_message not in client.messages[0][1]["content"]
    assert set(request_payload["scenario_brief"]) == {"common", "variation"}
    assert str(candidate.numeric_registry.computed_values[0].value) == "25.0"
    assert len(candidate.provenance.provider_calls) == 1
    assert candidate.material_facts[0].fact_id not in candidate.source_packet.rendered_text


def test_generation_output_excludes_redundant_computed_values() -> None:
    """Let deterministic code, rather than the generator, produce calculated results."""
    draft = make_integrated_draft()
    assert "numeric_registry" not in draft.model_dump(mode="json")
    assert "computed_values" not in draft.model_dump(mode="json")


def test_generation_prompt_requires_a_deployment_native_reference_artifact() -> None:
    """Prevent natural-sounding benchmark prose from replacing a realistic retrieved reference."""
    assert "naturally be available to the deployed assistant" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "using the supplied evidence format" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "not a narrative" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "benchmark vignette" in SCENARIO_GENERATION_SYSTEM_PROMPT


def test_exact_source_span_validation() -> None:
    """Reject a support span whose character bounds do not reproduce exact text."""
    scenario = make_accepted_scenario()
    item_by_id = {item.source_item_id: item for item in scenario.source_packet.items}
    valid = scenario.material_facts[0].source_support[0]
    validate_evidence_span(valid, item_by_id)
    invalid = valid.model_copy(update={"exact_text": "wrong text", "end_char": len("wrong text")})
    with pytest.raises(ValueError, match="invalid exact evidence span"):
        validate_evidence_span(invalid, item_by_id)


def test_pipeline_reruns_all_reviews_and_caps_revision_at_two() -> None:
    """Stop unresolved automation after two complete rebuild/review cycles."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.8.0"
    seed = load_and_validate_seed(seed_root / "scenario_generation_seeds.json", seed_root / "scenario_generation_seed_schema.json")
    use_case = cast(UseCaseSeed, seed.use_cases[0])
    replication = next(item for item in use_case.hidden_design.generation.replications if item.scenario_id == "CF001_R1")
    result = run_scenario_batch_pipeline(
        [(use_case, replication)],
        AlwaysReviseBackend(),
        default_revision_record_factory,
        fixed_diversity_candidates=[make_candidate_scenario("CF001_C1")],
    )[replication.scenario_id]

    assert result.terminal_decision == ReviewDecision.MANUAL_RESTRUCTURE
    assert len(result.revisions) == 2
    assert len(result.reviews) == 6
    assert all(set(record.rerun_review_sha256) == set(AutomatedReviewKind) for record in result.revisions)


def test_batch_diversity_review_receives_all_five_use_case_candidates() -> None:
    """Make the diversity contract compare C1 and R1-R4 together, never one candidate alone."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.8.0"
    seed = load_and_validate_seed(seed_root / "scenario_generation_seeds.json", seed_root / "scenario_generation_seed_schema.json")
    backend = BatchAcceptBackend()
    use_case = cast(UseCaseSeed, seed.use_cases[0])
    calibration_seed = next(item for item in use_case.hidden_design.generation.replications if item.scenario_id.endswith("_C1"))
    calibration_candidate = backend.generate_candidate(use_case, calibration_seed)
    evaluation_seeds = [(use_case, item) for item in use_case.hidden_design.generation.replications if not item.scenario_id.endswith("_C1")]
    results = run_scenario_batch_pipeline(
        evaluation_seeds,
        backend,
        default_revision_record_factory,
        fixed_diversity_candidates=[calibration_candidate],
    )
    expected_ids = {"CF001_C1", "CF001_R1", "CF001_R2", "CF001_R3", "CF001_R4"}
    assert set(results) == expected_ids - {"CF001_C1"}
    assert len(backend.observed_batches) == 1
    assert all(set(batch) == expected_ids for batch in backend.observed_batches)


def test_calibration_candidates_skip_batch_diversity() -> None:
    """Review each C1 for quality without comparing unrelated use cases for diversity."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.8.0"
    seed = load_and_validate_seed(seed_root / "scenario_generation_seeds.json", seed_root / "scenario_generation_seed_schema.json")
    backend = BatchAcceptBackend()
    use_cases = [cast(UseCaseSeed, use_case) for use_case in seed.use_cases]
    calibration_seeds = [
        (
            use_case,
            next(item for item in use_case.hidden_design.generation.replications if item.scenario_id.endswith("_C1")),
        )
        for use_case in use_cases
    ]
    results = run_scenario_batch_pipeline(calibration_seeds, backend, default_revision_record_factory)
    assert len(results) == 10
    assert backend.observed_batches == []
    assert all([review.review_kind for review in result.reviews] == [AutomatedReviewKind.CANDIDATE_QUALITY] for result in results.values())
