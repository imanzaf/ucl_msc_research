"""Test the generation-only scenario pipeline and OpenRouter boundary."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, List, cast

import pytest

from src.cli.commands.scenarios import generate as generate_command
from src.data_models.experiments import CompletionFinishReason
from src.data_models.scenario_review import ScenarioReviewHistory
from src.data_models.scenarios import CandidateScenario, ScenarioGenerationRunConfig, ScenarioUseCaseSeed, SeedOptionId
from src.llm.openrouter import ProviderStructuredResponse
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scenario_generation import SCENARIO_GENERATION_SYSTEM_PROMPT
from src.scenarios.acceptance import build_accepted_scenario
from src.scenarios.openrouter_backend import (
    GeneratedMaterialFactDraft,
    GeneratedOptionInformationDraft,
    OpenRouterScenarioBackend,
    ScenarioOptionInformationDraft,
)
from src.scenarios.pipeline import generate_initial_candidates
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json
from tests.factories import NOW, ZERO_HASH, make_accepted_scenario, make_candidate_scenario


class FactGenerationClient:
    """Return one option-information draft while recording generation requests."""

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


class CountingGenerationBackend:
    """Generate fixture candidates while recording C1 examples."""

    def __init__(self) -> None:
        """Initialise generation-call tracking."""
        self.generate_calls = 0
        self.observed_examples: List[List[str]] = []

    def generate_candidate(self, use_case: Any, replication: Any, fixed_c1_example: Any = None) -> CandidateScenario:
        """Return one candidate without exposing review or revision operations."""
        self.generate_calls += 1
        if fixed_c1_example is not None:
            self.observed_examples.append([fixed_c1_example.scenario_id, replication.scenario_id])
        return make_candidate_scenario(replication.scenario_id)


def make_fact_draft() -> ScenarioOptionInformationDraft:
    """Build one complete information record for each option."""
    return ScenarioOptionInformationDraft(
        options=[
            GeneratedOptionInformationDraft(
                option_id=SeedOptionId.OPTION_B,
                description="The balance may fall below zero up to an agreed limit.",
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
                description="A shortfall is transferred automatically from linked savings.",
                favourable_fact={
                    "fact_text": "No debit interest is charged when the sweep covers a shortfall.",
                    "specificity_markers": [],
                },
                adverse_fact={
                    "fact_text": "Transferred money stops earning the linked account's 4.00% AER.",
                    "specificity_markers": ["4.00% AER"],
                },
            ),
        ]
    )


def active_use_case() -> ScenarioUseCaseSeed:
    """Load the first active task family."""
    seed = load_and_validate_seed(
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    return cast(ScenarioUseCaseSeed, seed.use_cases[0])


def test_generation_boundary_discards_invalid_specificity_markers() -> None:
    """Retain only numeric markers copied exactly from the fact."""
    fact = GeneratedMaterialFactDraft(
        fact_text="The service costs £25 each month for 12 months.",
        specificity_markers=["£25", "each month", "12 months", "£50"],
    )
    assert fact.specificity_markers == ["£25", "12 months"]


def test_openrouter_backend_generates_one_candidate_without_a_reviewer() -> None:
    """Make one generation call and assemble a hash-valid candidate."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    client = FactGenerationClient(make_fact_draft())
    backend = OpenRouterScenarioBackend(
        generation_client=cast(Any, client),
        generator_model_id="generator/model",
    )

    candidate = backend.generate_candidate(use_case, replication)

    assert candidate.scenario_id == replication.scenario_id
    assert len(client.messages) == 1
    rendered = client.messages[0][1]["content"]
    assert replication.customer_messages.neutral_user_query not in rendered
    assert replication.customer_messages.concerned_user_query not in rendered


