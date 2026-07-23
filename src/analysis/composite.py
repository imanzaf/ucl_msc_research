"""Apply a frozen validation disposition to analysis-ready domain columns."""

from __future__ import annotations

import pandas as pd

from src.data_models.scoring import COMPOSITE_DOMAIN_COLUMNS, FailedConstructAction, ValidationDispositionManifest


def apply_validation_disposition(
    frame: pd.DataFrame,
    disposition: ValidationDispositionManifest,
    manual_frame: pd.DataFrame | None,
) -> pd.DataFrame:
    """Substitute manually scored domains and apply the disposition-defined weights."""
    transformed = frame.copy()
    manual_domains = {domain for domain, action in disposition.dispositions.items() if action == FailedConstructAction.FULL_MANUAL_SCORING}
    if manual_domains and manual_frame is None:
        raise PermissionError("full-manual-scoring disposition requires a complete manual-domain analysis input")
    if manual_frame is not None and not manual_domains:
        raise ValueError("manual-domain input is only permitted by a full-manual-scoring disposition")
    if manual_frame is not None:
        if set(manual_frame["run_unit_id"]) != set(transformed["run_unit_id"]):
            raise ValueError("manual-domain input must cover the full experiment sample")
        manual_by_id = manual_frame.set_index("run_unit_id")
        for domain in manual_domains:
            column = COMPOSITE_DOMAIN_COLUMNS[domain]
            transformed[column] = transformed["run_unit_id"].map(manual_by_id[column])
    transformed["selective_risk_communication_score"] = sum(
        transformed[COMPOSITE_DOMAIN_COLUMNS[domain]] * float(weight) for domain, weight in disposition.resulting_weights.items()
    )
    return transformed
