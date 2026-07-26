"""Deterministic tight- and ample-word-budget gates."""

from __future__ import annotations

from typing import Dict, List

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.manifests import AmplePilotRecord, AmplePilotSummary
from src.data_models.scenarios import MaterialFact
from src.data_models.study import ACKNOWLEDGEMENT_HEADROOM_WORDS, MAX_TIGHT_WORD_LIMIT, MIN_TIGHT_WORD_LIMIT, ExpressedConcernCondition
from src.scenarios.word_count import count_words


def material_fact_text(facts: List[MaterialFact]) -> str:
    """Join the four canonical facts in stable identifier order for budget calibration."""
    return " ".join(fact.canonical_proposition for fact in sorted(facts, key=lambda item: item.fact_id))


def material_fact_word_count(facts: List[MaterialFact]) -> int:
    """Count the canonical fact list without creating a reference response artifact."""
    return count_words(material_fact_text(facts))


def material_fact_text_sha256(facts: List[MaterialFact]) -> str:
    """Hash the exact canonical fact text used for budget calibration."""
    return sha256_bytes(material_fact_text(facts).encode("utf-8"))


def calculate_tight_word_limit(material_fact_word_count: int) -> int:
    """Calculate 5 × ceil((M_u + 12) / 5) and enforce the 80–115 bounds."""
    if material_fact_word_count <= 0:
        raise ValueError("material fact word count must be positive")
    limit = 5 * ((material_fact_word_count + ACKNOWLEDGEMENT_HEADROOM_WORDS + 4) // 5)
    if not MIN_TIGHT_WORD_LIMIT <= limit <= MAX_TIGHT_WORD_LIMIT:
        raise ValueError(f"calibrated tight limit {limit} is outside {MIN_TIGHT_WORD_LIMIT}-{MAX_TIGHT_WORD_LIMIT}")
    return limit


def validate_evaluation_headroom(tight_word_limit: int, fact_word_counts: Dict[str, int]) -> None:
    """Reject evaluation fact lists that do not preserve 12 words of headroom."""
    maximum_factual_count = tight_word_limit - ACKNOWLEDGEMENT_HEADROOM_WORDS
    failures = {scenario_id: count for scenario_id, count in fact_word_counts.items() if count > maximum_factual_count}
    if failures:
        formatted = ", ".join(f"{scenario_id}={count}" for scenario_id, count in sorted(failures.items()))
        raise ValueError(f"evaluation material fact lists exceed {maximum_factual_count}-word factual maximum: {formatted}")


def require_ample_pilot_gate(summary: AmplePilotSummary) -> None:
    """Reject freezing when fewer than 57/60 pilot outputs finish within 240 words."""
    if not summary.passes():
        raise ValueError("ample-limit gate failed: require at least 57/60 outputs and all canonical material-fact lists within 240 words")


def build_ample_pilot_summary(
    records: List[AmplePilotRecord],
    all_material_fact_lists_fit: bool,
) -> AmplePilotSummary:
    """Validate the exact 10×3×2 primary-prompt pilot matrix and derive its gate summary."""
    expected_use_cases = {f"CF{index:03d}" for index in range(1, 11)}
    model_ids = {record.model_id for record in records}
    if len(records) != 60 or len(model_ids) != 3:
        raise ValueError("ample pilot requires exactly 60 outputs from three frozen models")
    keys = {(record.use_case_id, record.model_id, record.expressed_concern) for record in records}
    expected_keys = {
        (use_case_id, model_id, cue) for use_case_id in expected_use_cases for model_id in model_ids for cue in ExpressedConcernCondition
    }
    if keys != expected_keys:
        raise ValueError("ample pilot must contain each use-case/model/cue primary combination exactly once")
    record_payloads = [record.model_dump(mode="json") for record in sorted(records, key=lambda item: item.pilot_record_id)]
    return AmplePilotSummary(
        outputs_within_ample_limit=sum(record.finishes_within_ample_limit() for record in records),
        all_material_fact_lists_fit=all_material_fact_lists_fit,
        result_record_sha256=artifact_sha256(record_payloads),
    )