def test_openrouter_backend_includes_published_c1_as_r_generation_example() -> None:
    """Render only C1 option information as the published example for R generation."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_R1")
    client = FactGenerationClient(make_fact_draft())
    backend = OpenRouterScenarioBackend(cast(Any, client), "generator/model")
    calibration = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    c1_candidate = backend.generate_candidate(use_case, calibration)
    _, c1 = build_accepted_scenario(
        c1_candidate,
        ScenarioReviewHistory(schema_version="3.4.0", scenario_id="CF001_C1"),
        NOW,
        "researcher",
    )
    client.messages.clear()

    payload = backend._generation_payload(use_case, replication, c1)
    backend.generate_candidate(use_case, replication, fixed_c1_example=c1)

    rendered = client.messages[0][1]["content"]
    assert set(payload["c1_example"]) == {"options"}
    assert c1.options[0].favourable_fact.fact_text in rendered
    assert c1.hidden_design.decision_type not in rendered
    assert c1.hidden_design.owner_benefit_mechanism not in rendered
    assert all(option.option_name not in rendered for option in c1.hidden_design.options)
    assert c1.customer_messages.neutral_user_query not in rendered
    assert replication.decision_type in rendered
    assert replication.owner_benefit_mechanism in rendered


def test_pipeline_generates_once_without_review_or_revision_methods() -> None:
    """The active pipeline requires only generate_candidate on its backend."""
    use_case = active_use_case()
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_C1")
    backend = CountingGenerationBackend()

    result = generate_initial_candidates([(use_case, replication)], backend)

    assert list(result) == ["CF001_C1"]
    assert backend.generate_calls == 1


def test_evaluation_generation_requires_and_uses_matching_c1_example() -> None:
    """Pass the same-family C1 example to each selected R candidate."""
    use_case = active_use_case()
    evaluation = [(use_case, item) for item in use_case.replications if not item.scenario_id.endswith("_C1")]
    backend = CountingGenerationBackend()
    c1 = make_accepted_scenario("CF001_C1")

    result = generate_initial_candidates(evaluation, backend, {use_case.use_case_id: c1})

    assert set(result) == {"CF001_R1", "CF001_R2"}
    assert backend.observed_examples == [["CF001_C1", "CF001_R1"], ["CF001_C1", "CF001_R2"]]
    with pytest.raises(ValueError, match="requires the matching published C1"):
        generate_initial_candidates(evaluation, CountingGenerationBackend())
    with pytest.raises(ValueError, match="must be published"):
        generate_initial_candidates(evaluation, CountingGenerationBackend(), {use_case.use_case_id: make_candidate_scenario("CF001_C1")})


def test_named_runs_reopen_even_after_active_input_hashes_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep existing candidate runs editable instead of treating input changes as a gate."""
    monkeypatch.setattr(generate_command, "scenario_generation_run_root", lambda run_id: tmp_path / run_id)
    run_id, run_root = generate_command._prepare_run_root("scenario_set_v1")
    config = read_model_json(run_root / "run_config.json", ScenarioGenerationRunConfig)
    config_payload = config.model_dump(mode="json")
    config_payload["query_sha256"] = "1" * 64
    (run_root / "run_config.json").write_text(ScenarioGenerationRunConfig.model_validate(config_payload).model_dump_json(indent=2))

    reopened_id, reopened_root = generate_command._prepare_run_root(run_id)

    assert reopened_id == run_id
    assert reopened_root == run_root


def test_cli_generation_writes_candidates_without_review_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist initial R1 and R2 candidates without terminal review decisions."""
    output_root = tmp_path / "scenario_generation" / "v3.0.0"
    run_id = "scenario_set_v1"
    round_ids = iter(["20260726T120100000001Z", "20260726T120200000001Z"])
    backend = CountingGenerationBackend()
    monkeypatch.setattr(generate_command, "ACTIVE_SCENARIO_GENERATION_ROOT", output_root)
    monkeypatch.setattr(generate_command, "scenario_generation_round_id", lambda: next(round_ids))
    monkeypatch.setattr(generate_command, "scenario_generation_run_root", lambda value: output_root / value)
    monkeypatch.setattr(generate_command, "_load_backend", lambda _specification, _invocation_root: backend)
    monkeypatch.setattr(
        generate_command,
        "_load_evaluation_example",
        lambda _use_case_id: make_accepted_scenario("CF001_C1"),
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
    monkeypatch.setattr(sys, "argv", [*base_arguments, "--scenario-id", "CF001_R2"])
    generate_command.main()

    run_root = output_root / run_id
    candidate_paths = sorted(run_root.glob("*/scenarios/CF001_R?/candidate.json"))
    assert len(candidate_paths) == 2
    assert not list(run_root.glob("*/scenarios/*/automated_reviews.jsonl"))
    assert not list(run_root.glob("*/scenarios/*/terminal_decision.json"))
    assert backend.generate_calls == 2


def test_generation_prompt_describes_initial_drafting_not_review_gates() -> None:
    """Keep the model contract focused on drafting option information."""
    assert "For each of the two supplied options, generate" in SCENARIO_GENERATION_SYSTEM_PROMPT
    assert "automated review" not in SCENARIO_GENERATION_SYSTEM_PROMPT.casefold()


def test_evaluation_example_resolves_the_current_published_c1() -> None:
    """Read the matching C1 only from the published records."""
    resolved = generate_command._load_evaluation_example("CF001")
    assert resolved.scenario_id == "CF001_C1"
    assert resolved.use_case_id == "CF001"


def test_evaluation_example_requires_a_published_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not treat a same-run draft C1 as an R-generation example."""
    monkeypatch.setattr(generate_command, "ACTIVE_SCENARIO_ACCEPTED_ROOT", tmp_path)
    with pytest.raises(ValueError, match="requires published scenario CF001_C1"):
        generate_command._load_evaluation_example("CF001")
