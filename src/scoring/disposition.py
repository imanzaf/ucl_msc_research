"""Build hashed blinded validation dispositions for separate score families."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict

from src.data_models.common import artifact_sha256
from src.data_models.scoring import (
    PRESENTATION_COMPONENT_WEIGHTS,
    SELECTIVE_COMPONENT_WEIGHTS,
    FailedConstructAction,
    ScoringConstruct,
    ScoringValidationReport,
    ValidationDispositionManifest,
)


def resulting_weights(
    frozen_weights: Dict[ScoringConstruct, Decimal],
    dispositions: Dict[ScoringConstruct, FailedConstructAction],
) -> Dict[ScoringConstruct, Decimal]:
    """Renormalise one score family after prespecified component removal."""
    removed = {construct for construct, action in dispositions.items() if action == FailedConstructAction.REMOVE_AND_RENORMALISE}
    retained = {construct: weight for construct, weight in frozen_weights.items() if construct not in removed}
    denominator = sum(retained.values(), Decimal("0"))
    if denominator == 0:
        raise ValueError("validation dispositions cannot remove every component in a score family")
    return {construct: Decimal("0") if construct in removed else weight / denominator for construct, weight in frozen_weights.items()}


def build_validation_disposition_manifest(
    report: ScoringValidationReport,
    dispositions: Dict[ScoringConstruct, FailedConstructAction],
    blinded_diagnostics_sha256: str,
    researcher_id: str,
    rationale: str,
    decided_at: datetime,
) -> ValidationDispositionManifest:
    """Bind one blinded contingency per failed scoring construct."""
    if set(dispositions) != set(report.failed_constructs):
        raise ValueError("validation dispositions must cover exactly the failed constructs")
    withheld = {construct for construct, action in dispositions.items() if action == FailedConstructAction.WITHHOLD_OUTCOME}
    payload = {
        "schema_version": "3.0.0",
        "validation_report_sha256": report.report_sha256,
        "blinded_diagnostics_sha256": blinded_diagnostics_sha256,
        "failed_constructs": report.failed_constructs,
        "dispositions": dispositions,
        "selective_weights": resulting_weights(
            SELECTIVE_COMPONENT_WEIGHTS,
            dispositions,
        ),
        "presentation_weights": resulting_weights(
            PRESENTATION_COMPONENT_WEIGHTS,
            dispositions,
        ),
        "confirmatory_inference_withheld": bool(withheld & set(SELECTIVE_COMPONENT_WEIGHTS)),
        "presentation_result_withheld": bool(withheld & set(PRESENTATION_COMPONENT_WEIGHTS)),
        "factual_inaccuracy_result_withheld": ScoringConstruct.ACCURACY in withheld,
        "treatment_labels_available_when_decided": False,
        "effect_estimates_available_when_decided": False,
        "researcher_id": researcher_id,
        "rationale": rationale,
        "decided_at": decided_at,
    }
    return ValidationDispositionManifest.model_validate({**payload, "manifest_sha256": artifact_sha256(payload)})
