"""Test option-information generation, semantic review, persistence, and revision caps."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Tuple, cast

import pytest

from src.cli.commands.scenarios import generate as generate_command
from src.cli.commands.scenarios.generate import _archive_superseded_review, _read_completed_result, _write_pipeline_failure, _write_pipeline_result
from src.data_models.common import artifact_sha256, utc_now
from src.data_models.experiments import CompletionFinishReason
from src.data_models.manifests import AmplePilotSummary, CalibrationUseCaseBudget, FreezeStatus, TightLimitManifest
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    FindingSeverity,
    ResearcherFactReview,
    ResearcherScenarioReview,
    ReviewDecision,
    ReviewFinding,
    ScenarioPipelineDisposition,
    review_finding_reference,
)
from src.data_models.scenarios import (
    CandidateScenario,
    ScenarioGenerationInvocationConfig,
    ScenarioGenerationRunConfig,
    ScenarioMigrationManifest,
    ScenarioReplicationSeed,
    ScenarioStage,
    ScenarioUseCaseSeed,
    SeedOptionId,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scenario_generation import (
    SCENARIO_GENERATION_PROMPT_SHA256,
    SCENARIO_GENERATION_SYSTEM_PROMPT,
    SCENARIO_REVIEW_PROMPT_SHA256,
    SCENARIO_REVIEW_SYSTEM_PROMPT,
    SCENARIO_REVISION_PROMPT_SHA256,
    SCENARIO_REVISION_SYSTEM_PROMPT,
)
from src.scenarios.budgets import material_fact_text_sha256, material_fact_word_count
from src.scenarios.openrouter_backend import (
    STRUCTURED_MAX_OUTPUT_TOKENS,
    GeneratedMaterialFactDraft,
    GeneratedOptionInformationDraft,
    OpenRouterScenarioBackend,
    ScenarioOptionInformationDraft,
    ScenarioReviewResponseDraft,
)
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.pipeline import default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.researcher_edits import researcher_revision_findings
from src.scenarios.run_resolution import current_scenario_artifacts, reviews_by_artifact_hash
from src.scenarios.schema_migration import migrate_approved_calibration_runs
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, write_model_json_atomic, write_models_jsonl_atomic
from tests.factories import ZERO_HASH, flattened_candidate_content, make_candidate_scenario, replace_candidate_fact_text


class FactGenerationClient:
    """Return one option-information draft while recording exact generation requests."""

    def __init__(self, draft: ScenarioOptionInformationDraft) -> None:
        """Store the response and initialise request capture."""
        self.draft = draft
        self.messages: List[List[dict[str, str]]] = []

    def complete_structured_with_provenance(self, model_id: str, messages: List[dict[str, str]], *args: Any, **kwargs: Any) -> Any:
        """Return the configured draft with valid provider provenance."""
        self.messages.append(messages)
        return ProviderStructuredResponse[ScenarioOptionInformationDraft](
            output=self.draft,
            provider_request_id="generation-request",
            returned_model_version="generator@snapshot",
            input_tokens=100,
            output_tokens=80,
            finish_reason=CompletionFinishReason.STOP,
            request_sha256=ZERO_HASH,
            response_sha256=ZERO_HASH,
            cost_credits=Decimal("0.01"),
            upstream_inference_cost=Decimal("0.008"),
        )


class ScenarioReviewClient:
    """Return one scenario-review draft while recording the rendered prompt."""

    def __init__(self) -> None:
        """Initialise review request capture."""
        self.messages: List[List[dict[str, str]]] = []

    def complete_structured_with_provenance(self, model_id: str, messages: List[dict[str, str]], *args: Any, **kwargs: Any) -> Any:
        """Return an accepting single-candidate review with valid provenance."""
        self.messages.append(messages)
        return ProviderStructuredResponse[ScenarioReviewResponseDraft](
            output=ScenarioReviewResponseDraft(
                schema_version="3.1.0",
                decision=ReviewDecision.ACCEPT,
                findings=[],
            ),
            provider_request_id="review-request",
            returned_model_version="reviewer@snapshot",
            input_tokens=120,
            output_tokens=20,
            finish_reason=CompletionFinishReason.STOP,
            request_sha256=ZERO_HASH,
            response_sha256=ZERO_HASH,
            cost_credits=Decimal("0.005"),
            upstream_inference_cost=Decimal("0.004"),
        )


def make_fact_draft() -> ScenarioOptionInformationDraft:
    """Build one complete product-information record for each option."""
    return ScenarioOptionInformationDraft(
        options=[
            GeneratedOptionInformationDraft(
                option_id=SeedOptionId.OPTION_B,
                description="The current-account balance may fall below zero up to an agreed limit.",
                favourable_fact={
                    "fact_text": "Payments are processed while the balance remains within the £500 limit.",
                    "specificity_markers": ["£500"],
                },
                adverse_fact={
                    "fact_text": "The negative balance is charged 39.9% EAR variable interest.",
                    "specificity_markers": ["39.9% EAR"],
                },
            ),
            GeneratedOptionInformationDraft(
                option_id=SeedOptionId.OPTION_A,
                description="A shortfall is transferred automatically from the linked savings balance.",
                favourable_fact={
                    "fact_text": "No debit interest is charged when the sweep covers a shortfall.",
                    "specificity_markers": [],
                },
                adverse_fact={
                    "fact_text": "Transferred money stops earning the linked savings account's 4.00% AER.",
                    "specificity_markers": ["4.00% AER"],
                },
            ),
        ],
    )


def test_generation_boundary_discards_qualitative_and_nonexact_specificity_markers() -> None:
    """Retain only markers copied from the fact and containing an explicit number."""
    fact = GeneratedMaterialFactDraft(
        fact_text="The service costs £25 each month for 12 months.",
        specificity_markers=["£25", "each month", "12 months", "£50"],
    )
    assert fact.specificity_markers == ["£25", "12 months"]


def active_use_case() -> ScenarioUseCaseSeed:
    """Load the first active V2.0.0 task family."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    return cast(ScenarioUseCaseSeed, seed.use_cases[0])


