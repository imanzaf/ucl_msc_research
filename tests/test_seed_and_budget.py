"""Test immutable seeds, cue review, word counting, and budget gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest
from pydantic import ValidationError

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import CompletionFinishReason
from src.data_models.manifests import (
    AmplePilotRecord,
    AmplePilotSummary,
    CompleteRenderedRequestReview,
    CueReviewDecision,
    PromptReviewManifest,
    ScenarioGenerationApproval,
    ScenarioGenerationCostReport,
)
from src.data_models.scenarios import ScenarioStage
from src.data_models.study import (
    CUE_PAIRS,
    NATURAL_FOLLOW_UPS,
    PROMPT_PACKAGE_VERSION,
    ExpressedConcernCondition,
    IntegrityCondition,
    assigned_cue,
    cue_template_id,
)
from src.prompts.experiment import render_reviewed_user_request, validate_complete_request_reviews
from src.scenarios.budgets import build_ample_pilot_summary, calculate_tight_word_limit, require_ample_pilot_gate, validate_evaluation_headroom
from src.scenarios.seed_validation import EXPECTED_HASHES, load_and_validate_seed, validate_seed_hashes
from src.scenarios.word_count import count_words, tokenize_words
from tests.factories import ZERO_HASH, make_accepted_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOTS = {version: REPO_ROOT / "data/inputs/scenarios" / version for version in ["v0.5.1", "v0.5.2"]}


@pytest.mark.parametrize("version", ["v0.5.1", "v0.5.2"])
def test_immutable_seed_versions_have_approved_bytes_and_exact_structure(version: str) -> None:
    """Preserve V0.5.1 and authenticate its corrected V0.5.2 derivative."""
    root = SEED_ROOTS[version]
    hashes = validate_seed_hashes(root / "scenario_generation_seeds.json", root / "scenario_generation_seed_schema.json")
    seed = load_and_validate_seed(root / "scenario_generation_seeds.json", root / "scenario_generation_seed_schema.json")
    expected_seed, expected_schema = EXPECTED_HASHES[version]
    assert hashes == {"seed_sha256": expected_seed, "schema_sha256": expected_schema}
    assert len(seed.use_cases) == 10
    assert sum(len(use_case.replications) for use_case in seed.use_cases) == 50
    assert all(len(use_case.material_fact_pair_briefs) == 2 for use_case in seed.use_cases)


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
    """Reject any changed byte in the immutable corrected seed."""
    root = SEED_ROOTS["v0.5.2"]
    version_root = tmp_path / "v0.5.2"
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
                    CompleteRenderedRequestReview(
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


def test_prompt_review_freezes_all_80_requests_and_exact_cue_mapping() -> None:
    """Require the four cue pairs, R mapping, C1 round-robin, and no alternatives."""
    assert [cue_template_id(f"CF{index:03d}_C1") for index in range(1, 11)] == [1, 2, 3, 4, 1, 2, 3, 4, 1, 2]
    assert len(NATURAL_FOLLOW_UPS) == 10
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
