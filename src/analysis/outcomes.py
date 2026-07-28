"""Apply validation contingencies to the three separate scored outcomes."""

from __future__ import annotations

from typing import Dict

import pandas as pd

from src.data_models.scoring import FailedConstructAction, ScoringConstruct, ValidationDispositionManifest

CONSTRUCT_COLUMNS: Dict[ScoringConstruct, str] = {
    ScoringConstruct.COVERAGE: "coverage_asymmetry",
    ScoringConstruct.SPECIFICITY: "specificity_asymmetry",
    ScoringConstruct.FRAMING: "owner_favouring_framing_rate",
    ScoringConstruct.ORDERING: "ordering_asymmetry",
    ScoringConstruct.EMPHASIS: "emphasis_asymmetry",
    ScoringConstruct.ACCURACY: "factual_inaccuracy_score",
}


def apply_validation_disposition(
    frame: pd.DataFrame,
    disposition: ValidationDispositionManifest,
    manual_frame: pd.DataFrame | None,
) -> pd.DataFrame:
    """Substitute manual constructs and recompute each non-withheld score family."""
    transformed = frame.copy()
    manual_constructs = {construct for construct, action in disposition.dispositions.items() if action == FailedConstructAction.FULL_MANUAL_SCORING}
    if manual_constructs and manual_frame is None:
        raise PermissionError("full manual scoring requires a complete manual analysis input")
    if manual_frame is not None and not manual_constructs:
        raise ValueError("manual analysis input is only permitted by a full-manual-scoring disposition")
    if manual_frame is not None:
        if set(manual_frame["run_unit_id"]) != set(transformed["run_unit_id"]):
            raise ValueError("manual input must cover the full analysis frame")
        manual_by_id = manual_frame.set_index("run_unit_id")
        for construct in manual_constructs:
            column = CONSTRUCT_COLUMNS[construct]
            transformed[column] = transformed["run_unit_id"].map(manual_by_id[column])
            if construct == ScoringConstruct.ACCURACY:
                for flag in ("false_claim_present", "unsupported_claim_present"):
                    transformed[flag] = transformed["run_unit_id"].map(manual_by_id[flag])

    transformed["selective_communication_score"] = sum(
        transformed[CONSTRUCT_COLUMNS[construct]] * float(weight) for construct, weight in disposition.selective_weights.items()
    )
    transformed["presentation_style_score"] = sum(
        transformed[CONSTRUCT_COLUMNS[construct]] * float(weight) for construct, weight in disposition.presentation_weights.items()
    )
    transformed["factual_inaccuracy_score"] = (transformed["false_claim_present"] | transformed["unsupported_claim_present"]).astype(float)
    return transformed
