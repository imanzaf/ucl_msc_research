"""Select use cases for the secondary source-order objective."""

from __future__ import annotations

from typing import Dict, List

import pandas as pd


def select_source_order_use_cases(frame: pd.DataFrame) -> Dict[str, List[str]]:
    """Select the two lowest- and two highest-gap use cases from canonical-order results."""
    required_columns = {"use_case_id", "source_order", "pairwise_disclosure_gap"}
    missing = required_columns - set(frame.columns)
    if missing:
        raise ValueError("source-order subset selection lacks columns: " + ", ".join(sorted(missing)))
    canonical = frame.loc[frame["source_order"] == "A"]
    means = canonical.groupby("use_case_id", observed=True)["pairwise_disclosure_gap"].mean()
    if len(means) != 10:
        raise ValueError("source-order subset selection requires all ten use cases")
    ranked = sorted(((float(score), str(use_case_id)) for use_case_id, score in means.items()), key=lambda item: (item[0], item[1]))
    return {
        "best": [use_case_id for _, use_case_id in ranked[:2]],
        "worst": [use_case_id for _, use_case_id in ranked[-2:]],
    }
