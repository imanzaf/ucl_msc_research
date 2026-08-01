"""Test immutable seeds, query review, word counting, and budget gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List

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
    EvaluationRenderedRequestReview,
    PilotAttemptStatus,
    PromptReviewDecision,
    PromptReviewManifest,
    ScenarioManifestScope,
)
from src.data_models.scenarios import ComparisonScope, LoadedScenarioSeedSet, ScenarioHiddenDesign, SeedOptionId
from src.data_models.study import PROMPT_PACKAGE_VERSION, ExpressedConcernCondition
from src.llm.openrouter import OpenRouterClient, ProviderTextResponse
from src.paths import ACTIVE_SCENARIO_INPUT_ROOT, ACTIVE_SCENARIO_SEED_VERSION
from src.prompts.experiment import render_reviewed_user_request, validate_complete_request_reviews
from src.scenarios.budgets import build_ample_pilot_summary, calculate_tight_word_limit, require_ample_pilot_gate, validate_evaluation_headroom
from src.scenarios.seed_validation import (
    EXPECTED_QUERY_SCHEMA_SHA256,
    EXPECTED_QUERY_SHA256,
    EXPECTED_SCHEMA_SHA256,
    EXPECTED_SEED_SHA256,
    load_and_validate_seed,
    validate_seed_hashes,
)
from src.scenarios.word_count import count_words, tokenize_words
from tests.factories import ZERO_HASH, make_accepted_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT


def load_active_seed() -> LoadedScenarioSeedSet:
    """Load the active joined scenario definitions and customer queries."""
    return load_and_validate_seed(
        SEED_ROOT / "scenario_generation_seeds.json",
        SEED_ROOT / "scenario_generation_seed_schema.json",
        SEED_ROOT / "scenario_customer_queries.json",
        SEED_ROOT / "scenario_customer_queries_schema.json",
    )


def test_active_seed_has_approved_bytes_and_exact_structure() -> None:
    """Authenticate the only runtime-supported V3.0.0 scenario inputs."""
    hashes = validate_seed_hashes(
        SEED_ROOT / "scenario_generation_seeds.json",
        SEED_ROOT / "scenario_generation_seed_schema.json",
        SEED_ROOT / "scenario_customer_queries.json",
        SEED_ROOT / "scenario_customer_queries_schema.json",
    )
    seed = load_active_seed()
    assert hashes == {
        "seed_sha256": EXPECTED_SEED_SHA256,
        "schema_sha256": EXPECTED_SCHEMA_SHA256,
        "query_sha256": EXPECTED_QUERY_SHA256,
        "query_schema_sha256": EXPECTED_QUERY_SCHEMA_SHA256,
    }
    assert len(seed.use_cases) == 10
    assert sum(len(use_case.replications) for use_case in seed.use_cases) == 30
    assert all(len({replication.decision_type for replication in use_case.replications}) == 3 for use_case in seed.use_cases)


def test_exported_seed_schemas_match_the_separate_active_boundaries() -> None:
    """Require exported schemas to enforce separate definition and query documents."""
    exported_schema = json.loads((REPO_ROOT / "schemas/scenario_seed_set.schema.json").read_text(encoding="utf-8"))
    exported_query_schema = json.loads((REPO_ROOT / "schemas/scenario_query_set.schema.json").read_text(encoding="utf-8"))
    active_schema = json.loads((SEED_ROOT / "scenario_generation_seed_schema.json").read_text(encoding="utf-8"))
    active_query_schema = json.loads((SEED_ROOT / "scenario_customer_queries_schema.json").read_text(encoding="utf-8"))
    active_payload = json.loads((SEED_ROOT / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    query_payload = json.loads((SEED_ROOT / "scenario_customer_queries.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(exported_schema)
    assert not list(validator.iter_errors(active_payload))
    assert not list(Draft202012Validator(exported_query_schema).iter_errors(query_payload))
    assert not list(Draft202012Validator(active_query_schema).iter_errors(query_payload))
    assert all("customer_messages" not in replication for family in active_payload["use_cases"] for replication in family["replications"])
    assert all(
        set(scenario) == {"scenario_id", "customer_messages"} for family in query_payload["scenario_families"] for scenario in family["scenarios"]
    )
    blank_design_payload = json.loads(json.dumps(active_payload))
    blank_design_payload["use_cases"][0]["replications"][0]["owner_benefit_mechanism"] = "   "
    assert list(validator.iter_errors(blank_design_payload))
    assert list(Draft202012Validator(active_schema).iter_errors(blank_design_payload))
    active_payload["use_cases"][0].pop("deployment_context")
    assert list(validator.iter_errors(active_payload))


def test_active_seed_enforces_stage_specific_provider_relationships() -> None:
    """Require R1 to compare internal options and R2 to identify one external alternative."""
    seed = load_active_seed()
    replications = [replication for use_case in seed.use_cases for replication in use_case.replications]
    for replication in replications:
        if replication.scenario_id.endswith("_R1"):
            assert replication.comparison_scope == ComparisonScope.INTRA_PROVIDER
            assert replication.external_option_id is None
        if replication.scenario_id.endswith("_R2"):
            assert replication.comparison_scope == ComparisonScope.PROVIDER_VS_EXTERNAL
            assert replication.external_option_id is not None
            assert replication.external_option_id != replication.owner_supporting_option


def test_hidden_design_requires_one_owner_option_and_distinct_option_names() -> None:
    """Require distinct option names and one valid owner-supporting option."""
    seed = load_active_seed()
    payload = seed.use_cases[0].replications[0].model_dump(mode="json", exclude={"scenario_id", "customer_messages"})
    assert ScenarioHiddenDesign.model_validate(payload).owner_supporting_option == SeedOptionId.OPTION_B
    payload["options"][1]["option_name"] = payload["options"][0]["option_name"]
    with pytest.raises(ValidationError, match="option names must be distinct"):
        ScenarioHiddenDesign.model_validate(payload)


def test_seed_tampering_is_rejected_before_use(tmp_path: Path) -> None:
    """Reject any changed byte in the active immutable seed."""
    root = SEED_ROOT
    version_root = tmp_path / ACTIVE_SCENARIO_SEED_VERSION
    version_root.mkdir()
    payload = json.loads((root / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    payload["use_cases"][0]["word_budget"] = 100
    seed_path = version_root / "scenario_generation_seeds.json"
    schema_path = version_root / "scenario_generation_seed_schema.json"
    query_path = version_root / "scenario_customer_queries.json"
    query_schema_path = version_root / "scenario_customer_queries_schema.json"
    seed_path.write_text(json.dumps(payload), encoding="utf-8")
    schema_path.write_bytes((root / "scenario_generation_seed_schema.json").read_bytes())
    query_path.write_bytes((root / "scenario_customer_queries.json").read_bytes())
    query_schema_path.write_bytes((root / "scenario_customer_queries_schema.json").read_bytes())
    with pytest.raises(ValueError, match="seed bytes differ"):
        load_and_validate_seed(seed_path, schema_path, query_path, query_schema_path)


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
    passing = AmplePilotSummary(outputs_within_ample_limit=57, all_material_fact_lists_fit=True, result_record_sha256=ZERO_HASH)
    require_ample_pilot_gate(passing)
    for within, all_fit in [(56, True), (60, False)]:
        failing = AmplePilotSummary(
            outputs_within_ample_limit=within,
            all_material_fact_lists_fit=all_fit,
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
    assert build_ample_pilot_summary(records, all_material_fact_lists_fit=True).outputs_within_ample_limit == 60
    with pytest.raises(ValueError, match="each use-case/model/cue"):
        build_ample_pilot_summary([records[0], *records[:-1]], all_material_fact_lists_fit=True)


def _complete_request_reviews() -> List[CompleteRenderedRequestReview]:
    """Build all 40 exact rendered-request review records."""
    reviews = []
    for use_case in range(1, 11):
        for replication in range(1, 3):
            scenario_id = f"CF{use_case:03d}_R{replication}"
            scenario = make_accepted_scenario(scenario_id)
            for concern in ExpressedConcernCondition:
                rendered = render_reviewed_user_request(scenario, concern)
                reviews.append(
                    EvaluationRenderedRequestReview(
                        scenario_id=scenario_id,
                        expressed_concern=concern,
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
            rendered = render_reviewed_user_request(scenario, concern)
            reviews.append(
                CalibrationRenderedRequestReview(
                    scenario_id=scenario_id,
                    expressed_concern=concern,
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
    """Freeze the twenty C1 requests independently before R1-R2 scenarios exist."""
    reviews = _calibration_request_reviews()
    scenarios = [make_accepted_scenario(f"CF{use_case:03d}_C1") for use_case in range(1, 11)]
    validate_complete_request_reviews(reviews, scenarios)
    payload = {
        "schema_version": "3.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "accepted_scenario_manifest_sha256": ZERO_HASH,
        "request_reviews": reviews,
        "researcher_notes": "All twenty C1 requests reviewed before the ample pilot.",
        "decision": PromptReviewDecision.APPROVE,
        "reviewed_by": "researcher",
        "reviewed_at": datetime(2026, 7, 23, tzinfo=timezone.utc),
    }
    manifest = CalibrationPromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    assert len(manifest.request_reviews) == 20


def test_prompt_review_freezes_all_40_seed_authored_requests() -> None:
    """Require one neutral/concerned pair per scenario and one shared generic follow-up."""
    active_seed = load_active_seed()
    replications = [replication for use_case in active_seed.use_cases for replication in use_case.replications]
    assert len({replication.customer_messages.follow_up_query for replication in replications}) == 1
    assert all(replication.customer_messages.neutral_user_query != replication.customer_messages.concerned_user_query for replication in replications)
    assert all("really worried" in replication.customer_messages.concerned_user_query.casefold() for replication in replications)
    reviews = _complete_request_reviews()
    payload = {
        "schema_version": "3.0.0",
        "prompt_version": PROMPT_PACKAGE_VERSION,
        "accepted_scenario_manifest_sha256": ZERO_HASH,
        "request_reviews": reviews,
        "researcher_notes": "Reviewed all complete requests before generation.",
        "decision": PromptReviewDecision.APPROVE,
        "reviewed_by": "researcher",
        "reviewed_at": datetime(2026, 7, 19, tzinfo=timezone.utc),
    }
    manifest = PromptReviewManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
    assert len(manifest.request_reviews) == 40
    validate_complete_request_reviews(
        reviews,
        [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 3)],
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
            [make_accepted_scenario(f"CF{use_case:03d}_R{replication}") for use_case in range(1, 11) for replication in range(1, 3)],
        )
    assert "cue_template_id" not in CompleteRenderedRequestReview.model_fields
    assert "assigned_phrase" not in CompleteRenderedRequestReview.model_fields


def test_prompt_review_schemas_restrict_calibration_and_evaluation_ids() -> None:
    """Keep exported prompt-review item schemas narrower than the shared runtime base."""
    calibration_schema = json.loads((REPO_ROOT / "schemas/calibration_prompt_review_manifest.schema.json").read_text(encoding="utf-8"))
    evaluation_schema = json.loads((REPO_ROOT / "schemas/prompt_review_manifest.schema.json").read_text(encoding="utf-8"))
    calibration_pattern = calibration_schema["$defs"]["CalibrationRenderedRequestReview"]["properties"]["scenario_id"]["pattern"]
    evaluation_pattern = evaluation_schema["$defs"]["EvaluationRenderedRequestReview"]["properties"]["scenario_id"]["pattern"]
    assert calibration_pattern == r"^CF\d{3}_C1$"
    assert evaluation_pattern == r"^CF\d{3}_R[12]$"


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
        7,
    )
    assert request == compile_ample_pilot_request(
        scenario,
        "provider/model",
        ExpressedConcernCondition.NEUTRAL,
        7,
    )
    assert (
        request[4]
        != compile_ample_pilot_request(
            scenario,
            "provider/model",
            ExpressedConcernCondition.CONCERNED,
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


def test_accepted_manifest_treats_input_hashes_as_provenance_not_publication_gates() -> None:
    """Allow changed authoring inputs while still requiring the selected downstream scope."""
    with pytest.raises(ValidationError, match="exact scenario ids required by its scope"):
        AcceptedScenarioManifest(
            schema_version="3.0.0",
            scenario_set_id="customer_facing_risk_communication_v2.0.0",
            manifest_scope=ScenarioManifestScope.COMPLETE,
            seed_sha256=ZERO_HASH,
            seed_schema_sha256=ZERO_HASH,
            query_sha256=ZERO_HASH,
            query_schema_sha256=ZERO_HASH,
            entries=[],
            published_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
            published_by="researcher",
            manifest_sha256=ZERO_HASH,
        )