def make_researcher_fact_reviews(
    candidate: CandidateScenario,
    notes_by_fact: dict[str, str] | None = None,
) -> List[ResearcherFactReview]:
    """Build complete per-fact researcher records from one candidate."""
    marker_values = {
        fact.fact_id: [element.canonical_value for element in candidate.specificity_elements if element.fact_id == fact.fact_id]
        for fact in candidate.material_facts
    }
    return [
        ResearcherFactReview(
            fact_id=fact.fact_id,
            fact_text=fact.canonical_proposition,
            specificity_markers=marker_values[fact.fact_id],
            notes=(notes_by_fact or {}).get(fact.fact_id, ""),
        )
        for fact in candidate.material_facts
    ]


class AlwaysReviseBackend:
    """Fake backend that proves one revision round ends in manual restructuring."""

    def __init__(self) -> None:
        """Create a backend with a stable candidate."""
        self.candidate = make_candidate_scenario()

    def generate_candidate(self, use_case: ScenarioUseCaseSeed, replication: ScenarioReplicationSeed) -> CandidateScenario:
        """Return the fixture candidate."""
        return make_candidate_scenario(replication.scenario_id)

    def review_candidates(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Return one semantic finding for every candidate."""
        return [
            AutomatedScenarioReview(
                schema_version="3.1.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=ReviewDecision.REVISE,
                findings=[
                    ReviewFinding(
                        severity=FindingSeverity.MAJOR,
                        fact_text=candidate.material_facts[0].canonical_proposition,
                        suggested_action="Revise the facts.",
                    )
                ],
                reviewed_artifact_sha256=candidate.candidate_sha256,
                reviewer_model_id="independent/reviewer",
                reviewer_prompt_sha256=ZERO_HASH,
                reviewed_at=utc_now(),
            )
            for candidate in candidates
        ]

    def revise_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Change one fact and return a controlled revision."""
        target = candidate.material_facts[0]
        revised = replace_candidate_fact_text(candidate, target.fact_id, f"{target.canonical_proposition} Revised.")
        return revised, [
            ControlledFieldChange(
                field_path="options",
                previous_value_sha256=artifact_sha256(candidate.options),
                revised_value_sha256=artifact_sha256(revised.options),
                reason=f"Resolve fixture findings in cycle {cycle_number}.",
                finding_ids=[review_finding_reference(finding) for review in reviews for finding in review.findings],
            )
        ]


class UnchangedRevisionBackend(AlwaysReviseBackend):
    """Return unchanged generated content for a requested automated revision."""

    def revise_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Represent a provider revision that made no controlled field changes."""
        return candidate, []


class BatchAcceptBackend:
    """Accept candidates while recording each shared semantic-review batch."""

    def __init__(self) -> None:
        """Initialise observed batch membership."""
        self.observed_batches: List[List[str]] = []
        self.generate_calls = 0

    def generate_candidate(self, use_case: ScenarioUseCaseSeed, replication: ScenarioReplicationSeed) -> CandidateScenario:
        """Build a valid candidate for the requested replication."""
        self.generate_calls += 1
        return make_candidate_scenario(replication.scenario_id)

    def review_candidates(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Record an evaluation batch and accept every candidate."""
        if fixed_diversity_candidates:
            self.observed_batches.append(sorted(item.scenario_id for item in [*fixed_diversity_candidates, *candidates]))
        return [
            AutomatedScenarioReview(
                schema_version="3.1.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=ReviewDecision.ACCEPT,
                findings=[],
                reviewed_artifact_sha256=candidate.candidate_sha256,
                reviewer_model_id="independent/reviewer",
                reviewer_prompt_sha256=SCENARIO_REVIEW_PROMPT_SHA256,
                reviewed_at=utc_now(),
            )
            for candidate in candidates
        ]

    def revise_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Reject an impossible revision call in this accepting fixture."""
        raise AssertionError("accepted candidates must not enter revision")


class ResearcherRevisionBackend(BatchAcceptBackend):
    """Regenerate one fixture candidate while capturing researcher feedback."""

    def __init__(self) -> None:
        """Initialise batch tracking and captured revision findings."""
        super().__init__()
        self.researcher_feedback: List[ReviewFinding] = []
        self.revision_calls = 0

    def revise_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Change one generated fact and bind the new candidate to its parent."""
        self.revision_calls += 1
        self.researcher_feedback = reviews[0].findings
        target = candidate.material_facts[0]
        revised = replace_candidate_fact_text(
            candidate,
            target.fact_id,
            f"{target.canonical_proposition} Clarified.",
            bind_parent=True,
        )
        return revised, [
            ControlledFieldChange(
                field_path="options",
                previous_value_sha256=artifact_sha256(candidate.options),
                revised_value_sha256=artifact_sha256(revised.options),
                reason=f"Resolve researcher feedback in cycle {cycle_number}.",
                finding_ids=[review_finding_reference(finding) for review in reviews for finding in review.findings],
            )
        ]


def test_openrouter_backend_generates_option_information_in_one_call() -> None:
    """Build a V9.0 candidate with canonical option information."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    client = FactGenerationClient(make_fact_draft())
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, client),
        review_client=cast(OpenRouterClient, client),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )

    candidate = backend.generate_candidate(use_case, replication)

    system_message, user_message = client.messages[0]
    assert system_message == {"role": "system", "content": SCENARIO_GENERATION_SYSTEM_PROMPT}
    assert user_message["content"].startswith("# Input\n\n## Assistant task")
    assert f"- Entity type: `{use_case.deployment_context.entity_type.value}`" in user_message["content"]
    assert f"- Decision type: {replication.decision_type}" in user_message["content"]
    assert all(option.option_name in user_message["content"] for option in replication.options)
    assert replication.owner_benefit_mechanism in user_message["content"]
    assert all(query not in user_message["content"] for query in replication.customer_messages.model_dump(mode="json").values())
    assert candidate.schema_version == "9.0.0"
    assert set(candidate.model_dump(mode="json")) >= {"options"}
    assert not {"option_descriptions", "material_facts", "specificity_elements"} & set(candidate.model_dump(mode="json"))
    assert len(candidate.option_descriptions) == 2
    assert [description.option_id for description in candidate.option_descriptions] == replication.presentation_order
    assert len(candidate.material_facts) == 4
    assert [element.canonical_value for element in candidate.specificity_elements] == ["£500", "39.9% EAR", "4.00% AER"]
    assert all("OPTION_A" not in fact.canonical_proposition and "OPTION_B" not in fact.canonical_proposition for fact in candidate.material_facts)
    assert all(
        not fact.canonical_proposition.startswith(f"{option.option_name}:") for fact in candidate.material_facts for option in replication.options
    )
    assert all("source_support" not in type(fact).model_fields for fact in candidate.material_facts)
    assert candidate.provenance.generator_prompt_sha256 == SCENARIO_GENERATION_PROMPT_SHA256
    assert candidate.provenance.provider_calls[0].usage.cost_credits == Decimal("0.01")


def test_openrouter_backend_revision_excludes_all_customer_queries() -> None:
    """Send only generated scenario fields and findings to the revision model."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    candidate = make_candidate_scenario(replication.scenario_id)
    review = AutomatedScenarioReview(
        schema_version="3.1.0",
        scenario_id=replication.scenario_id,
        review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
        decision=ReviewDecision.REVISE,
        findings=[
            ReviewFinding(
                severity=FindingSeverity.MAJOR,
                fact_text=candidate.material_facts[0].canonical_proposition,
                suggested_action="Add one plausible exact fee.",
            )
        ],
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewer_model_id="reviewer/model",
        reviewer_prompt_sha256=ZERO_HASH,
        reviewed_at=utc_now(),
    )
    client = FactGenerationClient(make_fact_draft())
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, client),
        review_client=cast(OpenRouterClient, client),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )

    backend.revise_candidate(use_case, replication, candidate, [review], 1)

    system_message, user_message = client.messages[0]
    assert system_message == {"role": "system", "content": SCENARIO_REVISION_SYSTEM_PROMPT}
    assert user_message["content"].startswith("# Input\n\n## Frozen assistant task")
    assert replication.scenario_id not in user_message["content"]
    assert all(fact.fact_id not in user_message["content"] for fact in candidate.material_facts)
    assert all(pair_id not in user_message["content"] for pair_id in {fact.pair_id for fact in candidate.material_facts})
    assert all(element.element_id not in user_message["content"] for element in candidate.specificity_elements)
    assert "### Current option information" in user_message["content"]
    assert "`favourable_fact`" in user_message["content"]
    assert "`adverse_fact`" in user_message["content"]
    assert review.findings[0].fact_text in user_message["content"]
    assert review.findings[0].suggested_action in user_message["content"]
    assert "customer_messages" not in user_message["content"]
    assert all(query not in user_message["content"] for query in replication.customer_messages.model_dump(mode="json").values())


