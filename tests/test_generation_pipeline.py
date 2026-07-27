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
from src.data_models.common import artifact_sha256, sha256_bytes, utc_now
from src.data_models.experiments import CompletionFinishReason
from src.data_models.manifests import AmplePilotSummary, CalibrationUseCaseBudget, FreezeStatus, TightLimitManifest
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    FindingSeverity,
    ResearcherScenarioReview,
    ReviewDecision,
    ReviewFinding,
)
from src.data_models.scenarios import (
    CandidateScenario,
    ScenarioGenerationInvocationConfig,
    ScenarioGenerationRunConfig,
    ScenarioStage,
    SeedOptionId,
    V100ReplicationSeed,
    V100UseCaseSeed,
)
from src.llm.openrouter import OpenRouterClient, ProviderStructuredResponse
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT, SCENARIO_REVIEW_SYSTEM_PROMPT
from src.scenarios.budgets import material_fact_text_sha256, material_fact_word_count
from src.scenarios.openrouter_backend import (
    STRUCTURED_MAX_OUTPUT_TOKENS,
    GeneratedOptionInformationDraft,
    OpenRouterScenarioBackend,
    ScenarioGenerationInput,
    ScenarioOptionInformationDraft,
)
from src.scenarios.pair_diagnostics import build_pair_diagnostics
from src.scenarios.pipeline import default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, write_model_json_atomic, write_models_jsonl_atomic
from tests.factories import ZERO_HASH, make_candidate_scenario


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


def make_fact_draft() -> ScenarioOptionInformationDraft:
    """Build one complete product-information record for each option."""
    return ScenarioOptionInformationDraft(
        options=[
            GeneratedOptionInformationDraft(
                option_id=SeedOptionId.OPTION_B,
                description="The current-account balance may fall below zero up to an agreed limit.",
                favourable_fact="Payments are processed while the balance remains within the £500 limit.",
                adverse_fact="The negative balance is charged 39.9% EAR variable interest.",
            ),
            GeneratedOptionInformationDraft(
                option_id=SeedOptionId.OPTION_A,
                description="A shortfall is transferred automatically from the linked savings balance.",
                favourable_fact="No debit interest is charged when the sweep covers a shortfall.",
                adverse_fact="Transferred money stops earning the linked savings account's 4.00% AER.",
            ),
        ],
    )


def active_use_case() -> V100UseCaseSeed:
    """Load the first active V1.0.0 task family."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
    )
    return cast(V100UseCaseSeed, seed.use_cases[0])


class AlwaysReviseBackend:
    """Fake backend that proves one revision round ends in manual restructuring."""

    def __init__(self) -> None:
        """Create a backend with a stable candidate."""
        self.candidate = make_candidate_scenario()

    def generate_candidate(self, use_case: V100UseCaseSeed, replication: V100ReplicationSeed) -> CandidateScenario:
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
        use_case: V100UseCaseSeed,
        replication: V100ReplicationSeed,
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

    def generate_candidate(self, use_case: V100UseCaseSeed, replication: V100ReplicationSeed) -> CandidateScenario:
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
                reviewer_prompt_sha256=sha256_bytes(SCENARIO_REVIEW_SYSTEM_PROMPT.encode("utf-8")),
                reviewed_at=utc_now(),
            )
            for candidate in candidates
        ]

    def revise_candidate(
        self,
        use_case: V100UseCaseSeed,
        replication: V100ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Reject an impossible revision call in this accepting fixture."""
        raise AssertionError("accepted candidates must not enter revision")


