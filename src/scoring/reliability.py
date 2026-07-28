"""Calculate and enforce single-researcher scoring-construct gates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from src.data_models.common import artifact_sha256
from src.data_models.scoring import ConstructValidationDiagnostics, ConstructValidationGate, ScoringConstruct, ScoringValidationReport


def _clustered_agreement_interval(
    reference: Sequence[str],
    predicted: Sequence[str],
    cluster_ids: Sequence[str],
    seed: int,
    draws: int = 2_000,
) -> List[Decimal]:
    """Bootstrap exact agreement by blinded-conversation cluster."""
    if len(reference) != len(predicted) or len(reference) != len(cluster_ids) or not reference:
        raise ValueError("agreement interval requires aligned nonempty labels")
    unique_clusters = sorted(set(cluster_ids))
    indices = {cluster: [index for index, value in enumerate(cluster_ids) if value == cluster] for cluster in unique_clusters}
    generator = np.random.default_rng(seed)
    estimates = []
    for _ in range(draws):
        sampled = generator.choice(
            unique_clusters,
            size=len(unique_clusters),
            replace=True,
        )
        selected = [index for cluster in sampled for index in indices[str(cluster)]]
        estimates.append(sum(reference[index] == predicted[index] for index in selected) / len(selected))
    lower, upper = np.quantile(np.asarray(estimates), [0.025, 0.975])
    return [Decimal(str(lower)), Decimal(str(upper))]


def build_construct_validation_diagnostics(
    reference: Sequence[str],
    predicted: Sequence[str],
    cluster_ids: Sequence[str],
    positive_labels: Sequence[str],
    gate: ConstructValidationGate,
    seed: int,
    maximum_absolute_error: Optional[Decimal] = None,
    invalid_output_count: int = 0,
) -> ConstructValidationDiagnostics:
    """Calculate blinded classification and optional derived-span diagnostics."""
    if len(reference) != len(predicted) or len(reference) != len(cluster_ids) or not reference:
        raise ValueError("construct validation requires aligned nonempty labels")
    labels = sorted(set(reference) | set(predicted))
    matrix = confusion_matrix(reference, predicted, labels=labels)
    nested_matrix = {
        reference_label: {predicted_label: int(matrix[row, column]) for column, predicted_label in enumerate(labels)}
        for row, reference_label in enumerate(labels)
    }
    agreement = Decimal(sum(left == right for left, right in zip(reference, predicted))) / Decimal(len(reference))
    precision = Decimal(
        str(
            precision_score(
                reference,
                predicted,
                labels=labels,
                average="macro",
                zero_division=0,
            )
        )
    )
    recall = Decimal(
        str(
            recall_score(
                reference,
                predicted,
                labels=labels,
                average="macro",
                zero_division=0,
            )
        )
    )
    f1 = Decimal(
        str(
            f1_score(
                reference,
                predicted,
                labels=labels,
                average="macro",
                zero_division=0,
            )
        )
    )
    positive = set(positive_labels)
    prevalence = Decimal(sum(label in positive for label in reference)) / Decimal(len(reference))
    passed = (
        agreement >= gate.minimum_agreement
        and precision >= gate.minimum_precision
        and recall >= gate.minimum_recall
        and f1 >= gate.minimum_f1
        and invalid_output_count <= gate.maximum_invalid_output_count
    )
    if gate.maximum_absolute_error is not None:
        passed = passed and maximum_absolute_error is not None and maximum_absolute_error <= gate.maximum_absolute_error
    return ConstructValidationDiagnostics(
        prevalence=prevalence,
        agreement=agreement,
        confusion_matrix=nested_matrix,
        precision=precision,
        recall=recall,
        f1=f1,
        maximum_absolute_error=maximum_absolute_error,
        invalid_output_count=invalid_output_count,
        sample_size=len(reference),
        uncertainty_interval=_clustered_agreement_interval(
            reference,
            predicted,
            cluster_ids,
            seed,
        ),
        gate_passed=passed,
    )


def binary_precision(reference: Sequence[int], predicted: Sequence[int]) -> Decimal:
    """Calculate binary precision with zero division reported as zero."""
    if len(reference) != len(predicted) or not reference:
        raise ValueError("precision requires aligned nonempty labels")
    return Decimal(str(precision_score(reference, predicted, zero_division=0)))


def binary_recall(reference: Sequence[int], predicted: Sequence[int]) -> Decimal:
    """Calculate binary recall with zero division reported as zero."""
    if len(reference) != len(predicted) or not reference:
        raise ValueError("recall requires aligned nonempty labels")
    return Decimal(str(recall_score(reference, predicted, zero_division=0)))


def build_scoring_validation_report(
    construct_diagnostics: Dict[ScoringConstruct, ConstructValidationDiagnostics],
    sample_size: int,
    construct_gate_manifest_sha256: str,
    validation_sample_manifest_sha256: str,
    generated_at: datetime,
) -> ScoringValidationReport:
    """Persist every construct diagnostic before treatment labels are joined."""
    passed = sorted(
        (construct for construct, values in construct_diagnostics.items() if values.gate_passed),
        key=lambda item: item.value,
    )
    failed = sorted(
        (construct for construct in ScoringConstruct if construct not in passed),
        key=lambda item: item.value,
    )
    payload = {
        "schema_version": "3.0.0",
        "sample_size": sample_size,
        "annotation_count_per_conversation": 1,
        "construct_diagnostics": construct_diagnostics,
        "passed_constructs": passed,
        "failed_constructs": failed,
        "invalid_output_count": sum(values.invalid_output_count for values in construct_diagnostics.values()),
        "construct_gate_manifest_sha256": construct_gate_manifest_sha256,
        "validation_sample_manifest_sha256": validation_sample_manifest_sha256,
        "generated_at": generated_at,
    }
    return ScoringValidationReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