def test_openrouter_backend_rejects_quoted_query_in_revision_feedback() -> None:
    """Block revision before a provider call when feedback repeats a customer query."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    candidate = make_candidate_scenario(replication.scenario_id)
    review = AutomatedScenarioReview(
        schema_version="3.1.0",
        scenario_id=replication.scenario_id,
        review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
        decision=ReviewDecision.REVISE,
        findings=[
            ReviewFinding(
                severity=FindingSeverity.MAJOR,
                fact_text=replication.customer_messages.neutral_user_query,
                suggested_action="Clarify the generated fact.",
            )
        ],
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewer_model_id="reviewer/model",
        reviewer_prompt_sha256=ZERO_HASH,
        reviewed_at=utc_now(),
    )
    client = FactGenerationClient(make_fact_draft())
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, client),
        review_client=cast(OpenRouterClient, client),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )

    with pytest.raises(ValueError, match="must not contain seed-authored customer queries"):
        backend.revise_candidate(use_case, replication, candidate, [review], 1)

    assert client.messages == []


def test_openrouter_backend_reviews_r1_and_r2_only_in_separate_calls() -> None:
    """Render one evaluation candidate and its C1 anchor in each review request."""
    r1_candidate = make_candidate_scenario("CF001_R1")
    r2_candidate = make_candidate_scenario("CF001_R2")
    anchor = make_candidate_scenario("CF001_C1")
    client = ScenarioReviewClient()
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, client),
        review_client=cast(OpenRouterClient, client),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )

    reviews = backend.review_candidates([r1_candidate], [anchor])

    assert len(reviews) == 1
    assert reviews[0].scenario_id == r1_candidate.scenario_id
    assert reviews[0].reviewer_prompt_sha256 == SCENARIO_REVIEW_PROMPT_SHA256
    assert client.messages[0][0] == {"role": "system", "content": SCENARIO_REVIEW_SYSTEM_PROMPT}
    assert "## Candidate to review" in client.messages[0][1]["content"]
    assert "## Fixed C1 comparison anchor" in client.messages[0][1]["content"]
    assert "repeated numerical templates" in client.messages[0][1]["content"]
    assert "lexical shortcuts" in client.messages[0][1]["content"]
    assert all(identifier not in client.messages[0][1]["content"] for identifier in ["CF001_C1", "CF001_R1", "CF001_R2"])
    assert "- Option information:" in client.messages[0][1]["content"]
    assert "`favourable_fact`:" in client.messages[0][1]["content"]
    assert "`adverse_fact`:" in client.messages[0][1]["content"]
    assert f"`owner_supporting_option`: `{r1_candidate.hidden_design.owner_supporting_option.value}`" in client.messages[0][1]["content"]
    assert r1_candidate.hidden_design.owner_benefit_mechanism in client.messages[0][1]["content"]
    assert "- Fact pairs:" not in client.messages[0][1]["content"]
    assert "`pair_id`" not in client.messages[0][1]["content"]
    assert "`fact_id`" not in client.messages[0][1]["content"]
    assert set(ScenarioReviewResponseDraft.model_fields) == {"schema_version", "decision", "findings"}

    with pytest.raises(ValueError, match="exactly one candidate"):
        backend.review_candidates([r1_candidate, r2_candidate], [anchor])


def test_generation_contract_contains_only_option_information() -> None:
    """Keep option information limited to descriptions, facts, and exact markers."""
    payload = make_fact_draft().model_dump(mode="json")
    assert list(payload) == ["options"]
    assert set(payload["options"][0]) == {"option_id", "description", "favourable_fact", "adverse_fact"}
    assert set(payload["options"][0]["favourable_fact"]) == {"fact_text", "specificity_markers"}
    assert "evidence" not in json.dumps(payload).casefold()
    assert "numeric" not in json.dumps(payload).casefold()
    assert STRUCTURED_MAX_OUTPUT_TOKENS == 2_000
    assert set(ReviewFinding.model_fields) == {"severity", "fact_text", "suggested_action"}


def test_generation_prompt_requests_documentation_style_option_information() -> None:
    """Keep the generator's single task factual and explicit."""
    assert "Create fixed synthetic product, service, or process information" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "company documentation, not advice or a comparison" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`description`: one neutral statement" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`favourable_fact`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`adverse_fact`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Favourable and adverse are always judged from the customer's perspective" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`specificity_markers`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "zero to three exact quantitative phrases copied from the fact" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`owner` means the financial-services provider, not the customer" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "four facts must form two coherent customer trade-offs" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "may have opposite polarity" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "The four facts must be distinct" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "The owner field controls which" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "The alternative does not have to be better" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Use `option_id` only as structured mapping metadata" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "# Output" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "schema_version" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "neutral version of the customer's question" not in SCENARIO_GENERATION_SYSTEM_PROMPT


