"""Descriptive grouped summaries without rankings or causal language."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Dict, List, Sequence

from pydantic import Field

from srcv2.common import ImmutableModel


class GroupObservation(ImmutableModel):
    """Store one outcome with a use-case or model-access grouping label."""

    group: str
    value: float


class DescriptiveSummary(ImmutableModel):
    """Report a group mean and sample size without comparative rank."""

    group: str
    mean: float
    sample_size: int = Field(ge=1)
    interpretation: str = Field(default="descriptive_only_no_ranking_or_causal_claim")


def summarize_groups(observations: Sequence[GroupObservation]) -> List[DescriptiveSummary]:
    """Calculate alphabetically ordered descriptive summaries without sorting by performance."""
    grouped: Dict[str, List[float]] = defaultdict(list)
    for observation in observations:
        grouped[observation.group].append(observation.value)
    return [DescriptiveSummary(group=group, mean=mean(grouped[group]), sample_size=len(grouped[group])) for group in sorted(grouped)]
