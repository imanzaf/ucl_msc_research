"""Test simple-fact generation, source spans, semantic review, and revision caps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Tuple, cast

import pytest

from src.cli.commands.scenarios.generate import _archive_superseded_review, _read_completed_result, _write_pipeline_failure, _write_pipeline_result
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
from src.data_models.scenarios import CandidateScenario, FactPolarity, SourceItem, SourceOptionId, V09ReplicationSeed, V09UseCaseSeed
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT, SCENARIO_REVIEW_SYSTEM_PROMPT
from src.scenarios.openrouter_backend import (
    STRUCTURED_MAX_OUTPUT_TOKENS,
    EvidenceItemDraft,
    GeneratedFactDraft,
    IntegratedScenarioDraft,
    OpenRouterScenarioBackend,
    ScenarioGenerationInput,
)
from src.scenarios.pipeline import default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.scenarios.source_rendering import build_source_packet, validate_evidence_span
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario


class IntegratedGenerationClient:
    """Return one simple-fact draft while recording exact generation requests."""

    def __init__(self, draft: IntegratedScenarioDraft) -> None:
        """Store the integrated response and initialise request capture."""
        self.draft = draft
        self.messages: List[List[dict[str, str]]] = []

    def complete_structured_with_provenance(self, model_id: str, messages: List[dict[str, str]], *args: Any, **kwargs: Any) -> Any:
        """Return the configured draft with valid provider provenance."""
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
    """Build four canonical facts followed by four corresponding evidence items."""
    return IntegratedScenarioDraft(
        schema_version="3.0.0",
        facts=[
            GeneratedFactDraft(
                option_id=SourceOptionId.OPTION_A,
                polarity=FactPolarity.BENEFIT,
                text="The linked-savings sweep covers the £120 shortfall without debit interest.",
            ),
            GeneratedFactDraft(
                option_id=SourceOptionId.OPTION_A,
                polarity=FactPolarity.DOWNSIDE,
                text="The linked-savings sweep reduces the immediately available savings balance by £120.",
            ),
            GeneratedFactDraft(
                option_id=SourceOptionId.OPTION_B,
                polarity=FactPolarity.BENEFIT,
                text="The arranged overdraft makes a £500 authorised buffer available immediately.",
            ),
            GeneratedFactDraft(
                option_id=SourceOptionId.OPTION_B,
                polarity=FactPolarity.DOWNSIDE,
                text="Using the arranged overdraft for the forecast shortfall costs £72 over 12 months.",
            ),
        ],
        evidence_items=[
            EvidenceItemDraft(
                option_id=SourceOptionId.OPTION_A,
                polarity=FactPolarity.BENEFIT,
                text="A linked-savings sweep can cover the £120 shortfall without debit interest.",
            ),
            EvidenceItemDraft(
                option_id=SourceOptionId.OPTION_A,
                polarity=FactPolarity.DOWNSIDE,
                text="Covering the shortfall through the sweep reduces the available savings balance by £120.",
            ),
            EvidenceItemDraft(
                option_id=SourceOptionId.OPTION_B,
                polarity=FactPolarity.BENEFIT,
                text="The arranged-overdraft terms provide an immediately available authorised buffer of £500.",
            ),
            EvidenceItemDraft(
                option_id=SourceOptionId.OPTION_B,
                polarity=FactPolarity.DOWNSIDE,
                text="The quote shows £72 of debit interest over 12 months for the forecast use.",
            ),
        ],
    )


def active_use_case() -> V09UseCaseSeed:
    """Load the first active V0.9 use case."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
    )
    return cast(V09UseCaseSeed, seed.use_cases[0])