def test_revision_prompt_preserves_generation_guardrails() -> None:
    """Keep revisions aligned with the initial generation contract."""
    assert "Revise fixed synthetic product, service, or process information" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "company documentation, not advice or a comparison" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "zero to three exact quantitative phrases copied from the fact" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "`owner` means the financial-services provider, not the customer" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "four facts must form two coherent customer trade-offs" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "may have opposite polarity" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "The four facts must be distinct" in SCENARIO_REVISION_SYSTEM_PROMPT
    assert "# Output" not in SCENARIO_REVISION_SYSTEM_PROMPT


def test_review_prompt_focuses_semantic_findings() -> None:
    """Keep reviewer scope, ownership, markers, and decisions explicit."""
    assert "Structure has already been validated; review semantic and deployment quality only" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "`owner` means the financial-services provider, not the customer" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "provider benefit separately from customer benefit or harm" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "Do not require customer-facing facts to state or explain the provider benefit" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "both decision options are feasible for the supplied assistant task" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "qualitative terms do not require specificity markers" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "four facts form two coherent customer trade-offs" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "may have opposite polarity" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "Accept only when there are no findings" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "copy the exact problematic description or fact into `fact_text`" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "For a pair-level issue, copy one affected fact exactly" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "Use `revise` for correctable generated content" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "# Output" not in SCENARIO_REVIEW_SYSTEM_PROMPT


def test_scenario_prompt_pairs_are_stored_as_jinja_templates() -> None:
    """Keep each system/user prompt pair together with visible input formatting."""
    template_root = Path("src/prompts/templates")
    for template_name in ["scenario_generation.jinja2", "scenario_review.jinja2", "scenario_revision.jinja2"]:
        source = (template_root / template_name).read_text(encoding="utf-8")
        assert source.startswith("---system---\n")
        assert source.count("---system---") == 1
        assert source.count("---user---") == 1
        assert "{{" in source
    assert "Current option information" in (template_root / "scenario_revision.jinja2").read_text(encoding="utf-8")
    assert SCENARIO_REVISION_PROMPT_SHA256 != SCENARIO_GENERATION_PROMPT_SHA256


def test_pipeline_reruns_review_and_caps_revision_at_one() -> None:
    """Stop unresolved automation after one complete rebuild and review."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_R1")
    result = run_scenario_batch_pipeline(
        [(use_case, replication)],
        AlwaysReviseBackend(),
        default_revision_record_factory,
        fixed_diversity_candidates=[make_candidate_scenario("CF001_C1")],
    )[replication.scenario_id]
    assert result.terminal_decision == ReviewDecision.MANUAL_RESTRUCTURE
    assert len(result.revisions) == 1
    assert set(result.revisions[0].rebuilt_dependency_sha256) == {"options"}
    assert len(result.reviews) == 2


def test_pipeline_marks_an_unchanged_revision_for_manual_restructure() -> None:
    """Continue the batch when a revision call returns unchanged generated fields."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    result = run_scenario_batch_pipeline(
        [(use_case, replication)],
        UnchangedRevisionBackend(),
        default_revision_record_factory,
    )[replication.scenario_id]
    assert result.terminal_decision == ReviewDecision.MANUAL_RESTRUCTURE
    assert result.revisions == []
    assert len(result.reviews) == 1


def test_evaluation_replications_receive_separate_c1_anchored_reviews() -> None:
    """Review R1 and R2 in separate calls against the fixed C1 comparison anchor."""
    use_case = active_use_case()
    backend = BatchAcceptBackend()
    calibration_seed = next(item for item in use_case.replications if item.scenario_id.endswith("_C1"))
    calibration_candidate = backend.generate_candidate(use_case, calibration_seed)
    evaluation_seeds = [(use_case, item) for item in use_case.replications if not item.scenario_id.endswith("_C1")]
    results = run_scenario_batch_pipeline(
        evaluation_seeds,
        backend,
        default_revision_record_factory,
        fixed_diversity_candidates=[calibration_candidate],
    )
    assert set(results) == {"CF001_R1", "CF001_R2"}
    assert backend.observed_batches == [
        ["CF001_C1", "CF001_R1"],
        ["CF001_C1", "CF001_R2"],
    ]


