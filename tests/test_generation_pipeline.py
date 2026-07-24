"""Test four-fact generation, semantic review, persistence, and revision caps."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Tuple, cast

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
from src.data_models.scenarios import CandidateScenario, FactPolarity, SeedOptionId, V10ReplicationSeed, V10UseCaseSeed
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT, SCENARIO_REVIEW_SYSTEM_PROMPT
from src.scenarios.openrouter_backend import (
    STRUCTURED_MAX_OUTPUT_TOKENS,
    GeneratedFactDraft,
    OpenRouterScenarioBackend,
    ScenarioFactDraft,
    ScenarioGenerationInput,
)
from src.scenarios.pipeline import default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from tests.factories import ZERO_HASH, make_candidate_scenario


class FactGenerationClient:
    """Return one four-fact draft while recording exact generation requests."""

    def __init__(self, draft: ScenarioFactDraft) -> None:
        """Store the response and initialise request capture."""
        self.draft = draft
        self.messages: List[List[dict[str, str]]] = []

    def complete_structured_with_provenance(self, model_id: str, messages: List[dict[str, str]], *args: Any, **kwargs: Any) -> Any:
        """Return the configured draft with valid provider provenance."""
        self.messages.append(messages)
        return ProviderStructuredResponse[ScenarioFactDraft](
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


def make_fact_draft() -> ScenarioFactDraft:
    """Build one fact in every option-by-polarity cell."""
    return ScenarioFactDraft(
        schema_version="4.0.0",
        facts=[
            GeneratedFactDraft(
                option_id=SeedOptionId.OPTION_A,
                polarity=FactPolarity.BENEFIT,
                text="The linked-savings automatic sweep covers the shortfall without debit interest.",
            ),
            GeneratedFactDraft(
                option_id=SeedOptionId.OPTION_A,
                polarity=FactPolarity.DOWNSIDE,
                text="The linked-savings automatic sweep reduces the savings balance available for other needs.",
            ),
            GeneratedFactDraft(
                option_id=SeedOptionId.OPTION_B,
                polarity=FactPolarity.BENEFIT,
                text="The arranged overdraft keeps the linked savings balance untouched.",
            ),
            GeneratedFactDraft(
                option_id=SeedOptionId.OPTION_B,
                polarity=FactPolarity.DOWNSIDE,
                text="The arranged overdraft charges debit interest while the account remains overdrawn.",
            ),
        ],
    )


def active_use_case() -> V10UseCaseSeed:
    """Load the first active V0.10 task family."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
    )
    return cast(V10UseCaseSeed, seed.use_cases[0])


class AlwaysReviseBackend:
    """Fake backend that proves one revision round ends in manual restructuring."""

    def __init__(self) -> None:
        """Create a backend with a stable candidate."""
        self.candidate = make_candidate_scenario()

    def generate_candidate(self, use_case: V10UseCaseSeed, replication: V10ReplicationSeed) -> CandidateScenario:
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
                schema_version="3.0.0",
                scenario_id=candidate.scenario_id,
                review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
                decision=ReviewDecision.REVISE,
                findings=[
                    ReviewFinding(
                        finding_id=f"SCENARIO_QUALITY_{candidate.scenario_id}",
                        severity=FindingSeverity.MAJOR,
                        artifact_path="candidate.json",
                        field_path="material_facts",
                        message="Needs revision.",
                        evidence="Fixture evidence.",
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
        use_case: V10UseCaseSeed,
        replication: V10ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Change one fact and return a controlled revision."""
        facts = list(candidate.material_facts)
        facts[0] = facts[0].model_copy(update={"canonical_proposition": f"{facts[0].canonical_proposition} Revised."})
        payload = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
        payload["material_facts"] = [fact.model_dump(mode="json") for fact in facts]
        revised = CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})
        return revised, [
            ControlledFieldChange(
                field_path="material_facts",
                previous_value_sha256=artifact_sha256(candidate.material_facts),
                revised_value_sha256=artifact_sha256(revised.material_facts),
                reason=f"Resolve fixture findings in cycle {cycle_number}.",
                finding_ids=[finding.finding_id for review in reviews for finding in review.findings],
            )
        ]


class BatchAcceptBackend:
    """Accept candidates while recording each shared semantic-review batch."""

    def __init__(self) -> None:
        """Initialise observed batch membership."""
        self.observed_batches: List[List[str]] = []
        self.generate_calls = 0

    def generate_candidate(self, use_case: V10UseCaseSeed, replication: V10ReplicationSeed) -> CandidateScenario:
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
        use_case: V10UseCaseSeed,
        replication: V10ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Reject an impossible revision call in this accepting fixture."""
        raise AssertionError("accepted candidates must not enter revision")


def test_openrouter_backend_generates_only_four_direct_facts() -> None:
    """Build a V4 candidate in one call with no separate evidence packet."""
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

    request_payload = json.loads(client.messages[0][1]["content"])
    ScenarioGenerationInput.model_validate(request_payload)
    assert set(request_payload) == {"deployment", "decision"}
    assert set(request_payload["decision"]) == {
        "decision_type",
        "options",
        "customer_query",
        "customer_supporting_option",
        "owner_supporting_option",
        "owner_benefit_mechanism",
    }
    assert candidate.schema_version == "4.0.0"
    assert len(candidate.material_facts) == 4
    assert all("source_support" not in type(fact).model_fields for fact in candidate.material_facts)
    assert candidate.provenance.provider_calls[0].usage.cost_credits == Decimal("0.01")


def test_generation_contract_contains_only_fact_output() -> None:
    """Keep facts as ordinary prose without evidence, numeric, or specificity registries."""
    payload = make_fact_draft().model_dump(mode="json")
    assert list(payload) == ["schema_version", "facts"]
    assert "evidence" not in json.dumps(payload).casefold()
    assert "numeric" not in json.dumps(payload).casefold()
    assert "specificity" not in json.dumps(payload).casefold()
    assert STRUCTURED_MAX_OUTPUT_TOKENS == 2_000


def test_generation_prompt_requests_exactly_four_facts() -> None:
    """Keep the generator's single task explicit and small."""
    assert "Generate exactly four self-contained facts" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "one `benefit` fact and one `downside` fact for OPTION_A" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Do not describe the provider-benefit mechanism" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Do not generate background facts" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "return only `facts`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "specificity fields" not in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "minimal" not in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()


def test_review_prompt_distinguishes_c1_from_two_decision_replications() -> None:
    """Prevent the reviewer from treating a singleton calibration C1 as an undecided anchor."""
    assert "this is a calibration review" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "contains two R candidates" in SCENARIO_REVIEW_SYSTEM_PROMPT
    assert "In that R-batch case" in SCENARIO_REVIEW_SYSTEM_PROMPT


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
    assert set(result.revisions[0].rebuilt_dependency_sha256) == {"material_facts", "fact_pairs"}
    assert len(result.reviews) == 2


def test_combined_review_receives_three_use_case_candidates() -> None:
    """Review R1-R2 together against the fixed C1 comparison anchor."""
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
    expected_ids = {"CF001_C1", "CF001_R1", "CF001_R2"}
    assert set(results) == {"CF001_R1", "CF001_R2"}
    assert backend.observed_batches == [sorted(expected_ids)]


def test_calibration_candidates_receive_individual_semantic_reviews() -> None:
    """Review each C1 alone without comparing unrelated task families."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
    )
    backend = BatchAcceptBackend()
    use_cases = [cast(V10UseCaseSeed, use_case) for use_case in seed.use_cases]
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
