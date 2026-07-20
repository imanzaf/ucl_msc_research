"""Test seed provenance, exact structure, word counting, and budget gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest
from pydantic import ValidationError

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import CompletionFinishReason
from src.data_models.manifests import AmplePilotRecord, AmplePilotSummary, CueReviewDecision, PromptReviewManifest
from src.data_models.study import NEUTRAL_CUE, WORRIED_CUE, EmotionalCueCondition, IntegrityCondition
from src.scenarios.budgets import build_ample_pilot_summary, calculate_tight_word_limit, require_ample_pilot_gate, validate_evaluation_headroom
from src.scenarios.seed_validation import EXPECTED_SCHEMA_SHA256, EXPECTED_SEED_SHA256, load_and_validate_seed, validate_seed_hashes
from src.scenarios.word_count import count_words, tokenize_words
from tests.factories import ZERO_HASH

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = REPO_ROOT / "data/inputs/scenarios/v0.5.1"


def test_supplied_seed_and_schema_are_byte_identical_and_exactly_10_by_5() -> None:
    """Require approved byte hashes, ten use cases, and C1/R1-R4 per use case."""
    hashes = validate_seed_hashes(
        SEED_ROOT / "scenario_generation_seeds.json",
        SEED_ROOT / "scenario_generation_seed_schema.json",
    )
    seed = load_and_validate_seed(
        SEED_ROOT / "scenario_generation_seeds.json",
        SEED_ROOT / "scenario_generation_seed_schema.json",
    )

    assert hashes == {"seed_sha256": EXPECTED_SEED_SHA256, "schema_sha256": EXPECTED_SCHEMA_SHA256}
    assert len(seed.use_cases) == 10
    assert sum(len(use_case.replications) for use_case in seed.use_cases) == 50
    assert all(len(use_case.material_fact_pair_briefs) == 2 for use_case in seed.use_cases)
    assert all({brief.pair_slot.value for brief in use_case.material_fact_pair_briefs} == {"P1", "P2"} for use_case in seed.use_cases)
    assert "legacy_seed_extension" not in seed.model_dump()


def test_seed_schema_forbids_study_design_fields(tmp_path: Path) -> None:
    """Reject code-owned word-budget or treatment fields added to the immutable seed."""
    payload = json.loads((SEED_ROOT / "scenario_generation_seeds.json").read_text(encoding="utf-8"))
    payload["use_cases"][0]["word_budget"] = 100
    altered_seed = tmp_path / "scenario_generation_seeds.json"
    altered_seed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="approved supplied artifact"):
        load_and_validate_seed(altered_seed, SEED_ROOT / "scenario_generation_seed_schema.json")


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
    """Calculate 5-ceiling limits and reserve twelve words for every evaluation response."""
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
    """Refuse the 240-word freeze when either preregistered ample condition fails."""
    passing = AmplePilotSummary(
        outputs_within_ample_limit=57,
        all_approved_complete_responses_fit=True,
        result_record_sha256=ZERO_HASH,
    )
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
    """Derive the gate from ten use cases, three models, and two cues under absent integrity."""
    output_text = "Complete response."
    records = []
    index = 0
    for use_case_number in range(1, 11):
        for model_id in ["m1", "m2", "m3"]:
            for cue in EmotionalCueCondition:
                integrity = IntegrityCondition.ABSENT
                index += 1
                use_case_id = f"CF{use_case_number:03d}"
                payload = {
                    "schema_version": "1.0.0",
                    "pilot_record_id": f"PILOT_{index:016X}",
                    "scenario_id": f"{use_case_id}_C1",
                    "use_case_id": use_case_id,
                    "model_id": model_id,
                    "model_snapshot_sha256": ZERO_HASH,
                    "prompt_review_manifest_sha256": ZERO_HASH,
                    "expected_model_version": f"{model_id}@frozen",
                    "returned_model_version": f"{model_id}@frozen",
                    "emotional_cue": cue,
                    "integrity": integrity,
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
    summary = build_ample_pilot_summary(records, all_approved_complete_responses_fit=True)
    assert summary.outputs_within_ample_limit == 60
    with pytest.raises(ValueError, match="each use-case/model/cue"):
        build_ample_pilot_summary([records[0], *records[:-1]], all_approved_complete_responses_fit=True)


def test_prompt_review_can_only_approve_the_exact_active_cues() -> None:
    """Prevent a stale self-review record from freezing changed treatment wording."""
    common = {
        "schema_version": "1.0.0",
        "prompt_version": "v1",
        "neutral_cue": NEUTRAL_CUE,
        "worried_cue": WORRIED_CUE,
        "neutral_natural": True,
        "worried_natural": True,
        "semantic_request_equivalent": True,
        "urgency_confounded": False,
        "desired_detail_confounded": False,
        "decision_preference_confounded": False,
        "risk_appetite_confounded": False,
        "researcher_notes": "Reviewed before model calibration.",
        "decision": CueReviewDecision.APPROVE,
        "reviewed_by": "researcher",
        "reviewed_at": datetime(2026, 7, 19, tzinfo=timezone.utc),
        "manifest_sha256": ZERO_HASH,
    }
    assert PromptReviewManifest(**common).worried_cue == WORRIED_CUE
    with pytest.raises(ValidationError, match="exact active"):
        PromptReviewManifest(**{**common, "worried_cue": "I am very anxious and need urgent help."})