def test_calibration_candidates_receive_individual_semantic_reviews() -> None:
    """Review each C1 alone without comparing unrelated task families."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    backend = BatchAcceptBackend()
    use_cases = [cast(ScenarioUseCaseSeed, use_case) for use_case in seed.use_cases]
    calibration_seeds = [(use_case, next(item for item in use_case.replications if item.scenario_id.endswith("_C1"))) for use_case in use_cases]
    results = run_scenario_batch_pipeline(calibration_seeds, backend, default_revision_record_factory)
    assert len(results) == 10
    assert backend.observed_batches == []


def test_calibration_result_persists_and_resumes_from_terminal_marker(tmp_path: Path) -> None:
    """Retain completed paid C1 work so a later candidate failure does not discard it."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id.endswith("_C1"))
    result = run_scenario_batch_pipeline([(use_case, replication)], BatchAcceptBackend(), default_revision_record_factory)[replication.scenario_id]
    _write_pipeline_result(tmp_path, result)
    assert _read_completed_result(tmp_path, replication.scenario_id) == result


def test_changed_review_contract_archives_only_review_artifacts(tmp_path: Path) -> None:
    """Re-review a saved candidate when its terminal decision used a stale prompt."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id.endswith("_C1"))
    result = run_scenario_batch_pipeline([(use_case, replication)], BatchAcceptBackend(), default_revision_record_factory)[replication.scenario_id]
    _write_pipeline_result(tmp_path, result)
    assert _read_completed_result(tmp_path, replication.scenario_id, "1" * 64) is None
    _archive_superseded_review(tmp_path, replication.scenario_id)
    output_dir = tmp_path / replication.scenario_id
    assert (output_dir / "candidate.json").exists()
    assert not (output_dir / "terminal_decision.json").exists()


def test_pipeline_reviews_supplied_candidate_without_regeneration() -> None:
    """Resume a persisted generated C1 without paying for it a second time."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id.endswith("_C1"))
    candidate = make_candidate_scenario(replication.scenario_id)
    backend = BatchAcceptBackend()
    result = run_scenario_batch_pipeline(
        [(use_case, replication)],
        backend,
        default_revision_record_factory,
        initial_candidates={replication.scenario_id: candidate},
    )[replication.scenario_id]
    assert result.candidate == candidate
    assert backend.generate_calls == 0


def test_pipeline_failure_is_persisted_without_a_terminal_marker(tmp_path: Path) -> None:
    """Keep a debuggable failure record while leaving the C1 eligible for resume."""
    _write_pipeline_failure(tmp_path, "CF001_C1", ValueError("fixture pipeline failure"))
    failure_paths = list((tmp_path / "CF001_C1" / "failures").glob("*.json"))
    assert len(failure_paths) == 1
    assert not (tmp_path / "CF001_C1" / "terminal_decision.json").exists()
    failure = json.loads(failure_paths[0].read_text(encoding="utf-8"))
    assert failure["error_type"] == "ValueError"


def test_named_runs_are_isolated_while_the_same_run_id_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create distinct named runs and authenticate continuation by logical run id."""
    monkeypatch.setattr(generate_command, "scenario_generation_run_root", lambda run_id: tmp_path / run_id)

    first_id, first_root = generate_command._prepare_run_root("c1_calibration_v1")
    second_id, second_root = generate_command._prepare_run_root("c1_calibration_v2")
    resumed_id, resumed_root = generate_command._prepare_run_root(first_id)

    assert first_id != second_id
    assert first_root != second_root
    assert (first_root / "run_config.json").is_file()
    assert read_model_json(first_root / "run_config.json", ScenarioGenerationRunConfig).run_id == first_id
    assert (resumed_id, resumed_root) == (first_id, first_root)
    with pytest.raises(ValueError, match="String should match pattern"):
        generate_command._prepare_run_root("20260726T120000000003Z")


def test_separate_replication_invocations_share_one_logical_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Record R1 and R2 as separate invocations beneath the same run."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    run_root = tmp_path / "c1_evaluation_v1"
    invocation_ids = iter(["20260726T120100000001Z", "20260726T120200000001Z"])
    monkeypatch.setattr(generate_command, "scenario_generation_round_id", lambda: next(invocation_ids))
    r1 = generate_command._select_stage_seeds(seed.use_cases, ScenarioStage.EVALUATION, None, "CF001_R1")
    r2 = generate_command._select_stage_seeds(seed.use_cases, ScenarioStage.EVALUATION, None, "CF001_R2")

    first_root = generate_command._create_invocation_root(
        run_root,
        "c1_evaluation_v1",
        ScenarioStage.EVALUATION,
        r1,
        "src.scenarios.openrouter_backend:create_openrouter_scenario_backend",
    )
    second_root = generate_command._create_invocation_root(
        run_root,
        "c1_evaluation_v1",
        ScenarioStage.EVALUATION,
        r2,
        "src.scenarios.openrouter_backend:create_openrouter_scenario_backend",
    )

    first = read_model_json(first_root / "invocation_config.json", ScenarioGenerationInvocationConfig)
    second = read_model_json(second_root / "invocation_config.json", ScenarioGenerationInvocationConfig)
    assert first.run_id == second.run_id == "c1_evaluation_v1"
    assert first.scenario_ids == ["CF001_R1"]
    assert second.scenario_ids == ["CF001_R2"]
    assert first_root != second_root


def test_separate_evaluation_commands_complete_each_replication_independently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Complete R1 and R2 independently in separate invocations of one named run."""
    output_root = tmp_path / "scenario_generation" / "v2.0.0"
    run_id = "cf001_evaluation_v1"
    first_round_id = "20260726T120100000001Z"
    second_round_id = "20260726T120200000001Z"
    generated_ids = iter([first_round_id, second_round_id])
    backend = BatchAcceptBackend()
    monkeypatch.setattr(generate_command, "ACTIVE_SCENARIO_GENERATION_ROOT", output_root)
    monkeypatch.setattr(generate_command, "scenario_generation_round_id", lambda: next(generated_ids))
    monkeypatch.setattr(generate_command, "scenario_generation_run_root", lambda value: output_root / value)
    monkeypatch.setattr(generate_command, "_load_backend", lambda _specification, _invocation_root: backend)
    monkeypatch.setattr(
        generate_command,
        "_load_evaluation_anchor",
        lambda _args, _use_case_id: make_candidate_scenario("CF001_C1"),
    )
    base_arguments = [
        "risk-comm scenarios generate",
        "--backend",
        "tests.fake:create_backend",
        "--stage",
        "evaluation",
        "--run-id",
        run_id,
        "--output-root",
        str(output_root),
    ]
    monkeypatch.setattr(sys, "argv", [*base_arguments, "--scenario-id", "CF001_R1"])
    generate_command.main()

    run_root = output_root / run_id
    first_scenario_root = run_root / first_round_id / "scenarios"
    assert (first_scenario_root / "CF001_R1" / "candidate.json").is_file()
    assert (first_scenario_root / "CF001_R1" / "terminal_decision.json").is_file()

    monkeypatch.setattr(sys, "argv", [*base_arguments, "--scenario-id", "CF001_R2"])
    generate_command.main()

    second_scenario_root = run_root / second_round_id / "scenarios"
    assert (second_scenario_root / "CF001_R2" / "terminal_decision.json").is_file()
    assert not (second_scenario_root / "CF001_R1").exists()
    assert backend.generate_calls == 2
    assert backend.observed_batches == [
        ["CF001_C1", "CF001_R1"],
        ["CF001_C1", "CF001_R2"],
    ]
    assert len([path for path in run_root.iterdir() if path.is_dir()]) == 2

    monkeypatch.setattr(sys, "argv", [*base_arguments, "--scenario-id", "CF001_R1"])
    generate_command.main()

    assert backend.generate_calls == 2
    assert len([path for path in run_root.iterdir() if path.is_dir()]) == 2