class AlwaysReviseBackend:
    """Fake backend that proves one revision round ends in manual restructuring."""

    def __init__(self) -> None:
        """Create a backend with a stable candidate."""
        self.candidate = make_candidate_scenario()

    def generate_candidate(self, use_case: V09UseCaseSeed, replication: V09ReplicationSeed) -> CandidateScenario:
        """Return the fixture candidate."""
        return self.candidate

    def review_candidates(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Return one semantic finding for every candidate."""
        return [
            AutomatedScenarioReview(
                schema_version="3.0.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=ReviewDecision.REVISE,
                findings=[
                    ReviewFinding(
                        finding_id=f"SCENARIO_QUALITY_{candidate.scenario_id}",
                        severity=FindingSeverity.MAJOR,
                        artifact_path="candidate.json",
                        field_path="source_packet.fixed_title",
                        message="Needs revision.",
                        evidence="Fixture evidence.",
                        suggested_action="Revise the field.",
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
        use_case: V09UseCaseSeed,
        replication: V09ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Change the canonical title and return a controlled revision."""
        revised_source = build_source_packet(candidate.scenario_id, f"Revision {cycle_number}", candidate.source_packet.items)
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
    """Accept candidates while recording each shared semantic-review batch."""

    def __init__(self) -> None:
        """Initialise observed batch membership."""
        self.observed_batches: List[List[str]] = []
        self.generate_calls = 0

    def generate_candidate(self, use_case: V09UseCaseSeed, replication: V09ReplicationSeed) -> CandidateScenario:
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
                schema_version="3.0.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
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
        use_case: V09UseCaseSeed,
        replication: V09ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Reject an impossible revision call in this accepting fixture."""
        raise AssertionError("accepted candidates must not enter revision")


def test_openrouter_backend_generates_candidate_from_simple_fact_lists() -> None:
    """Build facts and spans in code while withholding the research mapping from generation."""
    use_case = active_use_case()
    replication = next(item for item in use_case.hidden_design.source_generation.replications if item.scenario_id == "CF001_R1")
    client = IntegratedGenerationClient(make_integrated_draft())
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, client),
        review_client=cast(OpenRouterClient, client),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )

    candidate = backend.generate_candidate(use_case, replication)

    request_payload = json.loads(client.messages[0][1]["content"])
    ScenarioGenerationInput.model_validate(request_payload)
    assert set(request_payload) == {"deployment", "source_generation", "replication_variation", "evidence_format"}
    assert "research" not in client.messages[0][1]["content"]
    assert "customer_preferred_option" not in client.messages[0][1]["content"]
    assert "numeric_registry" not in candidate.model_dump(mode="json")
    assert "specificity_elements" not in candidate.model_dump(mode="json")
    assert len(candidate.material_facts) == 4
    assert len(candidate.source_packet.items) == 4
    assert candidate.material_facts[0].canonical_proposition.startswith("The arranged overdraft")
    assert candidate.material_facts[1].canonical_proposition.startswith("The linked-savings sweep")
    assert candidate.source_packet.fixed_title == "Current account with arranged overdraft / Current account with linked-savings sweep"
    assert [item.header for item in candidate.source_packet.items] == [
        "Current account with arranged overdraft — Arranged limit",
        "Current account with arranged overdraft — Debit interest",
        "Current account with linked-savings sweep — Sweep operation",
        "Current account with linked-savings sweep — Savings balance",
    ]
    assert candidate.source_packet.items[0].body.startswith("The arranged-overdraft terms")
    assert all(span.start_char == 0 for fact in candidate.material_facts for span in fact.source_support)


def test_generation_contract_contains_no_numeric_or_scoring_registry() -> None:
    """Keep numbers as ordinary prose rather than a parallel generated structure."""
    payload = make_integrated_draft().model_dump(mode="json")
    assert list(payload) == ["schema_version", "facts", "evidence_items"]
    assert "numeric" not in json.dumps(payload).casefold()
    assert "specificity" not in json.dumps(payload).casefold()
    assert "minimal" not in json.dumps(payload).casefold()
    assert STRUCTURED_MAX_OUTPUT_TOKENS == 6_000


def test_generation_prompt_requests_facts_before_natural_evidence() -> None:
    """Require canonical facts first and their natural evidence packet second."""
    assert "First generate exactly four short canonical facts" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "one `benefit` fact and one `downside` fact for OPTION_A" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "do not generate separate background or neutral fact records" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Only after completing the four facts" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "return `facts` first" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "then return `evidence_items`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "do not return formulas, working" in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()
    assert "title, heading, or" in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()
    assert "customer-facing title" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Present the alternatives as" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "customer should choose" in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()
    assert "numeric registry" not in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()
    assert "specificity" not in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()
    assert "minimal" not in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()


def test_review_prompt_distinguishes_c1_decisions_from_r_batch_anchor() -> None:
    """Prevent the reviewer from treating a singleton calibration C1 as an undecided anchor."""
    assert "this is a calibration review" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "Review that C1 and return its" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "In that R-batch case" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "Use `revise` for a correctable problem" in SCENARIO_REVIEW_SYSTEM_PROMPT


def test_exact_source_span_validation() -> None:
    """Reject a support span whose character bounds do not reproduce exact text."""
    scenario = make_accepted_scenario()
    item_by_id = {item.source_item_id: item for item in scenario.source_packet.items}
    valid = scenario.material_facts[0].source_support[0]
    validate_evidence_span(valid, item_by_id)
    invalid = valid.model_copy(update={"exact_text": "wrong text", "end_char": len("wrong text")})
    with pytest.raises(ValueError, match="invalid exact evidence span"):
        validate_evidence_span(invalid, item_by_id)


def test_backend_uses_the_complete_simple_fact_as_source_support() -> None:
    """Derive source evidence without asking the generator for quote identifiers or offsets."""
    backend = OpenRouterScenarioBackend(
        generation_client=cast(OpenRouterClient, object()),
        review_client=cast(OpenRouterClient, object()),
        generator_model_id="generator/model",
        reviewer_model_id="reviewer/model",
    )
    item = SourceItem(source_item_id="ITEM_1", header="Terms", body="A fee applies.")
    span = backend._full_item_span(item)
    assert span.start_char == 0
    assert span.end_char == len(item.body)
    validate_evidence_span(span, {"ITEM_1": item})


def test_pipeline_reruns_review_and_caps_revision_at_one() -> None:
    """Stop unresolved automation after one complete rebuild and review."""
    use_case = active_use_case()
    replication = next(item for item in use_case.hidden_design.source_generation.replications if item.scenario_id == "CF001_R1")
    result = run_scenario_batch_pipeline(
        [(use_case, replication)],
        AlwaysReviseBackend(),
        default_revision_record_factory,
        fixed_diversity_candidates=[make_candidate_scenario("CF001_C1")],
    )[replication.scenario_id]
    assert result.terminal_decision == ReviewDecision.MANUAL_RESTRUCTURE
    assert len(result.revisions) == 1
    assert len(result.reviews) == 2


def test_combined_review_receives_all_five_use_case_candidates() -> None:
    """Review R1-R4 together against the fixed C1 comparison anchor."""
    use_case = active_use_case()
    backend = BatchAcceptBackend()
    replications = use_case.hidden_design.source_generation.replications
    calibration_seed = next(item for item in replications if item.scenario_id.endswith("_C1"))
    calibration_candidate = backend.generate_candidate(use_case, calibration_seed)
    evaluation_seeds = [(use_case, item) for item in replications if not item.scenario_id.endswith("_C1")]
    results = run_scenario_batch_pipeline(
        evaluation_seeds,
        backend,
        default_revision_record_factory,
        fixed_diversity_candidates=[calibration_candidate],
    )
    expected_ids = {"CF001_C1", "CF001_R1", "CF001_R2", "CF001_R3", "CF001_R4"}
    assert set(results) == expected_ids - {"CF001_C1"}
    assert backend.observed_batches == [sorted(expected_ids)]


def test_calibration_candidates_receive_individual_semantic_reviews() -> None:
    """Review each C1 alone without comparing unrelated use cases."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
    )
    backend = BatchAcceptBackend()
    use_cases = [cast(V09UseCaseSeed, use_case) for use_case in seed.use_cases]
    calibration_seeds = [
        (
            use_case,
            next(item for item in use_case.hidden_design.source_generation.replications if item.scenario_id.endswith("_C1")),
        )
        for use_case in use_cases
    ]
    results = run_scenario_batch_pipeline(calibration_seeds, backend, default_revision_record_factory)
    assert len(results) == 10
    assert backend.observed_batches == []


def test_calibration_result_persists_and_resumes_from_terminal_marker(tmp_path: Path) -> None:
    """Retain completed paid C1 work so a later candidate failure does not discard it."""
    use_case = active_use_case()
    replication = next(item for item in use_case.hidden_design.source_generation.replications if item.scenario_id.endswith("_C1"))
    result = run_scenario_batch_pipeline([(use_case, replication)], BatchAcceptBackend(), default_revision_record_factory)[replication.scenario_id]
    _write_pipeline_result(tmp_path, result)
    assert _read_completed_result(tmp_path, replication.scenario_id) == result


def test_changed_review_contract_archives_only_review_artifacts(tmp_path: Path) -> None:
    """Re-review a saved candidate when its terminal decision used a stale prompt."""
    use_case = active_use_case()
    replication = next(item for item in use_case.hidden_design.source_generation.replications if item.scenario_id.endswith("_C1"))
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
    replication = next(item for item in use_case.hidden_design.source_generation.replications if item.scenario_id.endswith("_C1"))
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
