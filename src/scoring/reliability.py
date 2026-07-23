"""Calculate and enforce the preregistered single-researcher scoring gates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from math import isnan
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.metrics import cohen_kappa_score, confusion_matrix, f1_score, precision_score, recall_score

from src.data_models.common import artifact_sha256
from src.data_models.scoring import (
    ClaimAssessmentJudgment,
    ClaimErrorType,
    CompositeDomain,
    DomainValidationDiagnostics,
    DomainValidationGate,
    ScoringValidationReport,
)

CLAIM_SPAN_OVERLAP_THRESHOLD = Decimal("0.5")


def _clustered_agreement_interval(
    reference: Sequence[str],
    predicted: Sequence[str],
    cluster_ids: Sequence[str],
    seed: int,
    draws: int = 2_000,
) -> List[Decimal]:
    """Bootstrap exact agreement by blinded conversation cluster."""
    if len(reference) != len(predicted) or len(reference) != len(cluster_ids) or not reference:
        raise ValueError("agreement interval requires nonempty aligned labels and clusters")
    unique_clusters = sorted(set(cluster_ids))
    indices = {cluster: [index for index, value in enumerate(cluster_ids) if value == cluster] for cluster in unique_clusters}
    generator = np.random.default_rng(seed)
    estimates = []
    for _ in range(draws):
        sampled = generator.choice(unique_clusters, size=len(unique_clusters), replace=True)
        selected = [index for cluster in sampled for index in indices[str(cluster)]]
        estimates.append(sum(reference[index] == predicted[index] for index in selected) / len(selected))
    lower, upper = np.quantile(np.asarray(estimates), [0.025, 0.975])
    return [Decimal(str(lower)), Decimal(str(upper))]


def build_domain_validation_diagnostics(
    reference: Sequence[str],
    predicted: Sequence[str],
    cluster_ids: Sequence[str],
    positive_labels: Sequence[str],
    gate: DomainValidationGate,
    seed: int,
    salience_absolute_error: Optional[Decimal] = None,
    invalid_output_count: int = 0,
) -> DomainValidationDiagnostics:
    """Calculate complete blinded diagnostics and apply one frozen domain gate."""
    if len(reference) != len(predicted) or len(reference) != len(cluster_ids) or not reference:
        raise ValueError("domain validation requires nonempty aligned reference and predicted labels")
    labels = sorted(set(reference) | set(predicted))
    matrix = confusion_matrix(reference, predicted, labels=labels)
    nested_matrix = {
        reference_label: {predicted_label: int(matrix[row, column]) for column, predicted_label in enumerate(labels)}
        for row, reference_label in enumerate(labels)
    }
    agreement = Decimal(sum(left == right for left, right in zip(reference, predicted))) / Decimal(len(reference))
    precision = Decimal(str(precision_score(reference, predicted, labels=labels, average="macro", zero_division=0)))
    recall = Decimal(str(recall_score(reference, predicted, labels=labels, average="macro", zero_division=0)))
    f1 = Decimal(str(f1_score(reference, predicted, labels=labels, average="macro", zero_division=0)))
    positive = set(positive_labels)
    prevalence = Decimal(sum(label in positive for label in reference)) / Decimal(len(reference))
    passed = (
        agreement >= gate.minimum_agreement
        and precision >= gate.minimum_precision
        and recall >= gate.minimum_recall
        and f1 >= gate.minimum_f1
        and invalid_output_count <= gate.maximum_invalid_output_count
    )
    if gate.maximum_salience_absolute_error is not None:
        passed = passed and salience_absolute_error is not None and salience_absolute_error <= gate.maximum_salience_absolute_error
    return DomainValidationDiagnostics(
        prevalence=prevalence,
        agreement=agreement,
        confusion_matrix=nested_matrix,
        precision=precision,
        recall=recall,
        f1=f1,
        salience_absolute_error=salience_absolute_error,
        invalid_output_count=invalid_output_count,
        sample_size=len(reference),
        uncertainty_interval=_clustered_agreement_interval(reference, predicted, cluster_ids, seed),
        gate_passed=passed,
    )


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
    domain_diagnostics: Dict[CompositeDomain, DomainValidationDiagnostics],
    sample_size: int,
    domain_gate_manifest_sha256: str,
    validation_sample_manifest_sha256: str,
    generated_at: datetime,
) -> ScoringValidationReport:
    """Persist every frozen-domain diagnostic before any treatment labels are joined."""
    passed = sorted((domain for domain, values in domain_diagnostics.items() if values.gate_passed), key=lambda item: item.value)
    failed = sorted((domain for domain in CompositeDomain if domain not in passed), key=lambda item: item.value)
    payload = {
        "schema_version": "2.0.0",
        "sample_size": sample_size,
        "annotation_count_per_conversation": 1,
        "domain_diagnostics": domain_diagnostics,
        "passed_domains": passed,
        "failed_domains": failed,
        "invalid_output_count": sum(values.invalid_output_count for values in domain_diagnostics.values()),
        "domain_gate_manifest_sha256": domain_gate_manifest_sha256,
        "validation_sample_manifest_sha256": validation_sample_manifest_sha256,
        "generated_at": generated_at,
    }
    return ScoringValidationReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