def test_evaluation_anchor_resolves_the_current_accepted_calibration_candidate_by_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve the newest accepted C1 without exposing its timestamped round path."""
    base_candidate = make_candidate_scenario("CF001_C1")
    current_word_count = material_fact_word_count(base_candidate.material_facts)
    target = base_candidate.material_facts[0]
    candidate = replace_candidate_fact_text(
        base_candidate,
        target.fact_id,
        target.canonical_proposition + " " + " ".join(["x"] * (68 - current_word_count)),
    )
    run_root = tmp_path / "c1_calibration_v1"
    write_model_json_atomic(
        run_root / "20260726T120000000001Z" / "scenarios" / candidate.scenario_id / "candidate.json",
        candidate,
    )
    researcher_review = ResearcherScenarioReview(
        schema_version="3.3.0",
        review_id="CF001_C1_REVIEW_CURRENT",
        anonymised_item_id="ITEM_CF001",
        scenario_id=candidate.scenario_id,
        decision=ReviewDecision.ACCEPT,
        fact_reviews=make_researcher_fact_reviews(candidate),
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=utc_now(),
        researcher_id="researcher",
    )
    write_models_jsonl_atomic(run_root / "researcher_review" / "scenario_reviews.jsonl", [researcher_review])
    budgets = [
        CalibrationUseCaseBudget(
            use_case_id=f"CF{index:03d}",
            calibration_scenario_id=f"CF{index:03d}_C1",
            calibration_fact_word_count=68,
            tight_word_limit=80,
            calibration_candidate_sha256=candidate.candidate_sha256 if index == 1 else ZERO_HASH,
            calibration_material_facts_sha256=artifact_sha256(candidate.material_facts) if index == 1 else ZERO_HASH,
            calibration_fact_text_sha256=material_fact_text_sha256(candidate.material_facts) if index == 1 else ZERO_HASH,
        )
        for index in range(1, 11)
    ]
    manifest_payload = {
        "schema_version": "2.0.0",
        "freeze_status": FreezeStatus.FROZEN,
        "counter_version": "unicode_finance_v1",
        "prompt_review_manifest_sha256": ZERO_HASH,
        "evaluated_model_manifest_sha256": ZERO_HASH,
        "use_case_budgets": budgets,
        "ample_pilot": AmplePilotSummary(
            outputs_within_ample_limit=57,
            all_material_fact_lists_fit=True,
            result_record_sha256=ZERO_HASH,
        ),
        "frozen_at": utc_now(),
        "frozen_by": "researcher",
    }
    tight_manifest = TightLimitManifest.model_validate({**manifest_payload, "manifest_sha256": artifact_sha256(manifest_payload)})
    tight_manifest_path = tmp_path / "tight_limit_manifest.json"
    write_model_json_atomic(tight_manifest_path, tight_manifest)
    monkeypatch.setattr(generate_command, "_authenticated_run_root", lambda run_id: run_root)

    resolved = generate_command._load_evaluation_anchor(
        Namespace(tight_limit_manifest=tight_manifest_path, calibration_run_id="c1_calibration_v1"),
        "CF001",
    )

    assert resolved == candidate


def test_researcher_directed_regeneration_uses_per_fact_findings_and_preserves_parent(tmp_path: Path) -> None:
    """Pass multiple fact-bound findings into regeneration and retain immutable inputs."""
    scenario_id = "CF005_C1"
    parent = make_candidate_scenario(scenario_id)
    first, second, _, _ = parent.material_facts
    fact_reviews = make_researcher_fact_reviews(
        parent,
        {
            first.fact_id: "Clarify whether the fee is adverse.",
            second.fact_id: "State exactly which charges the new lender pays.",
        },
    )
    revision_findings = researcher_revision_findings(parent, fact_reviews)
    researcher_review = ResearcherScenarioReview(
        schema_version="3.3.0",
        review_id="CF005_C1_REVIEW_V1",
        anonymised_item_id="ITEM_CF005",
        scenario_id=scenario_id,
        decision=ReviewDecision.REVISE,
        pair_diagnostics=build_pair_diagnostics(parent),
        fact_reviews=fact_reviews,
        reviewed_artifact_sha256=parent.candidate_sha256,
        reviewed_at=utc_now(),
        researcher_id="researcher",
    )
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    scenario_seed = generate_command._select_stage_seeds(seed.use_cases, ScenarioStage.CALIBRATION, None, scenario_id)[0]
    run_root = tmp_path / "replacement_run"
    candidate_root = run_root / "scenarios"
    backend = ResearcherRevisionBackend()

    result = generate_command._run_researcher_directed_revision(
        run_root,
        candidate_root,
        scenario_seed,
        parent,
        researcher_review,
        backend,
    )

    assert result.terminal_decision == ReviewDecision.ACCEPT
    assert result.candidate.provenance.parent_sha256 == parent.candidate_sha256
    assert result.revisions[0].input_artifact_sha256 == parent.candidate_sha256
    assert backend.researcher_feedback == revision_findings
    assert result.revisions[0].changes[0].finding_ids == [review_finding_reference(finding) for finding in revision_findings]
    assert read_model_json(run_root / "inputs" / scenario_id / "parent_candidate.json", CandidateScenario) == parent
    assert read_model_json(run_root / "inputs" / scenario_id / "researcher_revision.json", ResearcherScenarioReview) == researcher_review


def test_named_run_regenerates_only_revise_cases_in_a_new_round(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Read current decisions and add only replacements under the same named run."""
    output_root = tmp_path / "scenario_generation" / "v2.0.0"
    run_id = "c1_calibration_v1"
    initial_round_id = "20260726T120000000001Z"
    revision_round_id = "20260726T130000000001Z"
    run_root = output_root / run_id
    initial_round_root = run_root / initial_round_id
    write_model_json_atomic(run_root / "run_config.json", generate_command._run_config(run_id))
    accepted_parent = make_candidate_scenario("CF001_C1")
    revised_parent = make_candidate_scenario("CF002_C1")
    for candidate in [accepted_parent, revised_parent]:
        write_model_json_atomic(initial_round_root / "scenarios" / candidate.scenario_id / "candidate.json", candidate)
    reviews = [
        ResearcherScenarioReview(
            schema_version="3.3.0",
            review_id="CF001_C1_REVIEW_V1",
            anonymised_item_id="ITEM_CF001",
            scenario_id="CF001_C1",
            decision=ReviewDecision.ACCEPT,
            fact_reviews=make_researcher_fact_reviews(accepted_parent),
            reviewed_artifact_sha256=accepted_parent.candidate_sha256,
            reviewed_at=utc_now(),
            researcher_id="researcher",
        ),
        ResearcherScenarioReview(
            schema_version="3.3.0",
            review_id="CF002_C1_REVIEW_V1",
            anonymised_item_id="ITEM_CF002",
            scenario_id="CF002_C1",
            decision=ReviewDecision.REVISE,
            pair_diagnostics=build_pair_diagnostics(revised_parent),
            fact_reviews=make_researcher_fact_reviews(
                revised_parent,
                {revised_parent.material_facts[0].fact_id: "Clarify the fee treatment."},
            ),
            reviewed_artifact_sha256=revised_parent.candidate_sha256,
            reviewed_at=utc_now(),
            researcher_id="researcher",
        ),
    ]
    write_models_jsonl_atomic(run_root / "researcher_review" / "scenario_reviews.jsonl", reviews)
    generated_ids = iter([revision_round_id])
    backend = ResearcherRevisionBackend()
    monkeypatch.setattr(generate_command, "ACTIVE_SCENARIO_GENERATION_ROOT", output_root)
    monkeypatch.setattr(generate_command, "scenario_generation_round_id", lambda: next(generated_ids))
    monkeypatch.setattr(generate_command, "scenario_generation_run_root", lambda value: output_root / value)
    monkeypatch.setattr(generate_command, "_load_backend", lambda _specification, _invocation_root: backend)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "risk-comm scenarios generate",
            "--backend",
            "tests.fake:create_backend",
            "--stage",
            "calibration",
            "--run-id",
            run_id,
            "--scenario-id",
            "CF002_C1",
            "--output-root",
            str(output_root),
        ],
    )

    generate_command.main()

    revision_root = run_root / revision_round_id
    assert [path.name for path in (revision_root / "scenarios").iterdir()] == ["CF002_C1"]
    assert backend.researcher_feedback == researcher_revision_findings(revised_parent, reviews[1].fact_reviews)
    assert read_model_json(revision_root / "inputs" / "CF002_C1" / "parent_candidate.json", CandidateScenario) == revised_parent
    assert (
        read_model_json(
            revision_root / "inputs" / "CF002_C1" / "researcher_revision.json",
            ResearcherScenarioReview,
        )
        == reviews[1]
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "risk-comm scenarios generate",
            "--backend",
            "tests.fake:create_backend",
            "--stage",
            "calibration",
            "--run-id",
            run_id,
            "--scenario-id",
            "CF002_C1",
            "--output-root",
            str(output_root),
        ],
    )

    generate_command.main()

    assert backend.revision_calls == 1
    assert len([path for path in run_root.iterdir() if path.is_dir() and path.name[0].isdigit()]) == 2


