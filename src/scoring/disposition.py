"""Build hashed blinded validation-disposition manifests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict

from src.data_models.common import artifact_sha256
from src.data_models.scoring import (
    FROZEN_COMPOSITE_WEIGHTS,
    CompositeDomain,
    FailedConstructAction,
    ScoringValidationReport,
    ValidationDispositionManifest,
)


def resulting_weights(dispositions: Dict[CompositeDomain, FailedConstructAction]) -> Dict[CompositeDomain, Decimal]:
    """Apply only the prespecified remove-and-renormalise contingency."""
    removed = {domain for domain, action in dispositions.items() if action == FailedConstructAction.REMOVE_AND_RENORMALISE}
    denominator = sum((weight for domain, weight in FROZEN_COMPOSITE_WEIGHTS.items() if domain not in removed), Decimal("0"))
    if denominator == 0:
        raise ValueError("validation dispositions cannot remove every domain")
    return {domain: Decimal("0") if domain in removed else weight / denominator for domain, weight in FROZEN_COMPOSITE_WEIGHTS.items()}


def build_validation_disposition_manifest(
    report: ScoringValidationReport,
    dispositions: Dict[CompositeDomain, FailedConstructAction],
    blinded_diagnostics_sha256: str,
    researcher_id: str,
    rationale: str,
    decided_at: datetime,
) -> ValidationDispositionManifest:
    """Bind one decision per failed domain before treatment labels are exposed."""
    payload = {
        "schema_version": "2.0.0",
        "validation_report_sha256": report.report_sha256,
        "blinded_diagnostics_sha256": blinded_diagnostics_sha256,
        "failed_domains": report.failed_domains,
        "dispositions": dispositions,
        "resulting_weights": resulting_weights(dispositions),
        "confirmatory_inference_withheld": any(action == FailedConstructAction.WITHHOLD_CONFIRMATORY_INFERENCE for action in dispositions.values()),
        "treatment_labels_available_when_decided": False,
        "effect_estimates_available_when_decided": False,
        "researcher_id": researcher_id,
        "rationale": rationale,
        "decided_at": decided_at,
    }
    return ValidationDispositionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