class ResearcherRevisionBackend(BatchAcceptBackend):
    """Regenerate one fixture candidate while capturing researcher feedback."""

    def __init__(self) -> None:
        """Initialise batch tracking and captured revision text."""
        super().__init__()
        self.researcher_feedback: str | None = None
        self.revision_calls = 0

    def revise_candidate(
        self,
        use_case: V100UseCaseSeed,
        replication: V100ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Change one generated fact and bind the new candidate to its parent."""
        self.revision_calls += 1
        self.researcher_feedback = reviews[0].findings[0].message
        facts = list(candidate.material_facts)
        facts[0] = facts[0].model_copy(update={"canonical_proposition": f"{facts[0].canonical_proposition} Clarified."})
        payload = candidate.model_dump(mode="json", exclude={"candidate_sha256"})
        payload["material_facts"] = [fact.model_dump(mode="json") for fact in facts]
        payload["provenance"] = candidate.provenance.model_copy(update={"parent_sha256": candidate.candidate_sha256}).model_dump(mode="json")
        revised = CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})
        return revised, [
            ControlledFieldChange(
                field_path="material_facts",
                previous_value_sha256=artifact_sha256(candidate.material_facts),
                revised_value_sha256=artifact_sha256(revised.material_facts),
                reason=f"Resolve researcher feedback in cycle {cycle_number}.",
                finding_ids=[finding.finding_id for review in reviews for finding in review.findings],
            )
        ]


def test_openrouter_backend_generates_option_information_in_one_call() -> None:
    """Build a V5.0 candidate with two descriptions and four directional facts."""
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
        "neutral_user_query",
        "owner_supporting_option",
        "owner_benefit_mechanism",
    }
    assert candidate.schema_version == "5.0.0"
    assert len(candidate.option_descriptions) == 2
    assert [description.option_id for description in candidate.option_descriptions] == replication.presentation_order
    assert len(candidate.material_facts) == 4
    assert all("OPTION_A" not in fact.canonical_proposition and "OPTION_B" not in fact.canonical_proposition for fact in candidate.material_facts)
    assert all("source_support" not in type(fact).model_fields for fact in candidate.material_facts)
    assert candidate.provenance.provider_calls[0].usage.cost_credits == Decimal("0.01")


def test_generation_contract_contains_only_option_information() -> None:
    """Keep option information free of evidence, numeric, or specificity registries."""
    payload = make_fact_draft().model_dump(mode="json")
    assert list(payload) == ["options"]
    assert set(payload["options"][0]) == {"option_id", "description", "favourable_fact", "adverse_fact"}
    assert "evidence" not in json.dumps(payload).casefold()
    assert "numeric" not in json.dumps(payload).casefold()
    assert "specificity" not in json.dumps(payload).casefold()
    assert STRUCTURED_MAX_OUTPUT_TOKENS == 2_000


def test_generation_prompt_requests_documentation_style_option_information() -> None:
    """Keep the generator's single task factual and explicit."""
    assert "Treat each option as one fixed synthetic configuration" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`description`: one neutral statement" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`favourable_fact`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "`adverse_fact`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "The owner field controls which" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "Use `option_id` only as structured mapping metadata" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "return only `options`" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "schema_version" not in SCENARIO_GENERATION_SYSTEM_PROMPT


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
    assert set(result.revisions[0].rebuilt_dependency_sha256) == {"option_descriptions", "material_facts", "fact_pairs"}
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
    use_cases = [cast(V100UseCaseSeed, use_case) for use_case in seed.use_cases]
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


def test_separate_evaluation_commands_complete_one_family_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist R1 first and trigger the shared review when R2 joins the same run."""
    output_root = tmp_path / "scenario_generation" / "v1.0.0"
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
    assert not (first_scenario_root / "CF001_R1" / "terminal_decision.json").exists()

    monkeypatch.setattr(sys, "argv", [*base_arguments, "--scenario-id", "CF001_R2"])
    generate_command.main()

    second_scenario_root = run_root / second_round_id / "scenarios"
    assert (second_scenario_root / "CF001_R1" / "terminal_decision.json").is_file()
    assert (second_scenario_root / "CF001_R2" / "terminal_decision.json").is_file()
    assert backend.generate_calls == 2
    assert backend.observed_batches == [["CF001_C1", "CF001_R1", "CF001_R2"]]
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
    candidate_payload = base_candidate.model_dump(mode="json", exclude={"candidate_sha256"})
    current_word_count = material_fact_word_count(base_candidate.material_facts)
    candidate_payload["material_facts"][0]["canonical_proposition"] += " " + " ".join(["documented"] * (68 - current_word_count))
    candidate = CandidateScenario.model_validate({**candidate_payload, "candidate_sha256": artifact_sha256(candidate_payload)})
    run_root = tmp_path / "c1_calibration_v1"
    write_model_json_atomic(
        run_root / "20260726T120000000001Z" / "scenarios" / candidate.scenario_id / "candidate.json",
        candidate,
    )
    researcher_review = ResearcherScenarioReview(
        schema_version="3.1.0",
        review_id="CF001_C1_REVIEW_CURRENT",
        anonymised_item_id="ITEM_CF001",
        scenario_id=candidate.scenario_id,
        decision=ReviewDecision.ACCEPT,
        reviewed_artifact_sha256=candidate.candidate_sha256,
        reviewed_at=utc_now(),
        researcher_id="researcher",
        notes="",
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


def test_researcher_directed_regeneration_uses_bound_notes_and_preserves_parent(tmp_path: Path) -> None:
    """Pass one revise note into regeneration and retain both immutable inputs."""
    scenario_id = "CF005_C1"
    parent = make_candidate_scenario(scenario_id)
    researcher_review = ResearcherScenarioReview(
        schema_version="3.1.0",
        review_id="CF005_C1_REVIEW_V1",
        anonymised_item_id="ITEM_CF005",
        scenario_id=scenario_id,
        decision=ReviewDecision.REVISE,
        pair_diagnostics=build_pair_diagnostics(parent),
        reviewed_artifact_sha256=parent.candidate_sha256,
        reviewed_at=utc_now(),
        researcher_id="researcher",
        notes="Clarify whether the fee is adverse and exactly which charges the new lender pays.",
    )
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
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
    assert backend.researcher_feedback == researcher_review.notes
    assert read_model_json(run_root / "inputs" / scenario_id / "parent_candidate.json", CandidateScenario) == parent
    assert read_model_json(run_root / "inputs" / scenario_id / "researcher_revision.json", ResearcherScenarioReview) == researcher_review


def test_named_run_regenerates_only_revise_cases_in_a_new_round(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Read current decisions and add only replacements under the same named run."""
    output_root = tmp_path / "scenario_generation" / "v1.0.0"
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
            schema_version="3.1.0",
            review_id="CF001_C1_REVIEW_V1",
            anonymised_item_id="ITEM_CF001",
            scenario_id="CF001_C1",
            decision=ReviewDecision.ACCEPT,
            reviewed_artifact_sha256=accepted_parent.candidate_sha256,
            reviewed_at=utc_now(),
            researcher_id="researcher",
            notes="",
        ),
        ResearcherScenarioReview(
            schema_version="3.1.0",
            review_id="CF002_C1_REVIEW_V1",
            anonymised_item_id="ITEM_CF002",
            scenario_id="CF002_C1",
            decision=ReviewDecision.REVISE,
            pair_diagnostics=build_pair_diagnostics(revised_parent),
            reviewed_artifact_sha256=revised_parent.candidate_sha256,
            reviewed_at=utc_now(),
            researcher_id="researcher",
            notes="Clarify the fee treatment.",
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
    assert backend.researcher_feedback == "Clarify the fee treatment."
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