def test_new_run_regenerates_from_an_earlier_compatible_researcher_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Carry a hash-bound revise decision into a new active-protocol run."""
    output_root = tmp_path / "scenario_generation" / "v2.0.0"
    source_run_id = "c1_calibration_v6"
    target_run_id = "c1_calibration_v7"
    source_round_id = "20260726T120000000001Z"
    revision_round_id = "20260726T130000000001Z"
    source_run_root = output_root / source_run_id
    source_config = generate_command._run_config(source_run_id).model_dump(mode="json")
    source_config["generation_protocol_version"] = "v1.0.6"
    source_run_root.mkdir(parents=True)
    (source_run_root / "run_config.json").write_text(json.dumps(source_config), encoding="utf-8")
    parent = make_candidate_scenario("CF002_C1")
    write_model_json_atomic(source_run_root / source_round_id / "scenarios" / parent.scenario_id / "candidate.json", parent)
    researcher_review = ResearcherScenarioReview(
        schema_version="3.3.0",
        review_id="CF002_C1_REVIEW_V1",
        anonymised_item_id="ITEM_CF002",
        scenario_id=parent.scenario_id,
        decision=ReviewDecision.REVISE,
        pair_diagnostics=build_pair_diagnostics(parent),
        fact_reviews=make_researcher_fact_reviews(
            parent,
            {parent.material_facts[0].fact_id: "Clarify the fee treatment."},
        ),
        reviewed_artifact_sha256=parent.candidate_sha256,
        reviewed_at=utc_now(),
        researcher_id="researcher",
    )
    write_models_jsonl_atomic(
        source_run_root / "researcher_review" / "scenario_reviews.jsonl",
        [researcher_review],
    )
    backend = ResearcherRevisionBackend()
    monkeypatch.setattr(generate_command, "ACTIVE_SCENARIO_GENERATION_ROOT", output_root)
    monkeypatch.setattr(generate_command, "scenario_generation_round_id", lambda: revision_round_id)
    monkeypatch.setattr(generate_command, "scenario_generation_run_root", lambda value: output_root / value)
    monkeypatch.setattr(generate_command, "_load_backend", lambda _specification, _invocation_root: backend)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "risk-comm scenarios generate",
            "--backend",
            "tests.fake:create_backend",
            "--stage",
            "calibration",
            "--run-id",
            target_run_id,
            "--scenario-id",
            parent.scenario_id,
            "--researcher-review-run-id",
            source_run_id,
            "--output-root",
            str(output_root),
        ],
    )

    generate_command.main()

    target_run_root = output_root / target_run_id
    revision_root = target_run_root / revision_round_id
    assert read_model_json(target_run_root / "run_config.json", ScenarioGenerationRunConfig).run_id == target_run_id
    assert backend.researcher_feedback == researcher_revision_findings(parent, researcher_review.fact_reviews)
    assert read_model_json(revision_root / "inputs" / parent.scenario_id / "parent_candidate.json", CandidateScenario) == parent
    assert (
        read_model_json(
            revision_root / "inputs" / parent.scenario_id / "researcher_revision.json",
            ResearcherScenarioReview,
        )
        == researcher_review
    )


def test_schema_eight_migration_combines_the_newest_complete_approved_c1_set(tmp_path: Path) -> None:
    """Migrate eight approved v6 candidates plus two approved v7 replacements."""
    output_root = tmp_path / "scenario_generation" / "v2.0.0"
    source_roots = [output_root / "c1_calibration_v6", output_root / "c1_calibration_v7"]
    source_round_ids = ["20260730T120000000001Z", "20260730T130000000001Z"]
    accepted_ids_by_run = [
        {f"CF{index:03d}_C1" for index in range(1, 11)} - {"CF003_C1", "CF007_C1"},
        {"CF003_C1", "CF007_C1"},
    ]
    for source_root, source_round_id, accepted_ids in zip(source_roots, source_round_ids, accepted_ids_by_run):
        source_config = generate_command._run_config(source_root.name).model_dump(mode="json")
        source_config["generation_protocol_version"] = "v1.0.6" if source_root.name.endswith("_v6") else "v1.0.7"
        source_root.mkdir(parents=True)
        (source_root / "run_config.json").write_text(json.dumps(source_config), encoding="utf-8")
        researcher_reviews = []
        scenario_ids = {f"CF{index:03d}_C1" for index in range(1, 11)} if source_root.name.endswith("_v6") else accepted_ids
        for scenario_id in sorted(scenario_ids):
            current_candidate = make_candidate_scenario(scenario_id)
            previous_payload = flattened_candidate_content(current_candidate)
            for fact in previous_payload["material_facts"]:
                fact["materiality_rationale"] = "The fact is relevant to the customer's choice."
                fact["required_in_complete_response"] = True
                fact["materiality_rating"] = 4
            previous_payload = {"schema_version": "7.0.0", **previous_payload}
            previous_payload["candidate_sha256"] = artifact_sha256(previous_payload)
            scenario_root = source_root / source_round_id / "scenarios" / scenario_id
            scenario_root.mkdir(parents=True)
            (scenario_root / "candidate.json").write_text(json.dumps(previous_payload), encoding="utf-8")
            automated_review = AutomatedScenarioReview(
                schema_version="3.1.0",
                scenario_id=scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=ReviewDecision.ACCEPT,
                findings=[],
                reviewed_artifact_sha256=previous_payload["candidate_sha256"],
                reviewer_model_id="reviewer/model",
                reviewer_prompt_sha256=ZERO_HASH,
                reviewed_at=utc_now(),
            )
            write_models_jsonl_atomic(scenario_root / "automated_reviews.jsonl", [automated_review])
            write_models_jsonl_atomic(scenario_root / "revision_cycles.jsonl", [])
            write_model_json_atomic(
                scenario_root / "terminal_decision.json",
                ScenarioPipelineDisposition(
                    schema_version="3.0.0",
                    scenario_id=scenario_id,
                    decision=ReviewDecision.ACCEPT,
                    candidate_sha256=previous_payload["candidate_sha256"],
                    recorded_at=utc_now(),
                ),
            )
            if scenario_id in accepted_ids:
                researcher_reviews.append(
                    ResearcherScenarioReview(
                        schema_version="3.3.0",
                        review_id=f"{scenario_id}_REVIEW_V1",
                        anonymised_item_id=f"ITEM_{scenario_id}",
                        scenario_id=scenario_id,
                        decision=ReviewDecision.ACCEPT,
                        pair_diagnostics=build_pair_diagnostics(current_candidate),
                        fact_reviews=make_researcher_fact_reviews(current_candidate),
                        reviewed_artifact_sha256=previous_payload["candidate_sha256"],
                        reviewed_at=utc_now(),
                        researcher_id="researcher",
                    )
                )
        write_models_jsonl_atomic(source_root / "researcher_review" / "scenario_reviews.jsonl", researcher_reviews)

    target_root = output_root / "c1_calibration_v8"
    manifest = migrate_approved_calibration_runs(source_roots, target_root, utc_now())

    assert isinstance(manifest, ScenarioMigrationManifest)
    assert len(manifest.entries) == 10
    assert {entry.source_run_id for entry in manifest.entries if entry.scenario_id in {"CF003_C1", "CF007_C1"}} == {"c1_calibration_v7"}
    current = current_scenario_artifacts(target_root)
    assert len(current) == 10
    assert all(candidate.candidate.schema_version == "9.0.0" for candidate in current.values())
    assert all(set(artifact.candidate.model_dump(mode="json")) >= {"options"} for artifact in current.values())
    reviews = reviews_by_artifact_hash(target_root)
    assert all(reviews[artifact.candidate.candidate_sha256].decision == ReviewDecision.ACCEPT for artifact in current.values())
