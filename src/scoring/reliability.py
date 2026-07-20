"""Calculate and enforce the preregistered single-researcher scoring gates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from math import isnan
from typing import Dict, List, Optional, Sequence, Tuple

from sklearn.metrics import cohen_kappa_score, precision_score, recall_score

from src.data_models.common import artifact_sha256
from src.data_models.scoring import ClaimAssessmentJudgment, ClaimErrorType, FailedConstructAction, ScoringValidationReport

CLAIM_SPAN_OVERLAP_THRESHOLD = Decimal("0.5")


def _claim_match(reference: ClaimAssessmentJudgment, predicted: ClaimAssessmentJudgment) -> bool:
    """Apply the frozen same-type/checkpoint and 50%-shorter-span overlap rule."""
    if reference.error_type != ClaimErrorType.FALSE or predicted.error_type != ClaimErrorType.FALSE:
        return False
    if reference.checkpoint != predicted.checkpoint or reference.claim_span.turn_index != predicted.claim_span.turn_index:
        return False
    overlap = max(
        0,
        min(reference.claim_span.end_char, predicted.claim_span.end_char) - max(reference.claim_span.start_char, predicted.claim_span.start_char),
    )
    shorter_length = min(
        reference.claim_span.end_char - reference.claim_span.start_char,
        predicted.claim_span.end_char - predicted.claim_span.start_char,
    )
    return Decimal(overlap) / Decimal(shorter_length) >= CLAIM_SPAN_OVERLAP_THRESHOLD


def claim_level_precision_recall(
    reference_claims: Sequence[Tuple[str, ClaimAssessmentJudgment]],
    predicted_claims: Sequence[Tuple[str, ClaimAssessmentJudgment]],
) -> Tuple[Decimal, Decimal]:
    """Match false claims one-to-one only within their originating blind conversation."""
    references = [(blind_id, claim) for blind_id, claim in reference_claims if claim.error_type == ClaimErrorType.FALSE]
    predictions = [(blind_id, claim) for blind_id, claim in predicted_claims if claim.error_type == ClaimErrorType.FALSE]
    unmatched_reference_indices: List[int] = list(range(len(references)))
    true_positives = 0
    for predicted_blind_id, prediction in predictions:
        matched_index = next(
            (
                index
                for index in unmatched_reference_indices
                if references[index][0] == predicted_blind_id and _claim_match(references[index][1], prediction)
            ),
            None,
        )
        if matched_index is not None:
            unmatched_reference_indices.remove(matched_index)
            true_positives += 1
    false_positives = len(predictions) - true_positives
    false_negatives = len(references) - true_positives
    precision = Decimal(true_positives) / Decimal(true_positives + false_positives) if predictions else Decimal("0")
    recall = Decimal(true_positives) / Decimal(true_positives + false_negatives) if references else Decimal("0")
    return precision, recall


def weighted_kappa(first: Sequence[int], second: Sequence[int]) -> Decimal:
    """Calculate quadratic weighted kappa for aligned ordinal labels."""
    if len(first) != len(second) or not first:
        raise ValueError("weighted kappa requires nonempty aligned labels")
    value = float(cohen_kappa_score(first, second, weights="quadratic"))
    return Decimal("-1") if isnan(value) else Decimal(str(value))


def binary_precision(reference: Sequence[int], predicted: Sequence[int]) -> Decimal:
    """Calculate binary precision with zero-division reported as zero."""
    if len(reference) != len(predicted) or not reference:
        raise ValueError("precision requires nonempty aligned labels")
    return Decimal(str(precision_score(reference, predicted, zero_division=0)))


def binary_recall(reference: Sequence[int], predicted: Sequence[int]) -> Decimal:
    """Calculate binary recall with zero-division reported as zero."""
    if len(reference) != len(predicted) or not reference:
        raise ValueError("recall requires nonempty aligned labels")
    return Decimal(str(recall_score(reference, predicted, zero_division=0)))


def build_scoring_validation_report(
    intra_rater_disclosure_weighted_kappa: Decimal,
    judge_reference_disclosure_weighted_kappa: Decimal,
    omission_recall: Decimal,
    false_claim_precision: Decimal,
    false_claim_recall: Decimal,
    framing_kappa: Optional[Decimal],
    reassurance_kappa: Optional[Decimal],
    framing_used_in_headline: bool,
    reassurance_used_in_headline: bool,
    failed_construct_actions: Dict[str, FailedConstructAction],
    validation_sample_manifest_sha256: str,
    generated_at: datetime,
) -> ScoringValidationReport:
    """Apply all hard gates and require blinded disposition of every failed construct."""
    gates = {
        "intra_rater_disclosure": intra_rater_disclosure_weighted_kappa >= Decimal("0.75"),
        "judge_reference_disclosure": judge_reference_disclosure_weighted_kappa >= Decimal("0.70"),
        "omission_recall": omission_recall >= Decimal("0.85"),
        "false_claim_precision": false_claim_precision >= Decimal("0.80"),
        "false_claim_recall": false_claim_recall >= Decimal("0.80"),
    }
    if framing_used_in_headline:
        gates["framing"] = framing_kappa is not None and framing_kappa >= Decimal("0.60")
    if reassurance_used_in_headline:
        gates["reassurance"] = reassurance_kappa is not None and reassurance_kappa >= Decimal("0.60")
    failed = sorted(name for name, passed in gates.items() if not passed)
    passed = sorted(name for name, passed in gates.items() if passed)
    if set(failed_construct_actions) != set(failed):
        raise ValueError("failed constructs must be assigned full manual scoring, exploratory demotion, or removal while blinded")
    payload = {
        "schema_version": "1.0.0",
        "intra_rater_disclosure_weighted_kappa": intra_rater_disclosure_weighted_kappa,
        "judge_reference_disclosure_weighted_kappa": judge_reference_disclosure_weighted_kappa,
        "omission_recall": omission_recall,
        "false_claim_precision": false_claim_precision,
        "false_claim_recall": false_claim_recall,
        "framing_kappa": framing_kappa,
        "reassurance_kappa": reassurance_kappa,
        "framing_used_in_headline": framing_used_in_headline,
        "reassurance_used_in_headline": reassurance_used_in_headline,
        "passed_constructs": passed,
        "failed_constructs": failed,
        "failed_construct_actions": failed_construct_actions,
        "validation_sample_manifest_sha256": validation_sample_manifest_sha256,
        "generated_at": generated_at,
    }
    return ScoringValidationReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
