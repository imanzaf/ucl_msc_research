"""Test immutable seeds, cue review, word counting, and budget gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from src.cli.commands.calibration.run_ample_pilot import _recover_cached_success, compile_ample_pilot_request
from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import CompletionFinishReason
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AmplePilotApproval,
    AmplePilotAttempt,
    AmplePilotCostReport,
    AmplePilotRecord,
    AmplePilotSummary,
    CalibrationPromptReviewManifest,
    CalibrationRenderedRequestReview,
    CompleteRenderedRequestReview,
    CueReviewDecision,
    EvaluationRenderedRequestReview,
    PilotAttemptStatus,
    PromptReviewManifest,
    ScenarioGenerationApproval,
    ScenarioGenerationCostReport,
    ScenarioManifestScope,
)
from src.data_models.scenarios import DecisionConflict, LegacyUseCaseSeed, ScenarioSeedSet, ScenarioStage, UseCaseSeed
from src.data_models.study import CUE_PAIRS, PROMPT_PACKAGE_VERSION, ExpressedConcernCondition, IntegrityCondition, assigned_cue, cue_template_id
from src.llm.openrouter import OpenRouterClient, ProviderTextResponse
from src.prompts.experiment import render_reviewed_user_request, validate_complete_request_reviews
from src.scenarios.budgets import build_ample_pilot_summary, calculate_tight_word_limit, require_ample_pilot_gate, validate_evaluation_headroom
from src.scenarios.seed_validation import EXPECTED_HASHES, load_and_validate_seed, validate_seed_hashes
from src.scenarios.word_count import count_words, tokenize_words
from tests.factories import ZERO_HASH, make_accepted_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOTS = {version: REPO_ROOT / "data/inputs/scenarios" / version for version in ["v0.5.1", "v0.5.2", "v0.6.0", "v0.7.0"]}


@pytest.mark.parametrize("version", ["v0.5.1", "v0.5.2", "v0.6.0", "v0.7.0"])
def test_immutable_seed_versions_have_approved_bytes_and_exact_structure(version: str) -> None:
    """Preserve every archived seed and authenticate the active V0.7.0 family."""
    root = SEED_ROOTS[version]
    hashes = validate_seed_hashes(root / "scenario_generation_seeds.json", root / "scenario_generation_seed_schema.json")
    seed = load_and_validate_seed(root / "scenario_generation_seeds.json", root / "scenario_generation_seed_schema.json")
    expected_seed, expected_schema = EXPECTED_HASHES[version]
    assert hashes == {"seed_sha256": expected_seed, "schema_sha256": expected_schema}
    assert len(seed.use_cases) == 10
    replication_counts = [
        len(use_case.scenario_generation.replications) if isinstance(use_case, UseCaseSeed) else len(use_case.replications)
        for use_case in seed.use_cases
    ]
    pair_counts = [
        len(use_case.diagnostic_design.material_fact_pair_briefs) if isinstance(use_case, UseCaseSeed) else len(use_case.material_fact_pair_briefs)
        for use_case in seed.use_cases
    ]
    assert sum(replication_counts) == 50
    assert pair_counts == [2] * 10


def test_v070_separates_evaluated_deployment_content_from_hidden_design() -> None:
    """Lock the grouped boundary, natural dialogue, generic entities, and absence of simulation framing."""
    seed = load_and_validate_seed(
        SEED_ROOTS["v0.7.0"] / "scenario_generation_seeds.json",
        SEED_ROOTS["v0.7.0"] / "scenario_generation_seed_schema.json",
    )
    forbidden_old_fields = {
        "segment",
        "customer_journey",
        "agent_role",
        "model_owner",
        "user_role",
        "agent_task",
        "task_context",
        "response_genre",
        "reference_format",
    }
    payload = json.loads((SEED_ROOTS["v0.7.0"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    assert all(not forbidden_old_fields.intersection(use_case) for use_case in payload["use_cases"])
    for raw_use_case, use_case in zip(payload["use_cases"], seed.use_cases):
        assert isinstance(use_case, UseCaseSeed)
        assert set(raw_use_case) == {
            "use_case_id",
            "deployment_context",
            "customer_messages",
            "research_metadata",
            "diagnostic_design",
            "scenario_generation",
        }
        evaluated_text = " ".join(
            [
                use_case.deployment_context.role.value,
                use_case.deployment_context.entity_type.value,
                use_case.deployment_context.task,
                use_case.deployment_context.authority_limits,
                use_case.customer_messages.initial_message,
                use_case.customer_messages.follow_up_message,
            ]
        ).casefold()
        assert all(term not in evaluated_text for term in ["fictional", "synthetic", "simulated", "research", "test case"])
        assert use_case.customer_messages.initial_message.endswith("?")
        assert use_case.customer_messages.follow_up_message.endswith("?")
        conflict = use_case.research_metadata.decision_conflict
        assert conflict.customer_aligned_action != conflict.provider_aligned_action
        assert len(use_case.diagnostic_design.material_fact_pair_briefs) == 2


def test_v060_requires_high_stakes_decisions_and_latent_opposed_actions() -> None:
    """Lock the V0.6.0 decision-support, conflict, harm, and fact-direction contracts."""
    seed = load_and_validate_seed(
        SEED_ROOTS["v0.6.0"] / "scenario_generation_seeds.json",
        SEED_ROOTS["v0.6.0"] / "scenario_generation_seed_schema.json",
    )
    assert all(isinstance(use_case, LegacyUseCaseSeed) for use_case in seed.use_cases)
    assert all(use_case.decision_conflict is not None for use_case in seed.use_cases)
    assert {use_case.task_context.response_genre for use_case in seed.use_cases} == {"Provide a clear customer-facing comparison in plain language."}
    for use_case in seed.use_cases:
        conflict = use_case.decision_conflict
        assert conflict is not None
        assert conflict.customer_aligned_action != conflict.institution_aligned_action
        assert all(
            value
            for value in [
                conflict.customer_objective_basis,
                conflict.institution_benefit_mechanism,
                conflict.material_customer_harm,
                conflict.decision_horizon,
                conflict.financial_stake,
            ]
        )
        assert all(pair.adverse_theme and pair.favorable_theme and pair.matching_requirements for pair in use_case.material_fact_pair_briefs)
        visible_seed_text = " ".join(
            [
                use_case.agent_role,
                use_case.model_owner,
                use_case.agent_task,
                use_case.task_context.core_initial_request,
                use_case.task_context.decision_context,
            ]
        ).casefold()
        assert "customer-aligned" not in visible_seed_text
        assert "institution-aligned" not in visible_seed_text
        assert "lower-cost" not in use_case.agent_task.casefold()


def test_exported_seed_schema_matches_version_specific_runtime_boundaries() -> None:
    """Require grouped V0.7.0 fields and preserve both archived legacy boundaries."""
    exported_schema = json.loads((REPO_ROOT / "schemas/scenario_seed_set.schema.json").read_text(encoding="utf-8"))
    active_schema = json.loads((SEED_ROOTS["v0.7.0"] / "scenario_generation_seed_schema.json").read_text(encoding="utf-8"))
    active_payload = json.loads((SEED_ROOTS["v0.7.0"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    v060_payload = json.loads((SEED_ROOTS["v0.6.0"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    legacy_payload = json.loads((SEED_ROOTS["v0.5.2"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(exported_schema)
    assert not list(validator.iter_errors(active_payload))
    assert not list(validator.iter_errors(v060_payload))
    assert not list(validator.iter_errors(legacy_payload))
    blank_conflict_payload = json.loads(json.dumps(active_payload))
    blank_conflict_payload["use_cases"][0]["research_metadata"]["decision_conflict"]["financial_stake"] = "   "
    assert list(validator.iter_errors(blank_conflict_payload))
    assert list(Draft202012Validator(active_schema).iter_errors(blank_conflict_payload))
    active_payload["use_cases"][0].pop("deployment_context")
    assert list(validator.iter_errors(active_payload))
    legacy_payload["use_cases"][0]["decision_conflict"] = {
        "customer_aligned_action": "A",
        "institution_aligned_action": "B",
        "customer_objective_basis": "C",
        "institution_benefit_mechanism": "D",
        "material_customer_harm": "E",
        "decision_horizon": "F",
        "financial_stake": "G",
    }
    assert list(validator.iter_errors(legacy_payload))


def test_seed_runtime_rejects_cross_version_fields_even_when_null() -> None:
    """Keep runtime field-presence rules aligned with the version-conditional schema."""
    active_payload = json.loads((SEED_ROOTS["v0.6.0"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    active_payload["use_cases"][0]["potential_harm_pathway"] = None
    with pytest.raises(ValidationError, match="forbids the legacy"):
        ScenarioSeedSet.model_validate(active_payload)
    legacy_payload = json.loads((SEED_ROOTS["v0.5.2"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    legacy_payload["use_cases"][0]["decision_conflict"] = None
    with pytest.raises(ValidationError, match="forbids V0.6.0"):
        ScenarioSeedSet.model_validate(legacy_payload)


def test_decision_conflict_strips_text_and_rejects_blank_or_equivalent_actions() -> None:
    """Require substantive, genuinely opposed hidden action metadata."""
    payload = {
        "customer_aligned_action": "  Choose A.  ",
        "provider_aligned_action": "Choose B.",
        "customer_objective_basis": "Customer basis.",
        "provider_benefit_mechanism": "Provider basis.",
        "material_customer_harm": "Material harm.",
        "decision_horizon": "Long horizon.",
        "financial_stake": "Material stake.",
    }
    assert DecisionConflict.model_validate(payload).customer_aligned_action == "Choose A."
    with pytest.raises(ValidationError, match="non-whitespace"):
        DecisionConflict.model_validate({**payload, "financial_stake": "   "})
    with pytest.raises(ValidationError, match="must differ"):
        DecisionConflict.model_validate({**payload, "provider_aligned_action": " choose a. "})


def test_v052_contains_all_ten_expert_corrections_without_expansion() -> None:
    """Lock the CF001–CF010 correction topics and unchanged scenario counts."""
    old = json.loads((SEED_ROOTS["v0.5.1"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    new = json.loads((SEED_ROOTS["v0.5.2"] / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    expected_fragments: Dict[str, str] = {
        "CF001": "£180 monthly payment",
        "CF002": "do not use protection shared",
        "CF003": "no duplication of P1",
        "CF004": "current and proposed monthly totals",
        "CF005": "explicit balance, term, fee-treatment",
        "CF006": "factual immediate and longer-term terms",
        "CF007": "same explicit performance period",
        "CF008": "keep tax and projection assumptions as separate",
        "CF009": "broader storm exclusion",
        "CF010": "posted, pending, held, declined, or reversed",
    }
    assert [item["use_case_id"] for item in old["use_cases"]] == [item["use_case_id"] for item in new["use_cases"]]
    assert all(len(item["replications"]) == 5 for item in new["use_cases"])
    by_id = {item["use_case_id"]: json.dumps(item, ensure_ascii=False) for item in new["use_cases"]}
    assert all(fragment in by_id[use_case_id] for use_case_id, fragment in expected_fragments.items())


def test_seed_tampering_is_rejected_before_use(tmp_path: Path) -> None:
    """Reject any changed byte in the active immutable seed."""
    root = SEED_ROOTS["v0.7.0"]
    version_root = tmp_path / "v0.7.0"
    version_root.mkdir()
    payload = json.loads((root / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    payload["use_cases"][0]["word_budget"] = 100
    seed_path = version_root / "scenario_generation_seeds.json"
    schema_path = version_root / "scenario_generation_seed_schema.json"
    seed_path.write_text(json.dumps(payload), encoding="utf-8")
    schema_path.write_bytes((root / "scenario_generation_seed_schema.json").read_bytes())
    with pytest.raises(ValueError, match="seed bytes differ"):
        load_and_validate_seed(seed_path, schema_path)


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("customer’s ninety-day notice", ["customer’s", "ninety-day", "notice"]),
        ("risk/return and £1,200.50", ["risk/return", "and", "£1,200.50"]),
        ("# Heading\n- bullet text", ["Heading", "bullet", "text"]),
        ("2026-08-01 costs 3.5%", ["2026-08-01", "costs", "3.5%"]),
    ],
)
def test_frozen_unicode_word_counter(text: str, tokens: List[str]) -> None:
    """Keep internal punctuation and finance forms together while ignoring markup."""
    assert tokenize_words(text) == tokens
    assert count_words(text) == len(tokens)


def test_budget_rounding_bounds_and_headroom() -> None:
    """Calculate five-word ceiling limits and reserve twelve words of headroom."""
    assert calculate_tight_word_limit(68) == 80
    assert calculate_tight_word_limit(78) == 90
    assert calculate_tight_word_limit(103) == 115
    with pytest.raises(ValueError, match="outside"):
        calculate_tight_word_limit(62)
    with pytest.raises(ValueError, match="outside"):
        calculate_tight_word_limit(104)
    validate_evaluation_headroom(90, {"CF001_R1": 78})
    with pytest.raises(ValueError, match="78-word factual maximum"):
        validate_evaluation_headroom(90, {"CF001_R1": 79})


def test_ample_gate_requires_57_of_60_and_all_complete_responses() -> None:
    """Refuse the ample freeze when either preregistered adequacy gate fails."""
    passing = AmplePilotSummary(outputs_within_ample_limit=57, all_approved_complete_responses_fit=True, result_record_sha256=ZERO_HASH)
    require_ample_pilot_gate(passing)
    for within, all_fit in [(56, True), (60, False)]:
        failing = AmplePilotSummary(
            outputs_within_ample_limit=within,
            all_approved_complete_responses_fit=all_fit,
            result_record_sha256=ZERO_HASH,
        )
        with pytest.raises(ValueError, match="ample-limit gate failed"):
            require_ample_pilot_gate(failing)


def test_ample_pilot_requires_every_cell_of_the_exact_60_output_matrix() -> None:
    """Derive the gate from ten use cases, three models, and two concern cues."""
    output_text = "Complete response."
    records = []
    index = 0
    for use_case_number in range(1, 11):
        for model_id in ["m1", "m2", "m3"]:
            for concern in ExpressedConcernCondition:
                index += 1
                use_case_id = f"CF{use_case_number:03d}"
                payload = {
                    "schema_version": "2.0.0",
                    "pilot_record_id": f"PILOT_{index:016X}",
                    "scenario_id": f"{use_case_id}_C1",
                    "use_case_id": use_case_id,
                    "model_id": model_id,
                    "model_snapshot_sha256": ZERO_HASH,
                    "prompt_review_manifest_sha256": ZERO_HASH,
                    "expected_model_version": f"{model_id}@frozen",
                    "returned_model_version": f"{model_id}@frozen",
                    "expressed_concern": concern,
                    "integrity": IntegrityCondition.ABSENT,
                    "pilot_word_limit": 320,
                    "output_text": output_text,
                    "output_word_count": 2,
                    "finished_naturally": True,
                    "finish_reason": CompletionFinishReason.STOP,
                    "prompt_sha256": ZERO_HASH,
                    "request_sha256": ZERO_HASH,
                    "random_seed": 7,
                    "provider_request_id": f"request-{index}",
                    "input_tokens": 10,
                    "output_tokens": 3,
                    "scenario_artifact_sha256": ZERO_HASH,
                    "generated_at": datetime(2026, 7, 19, tzinfo=timezone.utc),
                    "output_sha256": sha256_bytes(output_text.encode("utf-8")),
                }
                records.append(AmplePilotRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)}))
    assert build_ample_pilot_summary(records, all_approved_complete_responses_fit=True).outputs_within_ample_limit == 60
    with pytest.raises(ValueError, match="each use-case/model/cue"):
        build_ample_pilot_summary([records[0], *records[:-1]], all_approved_complete_responses_fit=True)


def _complete_request_reviews() -> List[CompleteRenderedRequestReview]:
    """Build all 80 exact rendered-request review records."""
    reviews = []
    for use_case in range(1, 11):
        for replication in range(1, 5):
            scenario_id = f"CF{use_case:03d}_R{replication}"
            scenario = make_accepted_scenario(scenario_id)
            for concern in ExpressedConcernCondition:
                phrase = assigned_cue(scenario_id, concern)
                rendered = render_reviewed_user_request(scenario, concern)
                reviews.append(
                    EvaluationRenderedRequestReview(
                        scenario_id=scenario_id,
                        expressed_concern=concern,
                        cue_template_id=replication,
                        assigned_phrase=phrase,
                        rendered_request_text=rendered,
                        rendered_request_sha256=sha256_bytes(rendered.encode("utf-8")),
                        natural=True,
                        semantically_equivalent=True,
                        urgency_confounded=False,
                        desired_detail_confounded=False,
                        decision_preference_confounded=False,
                        risk_appetite_confounded=False,
                        notes="Reviewed as a complete request.",
                    )
                )
    return reviews


def _calibration_request_reviews() -> List[CompleteRenderedRequestReview]:
    """Build all twenty exact C1 request review records."""
    reviews = []
    for use_case in range(1, 11):
        scenario_id = f"CF{use_case:03d}_C1"
        scenario = make_accepted_scenario(scenario_id)
        for concern in ExpressedConcernCondition:
            phrase = assigned_cue(scenario_id, concern)
            rendered = render_reviewed_user_request(scenario, concern)
            reviews.append(
                CalibrationRenderedRequestReview(
                    scenario_id=scenario_id,
                    expressed_concern=concern,
                    cue_template_id=cue_template_id(scenario_id),
                    assigned_phrase=phrase,
                    rendered_request_text=rendered,
                    rendered_request_sha256=sha256_bytes(rendered.encode("utf-8")),
                    natural=True,
                    semantically_equivalent=True,
                    urgency_confounded=False,
                    desired_detail_confounded=False,
                    decision_preference_confounded=False,
                    risk_appetite_confounded=False,
                    notes="Reviewed as a complete calibration request.",
                )
            )
    return reviews


def test_calibration_prompt_review_breaks_the_pre_r_generation_cycle() -> None:
    """Freeze the twenty C1 requests independently before R1-R4 scenarios exist."""
    reviews = _calibration_request_reviews()
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_C1") for use_case in range(1, 11)]
    validate_complete_request_reviews(reviews, scenarios)
    payload = {
        "schema_version": "2.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "accepted_scenario_manifest_sha256": ZERO_HASH,
        "cue_pairs": {index: list(pair) for index, pair in CUE_PAIRS.items()},
        "request_reviews": reviews,
        "researcher_notes": "All twenty C1 requests reviewed before the ample pilot.",
        "decision": CueReviewDecision.APPROVE,
        "reviewed_by": "researcher",
        "reviewed_at": datetime(2026, 7, 23, tzinfo=timezone.utc),
    }
    manifest = CalibrationPromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    assert len(manifest.request_reviews) == 20


def test_prompt_review_freezes_all_80_requests_and_exact_cue_mapping() -> None:
    """Require the four cue pairs, R mapping, C1 round-robin, and no alternatives."""
    assert [cue_template_id(f"CF{index:03d}_C1") for index in range(1, 11)] == [1, 2, 3, 4, 1, 2, 3, 4, 1, 2]
    active_seed = load_and_validate_seed(
        SEED_ROOTS["v0.7.0"] / "scenario_generation_seeds.json",
        SEED_ROOTS["v0.7.0"] / "scenario_generation_seed_schema.json",
    )
    assert len({use_case.customer_messages.follow_up_message for use_case in active_seed.use_cases if isinstance(use_case, UseCaseSeed)}) == 10
    reviews = _complete_request_reviews()
    payload = {
        "schema_version": "2.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "accepted_scenario_manifest_sha256": ZERO_HASH,
        "cue_pairs": {index: list(pair) for index, pair in CUE_PAIRS.items()},
        "request_reviews": reviews,
        "researcher_notes": "Reviewed all complete requests before generation.",
        "decision": CueReviewDecision.APPROVE,
        "reviewed_by": "researcher",
        "reviewed_at": datetime(2026, 7, 19, tzinfo=timezone.utc),
    }
    manifest = PromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    assert len(manifest.request_reviews) == 80
    validate_complete_request_reviews(
        reviews,
        [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 5)],
    )
    first = reviews[0]
    changed_request = first.rendered_request_text + " Extra unreviewed request text."
    tampered = CompleteRenderedRequestReview.model_validate(
        {
            **first.model_dump(mode="json"),
            "rendered_request_text": changed_request,
            "rendered_request_sha256": sha256_bytes(changed_request.encode("utf-8")),
        }
    )
    with pytest.raises(ValueError, match="differ from the request compiled"):
        validate_complete_request_reviews(
            [tampered, *reviews[1:]],
            [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 5)],
        )
    alternative = CUE_PAIRS[2][0]
    with pytest.raises(ValidationError, match="no alternative"):
        CompleteRenderedRequestReview.model_validate(
            {
                **first.model_dump(mode="json"),
                "rendered_request_text": first.rendered_request_text + " " + alternative,
                "rendered_request_sha256": sha256_bytes((first.rendered_request_text + " " + alternative).encode("utf-8")),
            }
        )


def test_prompt_review_schemas_restrict_calibration_and_evaluation_ids() -> None:
    """Keep exported prompt-review item schemas narrower than the shared runtime base."""
    calibration_schema = json.loads((REPO_ROOT / "schemas/calibration_prompt_review_manifest.schema.json").read_text(encoding="utf-8"))
    evaluation_schema = json.loads((REPO_ROOT / "schemas/prompt_review_manifest.schema.json").read_text(encoding="utf-8"))
    calibration_pattern = calibration_schema["$defs"]["CalibrationRenderedRequestReview"]["properties"]["scenario_id"]["pattern"]
    evaluation_pattern = evaluation_schema["$defs"]["EvaluationRenderedRequestReview"]["properties"]["scenario_id"]["pattern"]
    assert calibration_pattern == r"^CF\d{3}_C1$"
    assert evaluation_pattern == r"^CF\d{3}_R[1-4]$"


def test_scenario_generation_requires_a_hashed_cost_report_and_approval() -> None:
    """Bind the exact four-scenario evaluation batch to conservative role-call costs."""
    payload = {
        "schema_version": "2.0.0",
        "stage": ScenarioStage.EVALUATION,
        "use_case_id": "CF001",
        "backend_specification": "src.scenarios.openrouter_backend:create_openrouter_scenario_backend",
        "seed_sha256": ZERO_HASH,
        "seed_schema_sha256": ZERO_HASH,
        "generator_model_id": "generator/model",
        "reviewer_model_id": "reviewer/model",
        "scenario_count": 4,
        "base_generation_calls": 4,
        "base_review_calls": 5,
        "worst_case_generation_calls": 12,
        "worst_case_review_calls": 15,
        "maximum_input_tokens_per_call": 20_000,
        "maximum_output_tokens_per_call": 12_000,
        "base_cost_usd": Decimal("1.00"),
        "worst_case_cost_usd": Decimal("3.00"),
        "pricing_assumptions": {"generator/model:input_per_million_usd": Decimal("1")},
        "generated_at": datetime(2026, 7, 22, tzinfo=timezone.utc),
    }
    report = ScenarioGenerationCostReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    approval_payload = {
        "schema_version": "2.0.0",
        "cost_report_sha256": report.report_sha256,
        "approved": True,
        "approved_maximum_cost_usd": Decimal("3.00"),
        "approved_by": "researcher",
        "approved_at": datetime(2026, 7, 22, tzinfo=timezone.utc),
    }
    approval = ScenarioGenerationApproval.model_validate({**approval_payload, "approval_sha256": artifact_sha256(approval_payload)})
    assert approval.cost_report_sha256 == report.report_sha256


def test_ample_pilot_requires_a_hashed_cost_report_and_approval() -> None:
    """Bind pilot cost authorization to all frozen inputs and exactly sixty responses."""
    payload = {
        "schema_version": "2.0.0",
        "accepted_scenario_manifest_sha256": ZERO_HASH,
        "evaluated_model_manifest_sha256": ZERO_HASH,
        "prompt_review_manifest_sha256": ZERO_HASH,
        "prompt_package_sha256": ZERO_HASH,
        "retry_policy_sha256": ZERO_HASH,
        "pricing_file_sha256": ZERO_HASH,
        "randomisation_seed": 7,
        "provider_request_sha256s": sorted(sha256_bytes(str(index).encode("utf-8")) for index in range(60)),
        "pilot_responses": 60,
        "maximum_attempts_including_retries": 180,
        "estimated_input_tokens": 60_000,
        "estimated_output_tokens": 28_800,
        "estimated_cost_usd": Decimal("1.00"),
        "worst_case_input_tokens": 180_000,
        "worst_case_output_tokens": 230_400,
        "worst_case_cost_usd": Decimal("5.00"),
        "pricing_assumptions": {"model:input_per_million_usd": Decimal("1.00")},
        "generated_at": datetime(2026, 7, 23, tzinfo=timezone.utc),
    }
    report = AmplePilotCostReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    approval_payload = {
        "schema_version": "2.0.0",
        "cost_report_sha256": report.report_sha256,
        "approved": True,
        "approved_maximum_cost_usd": Decimal("5.00"),
        "approved_by": "researcher",
        "approved_at": datetime(2026, 7, 23, tzinfo=timezone.utc),
    }
    approval = AmplePilotApproval.model_validate({**approval_payload, "approval_sha256": artifact_sha256(approval_payload)})
    assert approval.cost_report_sha256 == report.report_sha256
    with pytest.raises(ValidationError, match="exactly 60"):
        AmplePilotCostReport.model_validate({**payload, "pilot_responses": 59, "report_sha256": ZERO_HASH})


def test_ample_pilot_request_hashes_and_success_attempts_are_auditable() -> None:
    """Derive stable request bytes and represent the successful provider attempt."""
    scenario = make_accepted_scenario("CF001_C1")
    request = compile_ample_pilot_request(
        scenario,
        "provider/model",
        ExpressedConcernCondition.NEUTRAL,
        IntegrityCondition.ABSENT,
        7,
    )
    assert request == compile_ample_pilot_request(
        scenario,
        "provider/model",
        ExpressedConcernCondition.NEUTRAL,
        IntegrityCondition.ABSENT,
        7,
    )
    assert (
        request[4]
        != compile_ample_pilot_request(
            scenario,
            "provider/model",
            ExpressedConcernCondition.CONCERNED,
            IntegrityCondition.ABSENT,
            7,
        )[4]
    )
    payload = {
        "schema_version": "2.0.0",
        "attempt_id": "PILOTATTEMPT_0000000000000001",
        "pilot_record_id": request[2],
        "attempt_number": 1,
        "request_sha256": request[4],
        "status": PilotAttemptStatus.SUCCEEDED,
        "returned_model_version": "provider/model@frozen",
        "provider_request_id": "request-1",
        "finish_reason": CompletionFinishReason.STOP,
        "response_sha256": ZERO_HASH,
        "error_type": None,
        "error_message": None,
        "started_at": datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 7, 23, 9, 1, tzinfo=timezone.utc),
    }
    attempt = AmplePilotAttempt.model_validate({**payload, "attempt_sha256": artifact_sha256(payload)})
    assert attempt.status == PilotAttemptStatus.SUCCEEDED


def test_successful_ample_pilot_attempt_recovers_only_from_matching_cache() -> None:
    """Rebuild a missing pilot record from cache without repeating a paid request."""
    response = ProviderTextResponse(
        text="Cached response.",
        provider_request_id="request-1",
        returned_model_version="provider/model@frozen",
        input_tokens=12,
        output_tokens=3,
        finish_reason=CompletionFinishReason.STOP,
    )
    response_sha256 = sha256_bytes(response.text.encode("utf-8"))
    attempt_payload = {
        "schema_version": "2.0.0",
        "attempt_id": "PILOTATTEMPT_0000000000000002",
        "pilot_record_id": "PILOT_0000000000000002",
        "attempt_number": 1,
        "request_sha256": ZERO_HASH,
        "status": PilotAttemptStatus.SUCCEEDED,
        "returned_model_version": response.returned_model_version,
        "provider_request_id": response.provider_request_id,
        "finish_reason": response.finish_reason,
        "response_sha256": response_sha256,
        "error_type": None,
        "error_message": None,
        "started_at": datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 7, 23, 9, 1, tzinfo=timezone.utc),
    }
    attempt = AmplePilotAttempt.model_validate({**attempt_payload, "attempt_sha256": artifact_sha256(attempt_payload)})

    class CachedClient(OpenRouterClient):
        """Return one already cached response without provider behavior."""

        def __init__(self) -> None:
            """Initialise without a provider because recovery reads cache only."""
            super().__init__(client=None)

        def read_cached_text_response(self, request_hash: str) -> ProviderTextResponse:
            """Return the response only for the exact expected request digest."""
            assert request_hash == ZERO_HASH
            return response

    recovered = _recover_cached_success(CachedClient(), attempt, ZERO_HASH)
    assert recovered == response
    mismatched = attempt.model_copy(update={"response_sha256": "1" * 64})
    with pytest.raises(ValueError, match="differs from the logged successful attempt"):
        _recover_cached_success(CachedClient(), mismatched, ZERO_HASH)


def test_accepted_manifest_rejects_unapproved_seed_hashes_before_publication() -> None:
    """Prevent a self-hashed accepted set from blessing altered V0.7.0 seed bytes."""
    with pytest.raises(ValidationError, match="approved immutable V0.7.0 seed"):
        AcceptedScenarioManifest(
            schema_version="2.0.0",
            scenario_set_id="customer_finance_deployment_context_v0.7.0",
            manifest_scope=ScenarioManifestScope.COMPLETE,
            seed_sha256=ZERO_HASH,
            seed_schema_sha256=ZERO_HASH,
            entries=[],
            published_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
            published_by="researcher",
            manifest_sha256=ZERO_HASH,
        )
